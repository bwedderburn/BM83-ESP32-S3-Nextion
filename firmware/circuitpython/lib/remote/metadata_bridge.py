"""Optional receive-only Mac Now Playing bridge over an existing Wi-Fi join.

The private profile enables a bounded, nonblocking UDP socket. This module
never joins a network, sends controls, or decides which Bluetooth source owns
the display. main.py supplies that transport/native-metadata precedence.
"""
import json
import time

PROFILE_PATH = "/.metadata_bridge.json"
MAX_PROFILE_BYTES = 512
MAX_PACKET_BYTES = 1400
MAX_TEXT_BYTES = 256
MAX_TIME_MS = 0xFFFFFFFE
MAX_RETIRED_SESSIONS = 8
TTL_S = 8.0
PACKETS_PER_POLL = 2
POLL_PERIOD_S = 0.05


def _hex_text(value, minimum, maximum):
    return (isinstance(value, str) and minimum <= len(value) <= maximum
            and all(char in "0123456789abcdefABCDEF" for char in value))


def _ipv4(value):
    if not isinstance(value, str):
        return False
    parts = value.split(".")
    return (len(parts) == 4 and all(
        part and part.isdigit() and len(part) <= 3
        and 0 <= int(part) <= 255 and str(int(part)) == part for part in parts))


def validate_profile(value):
    """Validate a private profile without including its contents in errors."""
    if not isinstance(value, dict) or type(value.get("v")) is not int or value["v"] != 1:
        raise ValueError("bridge profile version/type")
    if not _hex_text(value.get("token"), 32, 128):
        raise ValueError("bridge token format")
    port = value.get("port", 8766)
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("bridge port range/type")
    host = value.get("host_ip")
    if host is not None and not _ipv4(host):
        raise ValueError("bridge host IPv4 format")
    return {"v": 1, "token": value["token"], "port": port, "host_ip": host}


def load_profile(path=PROFILE_PATH):
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_PROFILE_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_PROFILE_BYTES:
        raise ValueError("bridge profile too large")
    return validate_profile(json.loads(raw))


def _time_ms(number):
    if number is not None and (type(number) is not int or not 0 <= number <= MAX_TIME_MS):
        raise ValueError("bridge packet time range/type")
    return number


def _packet(raw, token):
    """Return a complete validated snapshot; never salvage malformed fields."""
    value = json.loads(raw)
    if not isinstance(value, dict) or type(value.get("v")) is not int or value["v"] != 1:
        raise ValueError("bridge packet version/type")
    if not isinstance(value.get("token"), str) or value["token"] != token:
        raise ValueError("bridge packet token")
    if not _hex_text(value.get("session"), 8, 64):
        raise ValueError("bridge packet session")
    if type(value.get("seq")) is not int or value["seq"] < 0:
        raise ValueError("bridge packet sequence")
    if value.get("state") not in ("playing", "paused", "stopped"):
        raise ValueError("bridge packet state")
    result = {"state": value["state"]}
    for field in ("title", "artist", "album"):
        text = value.get(field, "")
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError("bridge packet text type/length")
        if any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise ValueError("bridge packet text control character")
        result[field] = text.strip()
    for field in ("duration_ms", "position_ms"):
        result[field] = _time_ms(value.get(field))
    return value["session"], value["seq"], result


class MetadataBridge:
    """Cache authenticated metadata with replay protection and a short lease."""

    def __init__(self, clock=None, log=print, profile_path=PROFILE_PATH,
                 profile=None, socket=None, radio=None, pool=None):
        self._clock = time.monotonic if clock is None else clock
        self._log = log
        self._profile_path = profile_path
        self._profile_input = profile
        self._provided_socket = socket
        self._radio = radio
        self._pool = pool
        self._socket = None
        self._profile = None
        self._buffer = None
        self._session = None
        self._seq = -1
        self._retired = []
        self._snapshot = None
        self._received_at = None
        self._last_poll_at = None
        self.enabled = False

    def _open_socket(self):
        if self._provided_socket is not None:
            self._socket = self._provided_socket
            return True
        radio = self._radio
        if radio is None:
            import wifi
            radio = wifi.radio
        if not radio.connected or radio.ipv4_address is None:
            self._log("[META WIFI] no existing Wi-Fi connection; bridge disabled")
            return False
        pool = self._pool
        if pool is None:
            import socketpool
            pool = socketpool.SocketPool(radio)
        self._pool = pool
        self._socket = pool.socket(pool.AF_INET, pool.SOCK_DGRAM)
        return True

    def _close_socket(self):
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:  # nosec B110
                # Best-effort cleanup still clears the failed socket below.
                pass
        self._socket = None

    def setup(self):
        """Open UDP once on an already joined radio; absent config is inert."""
        if self.enabled:
            return True
        try:
            self._profile = (validate_profile(self._profile_input) if self._profile_input is not None
                             else load_profile(self._profile_path))
        except (ValueError, TypeError, UnicodeError):
            self._log("[META WIFI] invalid private profile; bridge disabled")
            return False
        if self._profile is None:
            return False
        try:
            if not self._open_socket():
                return False
            self._socket.settimeout(0)
            # The paired LAN listener uses only the existing Wi-Fi radio.
            self._socket.bind(("0.0.0.0", self._profile["port"]))  # nosec B104
            self._buffer = bytearray(MAX_PACKET_BYTES + 1)
            self.enabled = True
            self._log("[META WIFI] receiver ready port=%d" % self._profile["port"])
            return True
        except Exception:
            self._close_socket()
            self._log("[META WIFI] socket unavailable; bridge disabled")
            return False

    def reset(self):
        """Drop displayed data while retaining accepted replay counters."""
        self._snapshot = self._received_at = None

    def _accept(self, raw, now):
        session, seq, data = _packet(raw, self._profile["token"])
        if session in self._retired or (session == self._session and seq <= self._seq):
            return
        if session != self._session:
            if self._session is not None:
                self._retired.append(self._session)
                self._retired = self._retired[-MAX_RETIRED_SESSIONS:]
            self._session = session
        self._seq = seq
        if data["state"] == "stopped" or not (data["title"] or data["artist"]):
            self.reset()
        else:
            self._snapshot = data
            self._received_at = now

    def poll(self, now=None):
        """Consume at most two datagrams per 50 ms; bad input never renews TTL."""
        if not self.enabled:
            return
        now = self._clock() if now is None else now
        if self._last_poll_at is not None and 0 <= now - self._last_poll_at < POLL_PERIOD_S:
            return
        self._last_poll_at = now
        for _ in range(PACKETS_PER_POLL):
            try:
                length, address = self._socket.recvfrom_into(self._buffer)
            except Exception:
                return
            if length < 1 or length > MAX_PACKET_BYTES:
                continue
            host = self._profile["host_ip"]
            if host is not None and (not address or address[0] != host):
                continue
            try:
                self._accept(bytes(self._buffer[:length]), now)
            except Exception:  # nosec B112
                # Network input must not unwind the UART/UI loop, including
                # decoder allocation or nesting failures on the small device.
                # Discard bad datagrams quietly to prevent a network log flood.
                continue

    def snapshot(self, now=None):
        """Return only fresh source data; clock rollback also invalidates it."""
        if self._snapshot is None or self._received_at is None:
            return None
        now = self._clock() if now is None else now
        age = now - self._received_at
        if age < 0 or age >= TTL_S:
            self.reset()
            return None
        return self._snapshot

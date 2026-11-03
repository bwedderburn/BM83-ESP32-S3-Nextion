"""Authenticated BMW1 UDP endpoint for the Universe 2026 badge add-on.

Inert unless the private ``/.badge_remote.json`` profile exists. It opens one
nonblocking UDP socket on an already joined Wi-Fi radio, never joins a
network, and never logs keys, datagrams or peer addresses. Every datagram is
HMAC-SHA256 authenticated (128-bit tag) before parsing; unauthenticated input
is dropped without a reply. Replies report cached observations only.

Wire format (shared with addons/universe-badge/apps/bm83_remote/protocol.py):
``b"BMW1." + 32 hex HMAC tag + b"." + JSON``.
"""
import binascii
import hashlib
import json
import os
import sys

from utils.ticks import ticks_ms, ticks_recent

PROFILE_PATH = "/.badge_remote.json"
MAX_PROFILE_BYTES = 512
DEFAULT_PORT = 8767
MAX_DATAGRAM = 1200
MAX_REQUEST = 256
MIN_DATAGRAM = 40
MAX_CLIENTS = 4
MAX_HANDSHAKES = 64
DATAGRAMS_PER_POLL = 2
POLL_PERIOD_MS = 20
STATS_PERIOD_S = 60.0
MAX_TIME_MS = 0xFFFFFFFE
TEXT_CHARS = 96
TEXT_JSON_BYTES = 200
EQ_CHARS = 48
PLAY_STATUSES = (0, 1, 2, 3, 4, 255)
SOURCES = ("avrcp", "mac")

TOKENS = ("STATUS", "BT_PREV", "BT_PLAY", "BT_NEXT", "BT_MUTE",
          "BT_VOLUP_P", "BT_VOLUP_R", "BT_VOLDN_P", "BT_VOLDN_R",
          "BT_POWER", "BT_PAIR", "BT_EQ", "BT_EBIND", "NET_RETRY",
          "BLE_PAUSE", "BLE_ENABLE")
# Bond erasure changes pairing state on every central. It stays local to the
# panel unless the private profile explicitly opts in.
BOND_TOKENS = ("BT_EBIND",)
BLE_TOKENS = (b"BLE_PAUSE", b"BLE_ENABLE")


def _hex(value, size):
    return (isinstance(value, str) and len(value) == size
            and all(char in "0123456789abcdef" for char in value))


def _uint(value, maximum=0xFFFFFFFF):
    return type(value) is int and 0 <= value <= maximum


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
        raise ValueError("badge profile version/type")
    if not _hex(value.get("key"), 64):
        raise ValueError("badge key format")
    port = value.get("port", DEFAULT_PORT)
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("badge port range/type")
    client_ip = value.get("client_ip")
    if client_ip is not None and not _ipv4(client_ip):
        raise ValueError("badge client IPv4 format")
    allow_bonds = value.get("allow_bond_erase", False)
    if type(allow_bonds) is not bool:
        raise ValueError("badge bond-erase flag type")
    return {"v": 1, "key": binascii.unhexlify(value["key"]), "port": port,
            "client_ip": client_ip, "allow_bond_erase": allow_bonds}


def load_profile(path=PROFILE_PATH):
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_PROFILE_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_PROFILE_BYTES:
        raise ValueError("badge profile too large")
    return validate_profile(json.loads(raw))


def _hash_runtime_safe():
    """Refuse unpatched embedded PSA without allocating a probe context."""
    name = getattr(getattr(sys, "implementation", None), "name", "")
    return (name in ("cpython", "pypy")
            or getattr(hashlib, "_deinit_supported", False) is True)


def _sha256(data):
    if not _hash_runtime_safe():
        raise RuntimeError("Native hash cleanup requires the reviewed runtime")
    digest = hashlib.new("sha256")
    deinit = getattr(digest, "deinit", None)
    try:
        if (getattr(getattr(sys, "implementation", None), "name", "") not in ("cpython", "pypy")
                and not callable(deinit)):
            raise RuntimeError("Native hash cleanup API unavailable")
        digest.update(data)
        return digest.digest()
    finally:
        if callable(deinit):
            deinit()


def tag(key, payload):
    """Hex HMAC-SHA256 truncated to 16 bytes, matching the badge client."""
    if len(key) != 32:
        raise ValueError("BMW1 needs a 32-byte key")
    block = key + bytes(32)
    inner = bytes(byte ^ 0x36 for byte in block)
    outer = bytes(byte ^ 0x5C for byte in block)
    return binascii.hexlify(_sha256(outer + _sha256(inner + payload))[:16])


def json_text(value):
    """Compact deterministic JSON; non-ASCII text stays UTF-8."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if type(value) is int:
        return str(value)
    if isinstance(value, str):
        out = ['"']
        for char in value:
            code = ord(char)
            if char == '"':
                out.append('\\"')
            elif char == "\\":
                out.append("\\\\")
            elif code < 32 or code == 127:
                out.append("\\u%04x" % code)
            else:
                out.append(char)
        out.append('"')
        return "".join(out)
    if isinstance(value, dict):
        return "{" + ",".join(json_text(key) + ":" + json_text(item)
                              for key, item in value.items()) + "}"
    raise ValueError("Unsupported BMW1 JSON value")


def encode(key, message, maximum=MAX_DATAGRAM):
    payload = json_text(message).encode("utf-8")
    wire = b"BMW1." + tag(key, payload) + b"." + payload
    if len(wire) > maximum:
        raise ValueError("BMW1 reply too large")
    return wire


def decode(key, wire, maximum=MAX_REQUEST):
    """Authenticate before parsing; return a v1 mapping or None."""
    if (len(wire) > maximum or len(wire) < MIN_DATAGRAM or wire[:5] != b"BMW1."
            or wire[37:38] != b"."):
        return None
    expected = tag(key, wire[38:])
    difference = 0
    for index in range(32):
        difference |= expected[index] ^ wire[index + 5]
    if difference:
        return None
    try:
        value = json.loads(wire[38:].decode("utf-8"))
    except (ValueError, UnicodeError):
        return None
    if not isinstance(value, dict) or type(value.get("v")) is not int or value["v"] != 1:
        return None
    return value


def fit_text(text, chars=TEXT_CHARS, json_bytes=TEXT_JSON_BYTES):
    """Clip on character boundaries so the escaped JSON stays bounded."""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8", "replace")
    text = str(text or "")[:chars]
    while text and len(json_text(text).encode("utf-8")) > json_bytes:
        text = text[:-1]
    return text


def _time(value):
    return value if _uint(value, MAX_TIME_MS) else None


def np_from_snapshot(snapshot, eq_label, source=""):
    """Map StatePublisher.snapshot() to the badge's validated np contract."""
    status = snapshot.get("play_status")
    value = {
        "power_on": bool(snapshot.get("power_on")),
        "connected": bool(snapshot.get("connected")),
        "aux": bool(snapshot.get("aux")),
        "clock_advancing": bool(snapshot.get("clock_advancing")),
        "play_status": status if type(status) is int and status in PLAY_STATUSES else 255,
        "eq_index": snapshot.get("eq_index") if _uint(snapshot.get("eq_index"), 255) else 0,
        "eq": fit_text(eq_label, EQ_CHARS, EQ_CHARS + 2),
        "duration_ms": _time(snapshot.get("duration_ms")),
        "position_ms": _time(snapshot.get("position_ms")),
        "position_age_ms": _time(snapshot.get("position_age_ms")),
        "title": fit_text(snapshot.get("title")),
        "artist": fit_text(snapshot.get("artist")),
        "album": fit_text(snapshot.get("album")),
    }
    if value["position_ms"] is None:
        value["position_age_ms"] = None
    # The text origin is a fact the badge may show; never guess it.
    value["src"] = source if source in SOURCES and (value["title"] or value["artist"]) else ""
    return value


def ble_fields(status):
    """Validate one BleHid.snapshot_status() mapping into BMW1 ble fields."""
    if not isinstance(status, dict):
        raise ValueError("BLE status must be a mapping")
    mode, error = status.get("mode"), status.get("error")
    if not _uint(mode, 3) or not _uint(error, 7):
        raise ValueError("BLE status mode/error")
    flags = 0
    for field, bit in (("intent_enabled", 1), ("ready", 2), ("connected", 4), ("advertising", 8)):
        if type(status.get(field)) is not bool:
            raise ValueError("BLE status observations must be booleans")
        if status[field]:
            flags |= bit
    if (mode == 0 and (not flags & 1 or error)
            or mode == 1 and (flags & 1 or error)
            or mode == 2 and (flags != 2 or error)
            or mode == 3 and not error):
        raise ValueError("Inconsistent BLE status")
    return mode, flags, error


class BadgeRemote:
    """One bounded UDP endpoint: hello/welcome, deduplicated commands, state."""

    def __init__(self, clock=None, log=print, profile_path=PROFILE_PATH, profile=None,
                 socket=None, radio=None, pool=None, urandom=os.urandom, ticks=None):
        # Keep the seconds clock/now API for stats; sub-second pacing always
        # uses integer hardware ticks (or an explicitly injected test clock).
        self._ticks = ticks_ms if ticks is None else ticks
        if clock is None:
            import time
            clock = time.monotonic
        self._clock = clock
        self._log = log
        self._profile_path = profile_path
        self._profile_input = profile
        self._provided_socket = socket
        self._radio = radio
        self._pool = pool
        self._urandom = urandom
        self._socket = None
        self._profile = None
        self._buffer = None
        self._clients = []
        self._seen_hellos = None
        self._hello_count = 0
        self._touch = 0
        self._next_client = 0
        self._last_poll_at = None
        self._ble_requests = []
        self._ble_request = (None, None)
        self._ble_session = 0
        self._ble_sequence = 0
        self._stats = [0, 0, 0, 0]  # ok, bad, dup, denied
        self._stats_last = None
        self._stats_at = None
        self.unit = None
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
            self._log("[BADGE] no existing Wi-Fi connection; badge remote disabled")
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
            self._log("[BADGE] invalid private profile; badge remote disabled")
            return False
        if self._profile is None:
            return False
        if not _hash_runtime_safe():
            self._log("[BADGE] native hash cleanup unavailable; reviewed runtime required")
            return False
        try:
            if not self._open_socket():
                return False
            self._socket.settimeout(0)
            # Authenticated LAN endpoint on the existing Wi-Fi interface only.
            self._socket.bind(("0.0.0.0", self._profile["port"]))  # nosec B104
            self._buffer = bytearray(MAX_REQUEST + 1)
            unit = "00000000"
            while unit == "00000000":
                unit = binascii.hexlify(self._urandom(4)).decode()
            self.unit = unit
            self._next_client = (int.from_bytes(self._urandom(3), "big") or 1)
            self._ble_session = int.from_bytes(self._urandom(4), "big")
            self._clients = []
            self._seen_hellos = bytearray(MAX_HANDSHAKES * 8)
            self._hello_count = 0
            self._touch = 0
            self._last_poll_at = None
            self.enabled = True
            self._log("[BADGE] remote ready port=%d bond_erase=%s" % (
                self._profile["port"], "allowed" if self._profile["allow_bond_erase"] else "local-only"))
            return True
        except Exception:
            self._close_socket()
            self._log("[BADGE] socket unavailable; badge remote disabled")
            return False

    def take_ble_request(self, token):
        """Consume one accepted badge BLE request: (client, seq) or None."""
        for index, (queued, client, seq) in enumerate(self._ble_requests):
            if queued == token:
                self._ble_requests.pop(index)
                return client, seq
        return None

    def note_ble_request(self, origin):
        """Record which request the BLE backend applied last.

        ``origin`` is (client, seq) for a badge request, or None when another
        remote's request superseded it, so the badge reports "superseded".
        """
        self._ble_request = origin if origin is not None else (None, None)

    def _client(self, client_id):
        for entry in self._clients:
            if entry[0] == client_id:
                return entry
        return None

    def _welcome(self, nonce):
        for entry in self._clients:
            if entry[4] == nonce:
                # A lost welcome retries the same session, without resetting
                # its sequence watermark or making a replay refresh the LRU.
                return {"v": 1, "type": "welcome", "nonce": nonce,
                        "unit": self.unit, "client": entry[0]}
        nonce_bytes = binascii.unhexlify(nonce)
        # Retain retired nonces for this boot. Forgetting them would let a set
        # of recorded HELLOs continually rotate the live four-client table.
        # Once the bounded ledger fills, existing sessions/retries still work;
        # admitting a new handshake requires a local receiver restart.
        for index in range(self._hello_count):
            if self._seen_hellos[index * 8:index * 8 + 8] == nonce_bytes:
                return None
        if self._hello_count >= MAX_HANDSHAKES:
            return None
        offset = self._hello_count * 8
        self._seen_hellos[offset:offset + 8] = nonce_bytes
        self._hello_count += 1
        client_id = self._next_client
        self._next_client = (self._next_client % 0xFFFFFFFF) + 1
        if len(self._clients) >= MAX_CLIENTS:
            self._clients.sort(key=lambda entry: entry[2])
            self._clients.pop(0)
        self._touch += 1
        # [client id, last seq, LRU touch, last seq was refused, hello nonce]
        self._clients.append([client_id, 0, self._touch, False, nonce])
        self._log("[BADGE] client %d authenticated" % client_id)
        return {"v": 1, "type": "welcome", "nonce": nonce, "unit": self.unit, "client": client_id}

    def _state(self, state_fn, client_id, seq, dup, denied, include_ble=True):
        np_value, ble_status = state_fn()
        message = {"v": 1, "type": "state", "unit": self.unit, "client": client_id,
                   "seq": seq, "dup": dup, "np": np_value, "ble": None}
        # A reply built before a BLE request is dispatched would carry a newer
        # sequence with the previous request echo, which the badge correctly
        # reads as "superseded". Only post-dispatch observations carry ble.
        if ble_status is not None and include_ble and not self._ble_requests:
            try:
                mode, flags, error = ble_fields(ble_status)
            except Exception:
                mode, flags, error = 3, 0, 6
            self._ble_sequence = (self._ble_sequence + 1) & 0xFFFFFFFF
            req_client, req_seq = self._ble_request
            message["ble"] = {"session": self._ble_session, "sequence": self._ble_sequence,
                              "mode": mode, "flags": flags, "error": error,
                              "req_client": req_client, "req_seq": req_seq}
        if denied:
            message["denied"] = True
        return message

    def _handle(self, value, state_fn):
        """Return (reply message or None, token to dispatch or None).

        Once a sequence is recorded its token is returned even if the reply
        cannot be built, because the badge's retry will then receive dup=true
        and must not be told about a command that never ran.
        """
        kind = value.get("type")
        if kind == "hello":
            nonce = value.get("nonce")
            if not _hex(nonce, 16):
                return None, None
            return self._welcome(nonce), None
        if kind != "cmd":
            return None, None
        return self._command(value, state_fn)

    def _command(self, value, state_fn):
        client_id, seq, command = value.get("client"), value.get("seq"), value.get("token")
        if not _uint(client_id) or client_id == 0 or not _uint(seq) or command not in TOKENS:
            return None, None
        entry = self._client(client_id)
        if value.get("unit") != self.unit or entry is None:
            return {"v": 1, "type": "rehello", "client": client_id, "seq": seq}, None
        self._touch += 1
        entry[2] = self._touch
        if seq == entry[1] and seq != 0:
            self._stats[2] += 1
            # A retry after a lost reply must still learn the command was refused.
            return self._state(state_fn, client_id, seq, True, entry[3]), None
        if seq < entry[1] or seq == 0:
            return None, None
        entry[1] = seq
        # VM teardown can hard-fault this runtime; a remote must not reload it.
        denied = (command == "NET_RETRY"
                  or (command in BOND_TOKENS and not self._profile["allow_bond_erase"]))
        entry[3] = denied
        dispatch = self._accept(command, client_id, seq, denied)
        try:
            reply = self._state(state_fn, client_id, seq, False, denied,
                                include_ble=dispatch not in BLE_TOKENS)
        except Exception:
            reply = None
        return reply, dispatch

    def _accept(self, command, client_id, seq, denied):
        """Record a new sequence; return the UART token to dispatch, if any."""
        if denied:
            self._stats[3] += 1
            reason = ("receiver retry unavailable; use local maintenance"
                      if command == "NET_RETRY" else "bond erase is local-only")
            self._log("[BADGE] %s refused (%s)" % (command, reason))
            return None
        if command == "STATUS":
            return None
        dispatch = command.encode()
        if dispatch in BLE_TOKENS:
            self._ble_requests.append((dispatch, client_id, seq))
            if len(self._ble_requests) > 4:
                self._ble_requests.pop(0)
        self._log("[BADGE] %s client=%d seq=%d" % (command, client_id, seq))
        return dispatch

    def poll(self, state_fn, now=None):
        """Service at most two datagrams per 20 ms; return tokens to dispatch.

        ``state_fn()`` returns ``(np, ble_status_or_None)`` and is called only
        for authenticated commands. Replies precede dispatch, so they confirm
        receipt; the next STATUS reply shows the outcome.
        """
        if not self.enabled:
            return ()
        # BLE request context is valid only for the loop pass that returned
        # its token; never let a later fabricated token inherit it.
        self._ble_requests = []
        now = self._clock() if now is None else now
        tick = self._ticks()
        if ticks_recent(tick, self._last_poll_at, POLL_PERIOD_MS):
            return ()
        self._last_poll_at = tick
        tokens = None
        for _ in range(DATAGRAMS_PER_POLL):
            try:
                length, address = self._socket.recvfrom_into(self._buffer)
            except Exception:
                break
            token = self._service(length, address, state_fn)
            if token is not None:
                if tokens is None:
                    tokens = []
                tokens.append(token)
        self._tick_stats(now)
        return tokens if tokens else ()

    def _accepts(self, length, address):
        client_ip = self._profile["client_ip"]
        return (MIN_DATAGRAM <= length <= MAX_REQUEST
                and (client_ip is None or (address and address[0] == client_ip)))

    def _service(self, length, address, state_fn):
        """Authenticate, reply to and return the token of one datagram."""
        if not self._accepts(length, address):
            self._stats[1] += 1
            return None
        try:
            value = decode(self._profile["key"], bytes(self._buffer[:length]))
            reply, token = self._handle(value, state_fn) if value is not None else (None, None)
        except Exception:
            reply, token = None, None
        if reply is None:
            if token is None:
                self._stats[1] += 1
            return token
        self._stats[0] += 1
        try:
            self._socket.sendto(encode(self._profile["key"], reply), address)
        except Exception:  # nosec B110
            # Network output must never unwind the UART/UI loop; the badge
            # retries with the same seq and receives dup=true.
            pass
        return token

    def _tick_stats(self, now):
        if self._stats_at is not None and 0 <= now - self._stats_at < STATS_PERIOD_S:
            return
        self._stats_at = now
        snap = tuple(self._stats)
        if snap != self._stats_last and any(snap):
            self._stats_last = snap
            self._log("[BADGE] rx ok=%d bad=%d dup=%d denied=%d" % snap)

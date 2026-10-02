"""ESP-NOW receiver for the CrowPanel wireless remote.

Protocol v1 (shared with firmware/crowpanel-remote/include/espnow_link.h):

    token frame  (remote -> audio unit):  b"BMR1:<seq>:<token>"
    state frame  (audio unit -> remote):  b"BMS1:<seq>:<key>=<val>"  (reserved)

ASCII, at most 64 bytes. <token> is exactly the Nextion token vocabulary
(``nextion.display.TOKENS``), so main.py merges remote tokens into the
panel's token list and the existing dispatch applies unchanged: aux_mode
gating of transport controls, the EBIND debounce and volume
hold-and-repeat included. <seq> is a decimal uint32 that exists only so
duplicate deliveries can be dropped.

Failure-mode rules this module follows:

* It never raises into the main loop. Every radio call is guarded; a radio
  error pauses polling for a bounded back-off, then polling resumes.
* poll() is non-blocking and drains at most ``max_frames`` per call.
* Frames from any MAC other than the paired remote are dropped. This fails
  closed on purpose: the vocabulary includes BT_EBIND, a bond wipe.
* Without an ``espnow`` module (host tests, or a CircuitPython build that
  lacks it) the receiver reports itself off and poll() returns ().
"""

import time

try:
    import espnow as _espnow
except ImportError:  # host Python, or a CircuitPython build without espnow
    _espnow = None

from nextion.display import TOKENS as NEXTION_TOKENS

FRAME_PREFIX = b"BMR1:"
# Channel-discovery probe from the remote. Its only job is to be ACKed by
# this radio's hardware so the remote can find our channel; it is ignored
# here (counted as a probe, not as a bad frame).
PROBE_FRAME = b"BMP1"
MAX_FRAME_LEN = 64
MAX_SEQ = 0xFFFFFFFF
# A radio-level duplicate lands milliseconds after the original; a remote
# reboot (seq restarts at 1) takes seconds. Only an identical seq inside
# this window counts as a duplicate.
DUP_WINDOW_S = 2.0
# After a radio error, stop polling for this long, then try again.
ERROR_BACKOFF_S = 5.0
# Counter summary at most this often, and only when something changed.
STATS_PERIOD_S = 60.0
# Log each foreign sender once, for at most this many distinct MACs.
MAX_FOREIGN_LOGGED = 4
# CircuitPython 10.0.x ships ESP-IDF 5.4.1, whose WiFi/BLE coexistence
# cannot keep ESP-NOW reception alive while BLE is active: on the bench
# (2026-10-01) the unit went deaf to the remote within 0-2.5 min of every
# restart with BLE on, and stayed reachable for minutes with BLE off
# (espressif/esp-idf#17874). CircuitPython 10.1+ ships ESP-IDF 5.5.1 with
# the coexistence fix, so below that the receiver refuses to start alongside
# BLE: the WiFi radio stays off and BLE HID keeps the RF to itself.
MIN_CIRCUITPY_WITH_BLE = (10, 1, 0)

_HEX = "0123456789abcdefABCDEF"


def mac_to_bytes(mac):
    """'44:1B:F6:8A:C1:7C' (or 6 raw bytes) -> 6 raw bytes; None if malformed."""
    if isinstance(mac, (bytes, bytearray)):
        return bytes(mac) if len(mac) == 6 else None
    if not isinstance(mac, str):
        return None
    parts = mac.split(":")
    if len(parts) != 6:
        return None
    out = bytearray(6)
    for i, part in enumerate(parts):
        if len(part) != 2 or part[0] not in _HEX or part[1] not in _HEX:
            return None
        out[i] = int(part, 16)
    return bytes(out)


def fmt_mac(mac):
    """6 raw bytes -> 'AA:BB:CC:DD:EE:FF' (CircuitPython lacks bytes.hex(sep))."""
    if mac is None:
        return "?"
    try:
        return ":".join("%02X" % b for b in mac)
    except TypeError:
        return repr(mac)


def parse_frame(msg, vocabulary=NEXTION_TOKENS):
    """Return (seq, token) for a well-formed BMR1 frame, else None.

    Strict on purpose: exact prefix, 1-10 ASCII digits, one ':' and a token
    that is a member of ``vocabulary``. Anything else is noise.
    """
    if not msg or len(msg) > MAX_FRAME_LEN:
        return None
    msg = bytes(msg)
    if not msg.startswith(FRAME_PREFIX):
        return None
    body = msg[len(FRAME_PREFIX):]
    sep = body.find(b":")
    if sep < 1 or sep > 10:
        return None
    digits = body[:sep]
    for c in digits:
        if c < 0x30 or c > 0x39:
            return None
    seq = int(digits)
    if seq > MAX_SEQ:
        return None
    token = body[sep + 1:]
    if token not in vocabulary:
        return None
    return seq, token


def runtime_version():
    """(implementation name, (major, minor, micro)) of the running Python."""
    try:
        import sys
        impl = sys.implementation
        return impl.name, tuple(impl.version[:3])
    except Exception:
        return "unknown", (0, 0, 0)


class EspNowRemote:
    """Non-blocking ESP-NOW receiver that yields Nextion-vocabulary tokens.

    main.py usage::

        remote = EspNowRemote(enabled=REMOTE_ENABLED, peer_mac=REMOTE_MAC)
        remote.setup()
        ...
        remote_tokens = remote.poll()   # () when idle, else a list of tokens

    ``peer_mac=None`` accepts any sender (bring-up only). ``ble_active``
    tells the receiver whether BLE runs alongside it (see
    MIN_CIRCUITPY_WITH_BLE). ``espnow_module``, ``clock`` and ``runtime`` are
    injectable for host tests.
    """

    def __init__(self, enabled=True, peer_mac=None, vocabulary=NEXTION_TOKENS,
                 espnow_module=None, clock=None, log=print, ble_active=False,
                 runtime=None):
        self.want = enabled
        self.ble_active = ble_active
        self._runtime = runtime_version() if runtime is None else runtime
        self.vocabulary = vocabulary
        self._peer_mac_cfg = peer_mac
        self.peer_mac = None
        self._mod = _espnow if espnow_module is None else espnow_module
        self._clock = time.monotonic if clock is None else clock
        self._log = log
        self._radio = None
        self.enabled = False
        self.rx_ok = 0
        self.rx_dup = 0
        self.rx_foreign = 0
        self.rx_bad = 0
        self.rx_err = 0
        self.rx_probe = 0
        self._last_seq = None
        self._last_seq_at = 0.0
        self._paused_until = 0.0
        self._foreign_seen = []
        self._stats_at = 0.0
        self._stats_last = None

    def setup(self):
        """Bring the receiver up. Never raises; returns True when live."""
        if not self.want:
            self._log("[REMOTE] disabled by config (REMOTE_ENABLED = False)")
            return False
        if self._peer_mac_cfg is not None:
            self.peer_mac = mac_to_bytes(self._peer_mac_cfg)
            if self.peer_mac is None:
                self._log("[REMOTE] bad REMOTE_MAC %r -> receiver off" % (self._peer_mac_cfg,))
                return False
        if self._mod is None:
            self._log("[REMOTE] no espnow module in this build -> receiver off")
            return False
        name, version = self._runtime
        if self.ble_active and name == "circuitpython" and version < MIN_CIRCUITPY_WITH_BLE:
            self._log("[REMOTE] CircuitPython %d.%d.%d + BLE: ESP-NOW reception drops out "
                      "(ESP-IDF 5.4.1 coexistence fault) -> receiver off, WiFi radio left "
                      "off; upgrade CircuitPython to 10.1+" % version)
            return False
        try:
            self._radio = self._mod.ESPNow()
        except Exception as e:  # WiFi/ESP-NOW bring-up must never kill main.py
            self._radio = None
            self._log("[REMOTE] ESP-NOW init failed: %r -> receiver off" % (e,))
            return False
        wifi_ps = self._keep_radio_awake()
        self.enabled = True
        self._stats_at = self._clock()
        self._log("[REMOTE] ESP-NOW receiver up: own-sta=%s accepting=%s wifi-ps=%s" % (
            self._own_mac(), fmt_mac(self.peer_mac) if self.peer_mac else "any MAC", wifi_ps))
        return True

    @staticmethod
    def _keep_radio_awake():
        # A modem-sleeping unassociated STA neither hears nor ACKs the
        # remote, so ask for no power save and report what the stack kept
        # (ESP-IDF may refuse NONE alongside BLE). Hygiene, not the cure: on
        # CircuitPython 10.0.x the BLE coexistence fault still deafened the
        # radio with this set - see MIN_CIRCUITPY_WITH_BLE.
        try:
            import wifi
            wifi.radio.power_management = wifi.PowerManagement.NONE
            pm = wifi.radio.power_management
            return "NONE" if pm == wifi.PowerManagement.NONE else "kept %s" % (pm,)
        except Exception as e:
            return "unchanged (%r)" % (e,)

    @staticmethod
    def _own_mac():
        # The remote must unicast to this exact MAC — print it at boot so a
        # mismatch with the remote's PEER_MAC is obvious in the log.
        try:
            import wifi  # CircuitPython; ESPNow() above already started the radio
            return fmt_mac(wifi.radio.mac_address)
        except Exception:
            return "?"

    def poll(self, max_frames=4):
        """Drain up to ``max_frames`` packets; return accepted tokens, or ()."""
        if not self.enabled:
            return ()
        now = self._clock()
        self._tick_stats(now)
        if now < self._paused_until:
            return ()
        tokens = None
        try:
            if not self._radio:  # ESPNow is falsy when nothing is buffered
                return ()
            for _ in range(max_frames):
                pkt = self._radio.read()
                if pkt is None:
                    break
                tok = self.accept(pkt.mac, pkt.msg, now, getattr(pkt, "rssi", None))
                if tok is not None:
                    if tokens is None:
                        tokens = []
                    tokens.append(tok)
        except Exception as e:  # never propagate into the main loop
            self.rx_err += 1
            self._paused_until = now + ERROR_BACKOFF_S
            self._log("[REMOTE] ESP-NOW read error #%d: %r -> pausing %.0fs" % (
                self.rx_err, e, ERROR_BACKOFF_S))
        return tokens if tokens else ()

    def accept(self, mac, msg, now, rssi=None):
        """Validate one received frame; return its token or None."""
        if self.peer_mac is not None and bytes(mac) != self.peer_mac:
            self.rx_foreign += 1
            self._note_foreign(mac)
            return None
        if msg == PROBE_FRAME:
            self.rx_probe += 1
            return None
        parsed = parse_frame(msg, self.vocabulary)
        if parsed is None:
            self.rx_bad += 1
            return None
        seq, token = parsed
        if seq == self._last_seq and (now - self._last_seq_at) < DUP_WINDOW_S:
            self.rx_dup += 1
            return None
        self._last_seq = seq
        self._last_seq_at = now
        self.rx_ok += 1
        if rssi is None:
            self._log("[REMOTE] %s seq=%d" % (token.decode(), seq))
        else:
            self._log("[REMOTE] %s seq=%d rssi=%d" % (token.decode(), seq, rssi))
        return token

    def _note_foreign(self, mac):
        mac = bytes(mac)
        if mac in self._foreign_seen or len(self._foreign_seen) >= MAX_FOREIGN_LOGGED:
            return
        self._foreign_seen.append(mac)
        self._log("[REMOTE] ignoring ESP-NOW from %s (paired remote is %s)" % (
            fmt_mac(mac), fmt_mac(self.peer_mac)))

    def _tick_stats(self, now):
        if now - self._stats_at < STATS_PERIOD_S:
            return
        self._stats_at = now
        snap = (self.rx_ok, self.rx_dup, self.rx_foreign, self.rx_bad, self.rx_err,
                self.rx_probe)
        if snap == self._stats_last:
            return
        self._stats_last = snap
        self._log("[REMOTE] rx ok=%d dup=%d foreign=%d bad=%d err=%d probe=%d" % snap)

"""Observed BLE volume-remote state, separate from BMS2 audio metadata.

BLS1 is one 19-byte frame: magic, boot session u32, sequence u16, mode,
flags, last validated BLE control sequence u32, error, then CRC16 over the
first 17 bytes. A request echo confirms receipt, never successful completion.
"""
import os

from utils.ticks import ticks_add, ticks_diff, ticks_ms
from .now_playing import crc16

FRAME_SIZE = 19
PERIOD_MS = 1000
BLE_TOKENS = (b"BLE_PAUSE", b"BLE_ENABLE")


def encode_status(status, session, sequence, request_sequence=0):
    """Encode only valid observed states; never turn intent into Paused."""
    if not isinstance(status, dict):
        raise ValueError("BLE status must be a mapping")
    mode, error = status.get("mode"), status.get("error")
    if type(mode) is not int or not 0 <= mode <= 3 or type(error) is not int or not 0 <= error <= 7:
        raise ValueError("BLE status mode/error")
    flags = 0
    for field, bit in (("intent_enabled", 1), ("ready", 2), ("connected", 4), ("advertising", 8)):
        if type(status.get(field)) is not bool:
            raise ValueError("BLE status observations must be booleans")
        if status[field]:
            flags |= bit
    if (mode == 0 and (not flags & 1 or error != 0)
            or mode == 1 and (flags & 1 or error != 0)
            or mode == 2 and (flags != 2 or error != 0)
            or mode == 3 and error == 0):
        raise ValueError("Inconsistent BLE status")
    if type(request_sequence) is not int or not 0 <= request_sequence <= 0xFFFFFFFF:
        raise ValueError("BLE request sequence")
    frame = (b"BLS1" + (int(session) & 0xFFFFFFFF).to_bytes(4, "big")
             + (int(sequence) & 0xFFFF).to_bytes(2, "big") + bytes((mode, flags))
             + request_sequence.to_bytes(4, "big") + bytes((error,)))
    return frame + crc16(frame).to_bytes(2, "big")


class BleStatusPublisher:
    """Queue intent only; publish actual backend observations at most once/s."""

    def __init__(self, remote, ble, clock=None, session=None, log=print):
        self._remote = remote
        self._ble = ble
        self._clock = ticks_ms if clock is None else clock
        self._session = int.from_bytes(os.urandom(4), "big") if session is None else session
        self._sequence = 0
        self._request_sequence = 0
        self._next_send = None
        self._log = log
        self._observation_error = False

    def request(self, token, sequence):
        """Apply a validated control frame without performing BLE radio work."""
        if token not in BLE_TOKENS or type(sequence) is not int or not 0 <= sequence <= 0xFFFFFFFF:
            return False
        self._request_sequence = sequence
        if token == b"BLE_PAUSE":
            return self._ble.request_pause()
        return self._ble.request_enable()

    def tick(self):
        """Called only at the shared publisher's idle frame boundary."""
        if not self._remote.state_tx_enabled:
            return False
        now = self._clock()
        if self._next_send is not None and ticks_diff(now, self._next_send) < 0:
            return False
        if not self._remote.state_tx_ready():
            return False
        sequence = (self._sequence + 1) & 0xFFFF
        try:
            status = self._ble.snapshot_status()
            frame = encode_status(status, self._session, sequence, self._request_sequence)
            self._observation_error = False
        except Exception:
            if not self._observation_error:
                self._log("[REMOTE BLE] observation unavailable")
            self._observation_error = True
            frame = encode_status({"ready": False, "intent_enabled": False, "connected": False,
                                   "advertising": False, "mode": 3, "error": 6},
                                  self._session, sequence, self._request_sequence)
        self._next_send = ticks_add(now, PERIOD_MS)
        if not self._remote.send_ble_status_frame(frame):
            return False
        self._sequence = sequence
        return True

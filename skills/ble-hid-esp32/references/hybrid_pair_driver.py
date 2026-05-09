"""Hybrid pairing driver — passive for iOS, one-shot drive for Windows.

iOS auto-initiates BLE HID pairing ~1-2 seconds after connect, so any
peripheral-side c.pair() call inside that window is redundant and may
starve the main loop during the SMP handshake. Windows does NOT auto-
initiate — it waits for either a user click in the Add-device dialog
or a peripheral-driven Security Request.

The practical middle path: stay passive for the first 6 seconds,
then (if the connection has still not encrypted on its own) call
c.pair() exactly once. 6 seconds is long enough for a slow human
click in the Windows "Pair device? Allow" dialog to complete Just
Works pairing on its own (avoiding a collision where our Security
Request lands while Windows is already mid-SMP), and short enough
that truly-stuck centrals still get a nudge.

Do not drive multiple times. A fast (< 2s) drive collides with user-
mediated Windows pair flows and produces "Connection failed" in the
central UI.
"""
import time
from utils.common import dprint


# Inside BleHid.__init__:
#
#     self._need_pairing_check = False
#     self._last_pair_try_at = 0.0
#     self._pair_retry_s = 2.0            # how often we poll
#     self._pair_attempts = 0
#     self._pair_attempt_limit = 4        # stop polling after N tries
#     self._connected_at = 0.0
#     self._pair_auto_after_s = 6.0       # one-shot drive after this
#     self._pair_drive_tried = False
#     self._ever_paired_this_conn = False # for fast-disconnect hint
#     self._peer_logged = False


def _on_connect(self):
    print("[BLE] Connected")
    # NOTE: peer_address is logged from _ensure_paired, NOT here —
    # BLERadio.connections is frequently still empty at this moment
    # on NimBLE (peer record not yet linked into list).
    self._need_pairing_check = True
    self._pair_attempts = 0
    self._last_pair_try_at = 0.0
    self._connected_at = time.monotonic()
    self._pair_drive_tried = False
    self._ever_paired_this_conn = False
    self._peer_logged = False


def _ensure_paired(self):
    if not self._ble or not getattr(self._ble, "connected", False):
        return
    if self._pair_attempts >= self._pair_attempt_limit:
        self._need_pairing_check = False
        return
    now = time.monotonic()
    if (now - self._last_pair_try_at) < self._pair_retry_s:
        return
    self._last_pair_try_at = now

    try:
        conns = list(getattr(self._ble, "connections", []))
    except Exception:
        conns = []
    since_connect = now - self._connected_at

    # Log peer address on the first non-empty poll. Useful for
    # telling iPhone (random resolvable, changes each reconnect)
    # from Windows (stable public address) in the serial log.
    if (not self._peer_logged) and conns:
        for c in conns:
            try:
                addr = getattr(c, "peer_address", None)
                if addr is not None:
                    print("[BLE] peer:", addr)
            except Exception:
                pass
        self._peer_logged = True

    for c in conns:
        try:
            paired = getattr(c, "paired", None)
            if paired:
                self._need_pairing_check = False
                self._pair_attempts = 0
                self._ever_paired_this_conn = True
                print("[BLE] Paired/encrypted")
                continue
            # Still not paired. One-shot drive only after the grace
            # period, and only once per connection.
            if (not self._pair_drive_tried) and since_connect >= self._pair_auto_after_s:
                self._pair_drive_tried = True
                print("[BLE] Pairing... (driving from peripheral)")
                try:
                    c.pair()
                except Exception as e:
                    dprint("[BLE] pair() err:", e)
                paired = getattr(c, "paired", None)
                if paired:
                    self._need_pairing_check = False
                    self._pair_attempts = 0
                    self._ever_paired_this_conn = True
                    print("[BLE] Paired/encrypted")
                    continue
            self._pair_attempts += 1
            dprint("[BLE] pair poll %d/%d: paired=%r since_connect=%.1fs"
                   % (self._pair_attempts, self._pair_attempt_limit,
                      paired, since_connect))
        except Exception as e:
            self._pair_attempts += 1
            dprint("[BLE] pair poll err (attempt %d):" % self._pair_attempts, e)

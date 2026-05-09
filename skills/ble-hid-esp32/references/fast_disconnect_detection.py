"""Fast-disconnect-without-pair detection.

When a central's bond store disagrees with the peripheral's (usually:
central has a stored LTK, peripheral's NVS was wiped by EBIND, OR
the other way around), the central will connect, attempt to use the
stored bond, find the peripheral doesn't recognise it, and silently
drop the link within a second or two. The user sees nothing useful
on either side.

Detect this pattern and print a clear multi-line log hint naming
the likely cause and the fix. The one remaining recovery path is
"Forget Device on the central, then EBIND on the peripheral, then
reconnect from the central's OTHER DEVICES list."
"""
import time


# Inside BleHid.__init__:
#
#     self._connected_at = 0.0
#     self._ever_paired_this_conn = False
#     self._fast_disconnect_s = 2.0

# _on_connect resets _connected_at and _ever_paired_this_conn:
# see references/hybrid_pair_driver.py _on_connect.

# _ensure_paired sets _ever_paired_this_conn = True on the first
# poll where c.paired is True: see references/hybrid_pair_driver.py.


def _on_disconnect(self):
    try:
        uptime = time.monotonic() - self._connected_at
    except Exception:
        uptime = 0.0
    print("[BLE] Disconnected (uptime %.2fs, paired=%s)"
          % (uptime, self._ever_paired_this_conn))
    if (uptime < self._fast_disconnect_s) and (not self._ever_paired_this_conn):
        print("[BLE] Fast disconnect without pairing — likely stale bond on")
        print("      central side. Fix: Forget Device on the phone/PC, then")
        print("      press EBIND on the device, then reconnect from the")
        print("      central's OTHER DEVICES list.")
    self._need_pairing_check = False
    self._pair_attempts = 0
    self._pair_drive_tried = False
    self._ever_paired_this_conn = False
    # Kick advertising immediately so the central can re-find us.
    self._start_adv(force=True)

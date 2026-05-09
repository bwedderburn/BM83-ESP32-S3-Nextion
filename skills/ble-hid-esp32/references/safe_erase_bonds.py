"""NimBLE-safe erase_bonding() pattern.

NimBLE on ESP32-S3 will hard-crash (Thonny loses COM, board needs
power-cycle) if you call _bleio.adapter.erase_bonding() while the
radio is actively pumping — i.e. while a connection is live or an
advertisement is in flight. The synchronous c.disconnect() call from
the same callsite is even worse: it crashed the stack mid-AVRCP-
metadata-handshake in real hardware testing.

The robust shape is:

    request_erase_bonds()    # public, called from your UI handler
                             # (Nextion button, GPIO, etc.). Pure flag-
                             # setter; never blocks; rate-limited.

    _do_erase_bonds()        # main-loop worker, called from tick()
                             # only when self._ble.connected is False.
                             # Performs the actual six-step sequence.

A 30-second cooldown between successful erases is sufficient for the
"Forget Device → EBIND → re-pair" workflow and prevents accidental
back-to-back wipes from killing the stack.
"""
import time
import gc
from utils.common import dprint

# Short sleep between heavy NimBLE operations. 50 ms was the value
# from the recovered_source build that worked on shipped hardware.
_BLE_STABILIZE_S = 0.05


# Inside BleHid.__init__:
#
#     self._erase_pending = False
#     self._erase_cooldown_s = 30.0
#     # Init well in the past so the FIRST EBIND after boot isn't
#     # blocked by a false-positive cooldown check against t=0.
#     self._last_erase_at = -self._erase_cooldown_s - 1.0


def request_erase_bonds(self):
    """Request a bond-store wipe.

    Pure flag-setter. The actual erase runs from tick() once the
    link is down and the radio is quiet. Telling the user the
    request is queued (and will run after they disconnect from
    the central) keeps the UX self-explanatory.
    """
    if not self._ready:
        print("[BLE] erase_bonds: BLE not ready")
        return
    if self._erase_pending:
        print("[BLE] erase_bonds: already pending")
        return
    now = time.monotonic()
    if (now - self._last_erase_at) < self._erase_cooldown_s:
        remaining = self._erase_cooldown_s - (now - self._last_erase_at)
        print("[BLE] erase_bonds: on cooldown (%.1fs left)" % remaining)
        return
    self._erase_pending = True
    if getattr(self._ble, "connected", False):
        print("[BLE] erase_bonds: queued — disconnect central first, then it'll run")
    else:
        print("[BLE] erase_bonds: queued — will run on next tick")


def _do_erase_bonds(self):
    """Run from tick() only, with self._ble.connected == False."""
    self._erase_pending = False
    self._last_erase_at = time.monotonic()
    print("[BLE] erase_bonds: running")

    # 1. Stop advertising so the radio isn't actively pumping.
    try:
        self._stop_adv()
    except Exception as e:
        dprint("[BLE] erase_bonds stop_adv err:", e)

    # 2. Settle + GC so the NVS write has headroom.
    time.sleep(_BLE_STABILIZE_S)
    gc.collect()
    gc.collect()
    time.sleep(_BLE_STABILIZE_S)

    # 3. Try adafruit_ble's wrapper first; fall back to _bleio.adapter.
    ok = False
    try:
        if hasattr(self._ble, "erase_bonding"):
            self._ble.erase_bonding()
            ok = True
    except Exception as e:
        dprint("[BLE] erase_bonding (adafruit_ble) err:", e)
    if not ok:
        try:
            import _bleio
            if hasattr(_bleio.adapter, "erase_bonding"):
                _bleio.adapter.erase_bonding()
                ok = True
        except Exception as e:
            dprint("[BLE] erase_bonding (_bleio.adapter) err:", e)
    print("[BLE] erase_bonds:", "OK" if ok else "Unavailable on this build")

    # 4. (Optional but recommended) Bump name-cycle counter and rename.
    # See references/name_cycling.py for the helper.
    if ok:
        try:
            self._bump_counter_and_rename()
        except Exception as e:
            dprint("[BLE] name-cycle err:", e)

    # 5. Settle again before re-advertising so the next central
    # sees a clean radio.
    time.sleep(_BLE_STABILIZE_S)
    gc.collect()
    try:
        self._start_adv(force=True)
    except Exception as e:
        dprint("[BLE] erase_bonds restart adv err:", e)


# In your tick() loop:
#
#     if not connected:
#         if self._erase_pending:
#             self._do_erase_bonds()
#             return
#         # ... normal advertising-kick logic ...

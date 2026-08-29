# BM83 automated power-cycle validation harness.
#
# Usage: copy this file to the CIRCUITPY drive as `code.py` (CircuitPython
# runs code.py in preference to main.py), watch the serial console for the
# [TEST] lines and the final PASS/FAIL verdict, then DELETE code.py from
# CIRCUITPY to restore normal main.py operation. Safe to run with the unit
# live; it will power the BM83 off and back on, dropping any BT session.
#
# Drives the real chip through the same Bm83.power_toggle() path the
# BT_POWER touchscreen token uses, and validates the PR #133 contract:
#   phase 0  probe the live chip (expect ON via non-ACK evidence)
#   phase 1  toggle -> OFF sequence, explicit-off latched
#   phase 2  6s quiet window: no power_on resurrection, no probe spam
#   phase 3  toggle -> ON press, then confirmation must come from real
#            chip reporting (Command_ACKs are NOT boot evidence)
#
# History: first run of this harness (2026-08-29) caught the ACK hole --
# power_on flipped True +0.02s after the ON press, from the press ACK of a
# soft-off chip -- which became the EVT_CMD_ACK exclusion in bm83.py.
#
import time
import board
import busio
from bm83.bm83 import Bm83

print("=" * 60)
print("[TEST] BM83 power-cycle validation harness 2026-08-29")
print("=" * 60)

bm_uart = busio.UART(
    board.IO17, board.IO18, baudrate=115200, timeout=0.0,
    receiver_buffer_size=8192
)
bm = Bm83(bm_uart)


def run(seconds):
    """Poll + tick for a window, reporting power_on transitions."""
    t0 = time.monotonic()
    end = t0 + seconds
    last_p = bm.power_on
    while time.monotonic() < end:
        bm.poll()
        bm.tick_power()
        bm.tick_link_recovery()
        if bm.power_on != last_p:
            print("[TEST] power_on %s -> %s at +%.2fs" % (
                last_p, bm.power_on, time.monotonic() - t0))
            last_p = bm.power_on
        time.sleep(0.02)


def idle_forever():
    print("[TEST] idling - delete code.py to restore main.py")
    while True:
        bm.poll()
        bm.tick_power()
        bm.tick_link_recovery()
        time.sleep(0.05)


# Phase 0: chip was left ON and connected. Poke it once so its reply lets
# the normal inference path arm power_on=True, same as main.py would see.
print("[TEST] phase 0: probing live chip (expect ON)")
bm.send(bm.OP_READ_BD_ADDR)
run(4)
print("[TEST] phase 0 result: power_on=%s connected=%s" % (
    bm.power_on, bm.connected))
if not bm.power_on:
    print("[TEST] ABORT: chip did not respond while expected ON.")
    print("[TEST] VERDICT: OVERALL: ABORT")
    idle_forever()

# Phase 1: BT_POWER toggle while ON -> must send the OFF sequence.
print("[TEST] phase 1: power_toggle() -> expect OFF")
bm.power_toggle()
run(6)
off_ok = (bm.power_on is False) and bm._explicit_off
print("[TEST] phase 1 result: power_on=%s explicit_off=%s -> %s" % (
    bm.power_on, bm._explicit_off, "OK" if off_ok else "FAIL"))

# Phase 2: quiet window. Shutdown-time chatter must NOT resurrect
# power_on (the old bug), and the recovery probe must stay silent.
print("[TEST] phase 2: 6s quiet window (no resurrect, no probe spam)")
run(6)
quiet_ok = bm.power_on is False
print("[TEST] phase 2 result: power_on=%s -> %s" % (
    bm.power_on, "OK" if quiet_ok else "FAIL"))

# Phase 3: BT_POWER toggle while OFF -> must send ON and wait for the
# chip's own reporting to confirm (no faith-based power_on).
print("[TEST] phase 3: power_toggle() -> expect ON + chip confirmation")
bm.power_toggle()
run(12)
on_ok = (bm.power_on is True) and (bm._power_confirm_deadline == 0.0)
print("[TEST] phase 3 result: power_on=%s confirm_deadline=%s -> %s" % (
    bm.power_on, bm._power_confirm_deadline, "OK" if on_ok else "FAIL"))

print("=" * 60)
print("[TEST] VERDICT: OFF=%s QUIET=%s ON_CONFIRMED=%s" % (
    off_ok, quiet_ok, on_ok))
print("[TEST] OVERALL: %s" % (
    "PASS" if (off_ok and quiet_ok and on_ok) else "FAIL"))
print("=" * 60)

idle_forever()

# BM83 power-cycle STRESS harness -- reproduce intermittent power-on failures.
#
# Usage: copy to CIRCUITPY as `code.py` (runs instead of main.py), watch the
# serial [STRESS] lines, delete code.py to restore main.py.
#
# Runs 8 consecutive OFF -> gap -> ON cycles with varied off-gaps (short
# gaps leave supply caps charged; long gaps match a user powering on after
# idle). Per cycle it measures press-to-confirmation latency and flags
# timeouts. The boot banner prints the ESP32 reset reason: if the harness
# restarts mid-run (a second banner appears) with reset_reason BROWNOUT,
# the power-button "struggle" is a supply sag when the BM83 starts -- a
# hardware fix (bulk capacitance / supply), not firmware.
#
# Built for the 2026-08-29 field report "still struggles with the power
# button" after the toggle-inversion fixes (PR #133) all passed on
# hardware; the serial port re-enumerated at the exact moment of the
# user's failed press, which firmware cannot do.

import time
import board
import busio
import microcontroller
from bm83.bm83 import Bm83

OFF_GAPS = (2, 5, 10, 3, 15, 2, 8, 5)   # seconds chip stays off per cycle
ON_TIMEOUT = 8.0                         # press-to-confirmation limit

print("=" * 60)
print("[STRESS] BM83 power-cycle stress harness 2026-08-29")
print("[STRESS] reset_reason:", microcontroller.cpu.reset_reason)
print("[STRESS] %d cycles, off-gaps %s" % (len(OFF_GAPS), OFF_GAPS))
print("=" * 60)

bm_uart = busio.UART(
    board.IO17, board.IO18, baudrate=115200, timeout=0.0,
    receiver_buffer_size=8192
)
bm = Bm83(bm_uart)


def spin(seconds, until=None):
    """Production-faithful loop; returns elapsed when `until()` is True."""
    t0 = time.monotonic()
    end = t0 + seconds
    while time.monotonic() < end:
        for op, params in bm.poll():
            bm.ack_event(op)
            if op == bm.EVT_BTM_STATUS and params:
                bm.note_btm_state(params[0])
        bm.tick_power()
        bm.tick_link_recovery()
        if until is not None and until():
            return time.monotonic() - t0
        time.sleep(0.02)
    return None if until is not None else (time.monotonic() - t0)


# Arm initial state from the live chip (expected ON).
print("[STRESS] phase 0: sensing live chip")
bm.send(bm.OP_READ_BD_ADDR)
spin(4)
if not bm.power_on:
    print("[STRESS] ABORT: chip not responding while expected ON")
    while True:
        time.sleep(1)

results = []
for i, gap in enumerate(OFF_GAPS):
    n = i + 1
    print("[STRESS] cycle %d/%d: OFF, gap %ds" % (n, len(OFF_GAPS), gap))
    bm.power_toggle()                    # ON -> sends OFF
    off_t = spin(6, until=lambda: bm.power_on is False)
    if off_t is None:
        print("[STRESS] cycle %d: OFF FAILED (power_on never cleared)" % n)
        results.append((n, gap, "OFF-FAIL", None))
        continue
    resurrected = spin(gap, until=lambda: bm.power_on is True)
    if resurrected is not None:
        print("[STRESS] cycle %d: power_on RESURRECTED %.2fs into the "
              "off-gap (issue #135 class)" % (n, resurrected))
        results.append((n, gap, "RESURRECT", resurrected))
        # Re-settle to OFF before continuing.
        bm.power_toggle()
        spin(6, until=lambda: bm.power_on is False)
        continue
    print("[STRESS] cycle %d: ON press" % n)
    bm.power_toggle()                    # OFF -> sends ON
    on_t = spin(ON_TIMEOUT, until=lambda: bm.power_on is True)
    if on_t is None:
        print("[STRESS] cycle %d: ON TIMEOUT after %.1fs -- "
              "chip did not confirm" % (n, ON_TIMEOUT))
        results.append((n, gap, "ON-TIMEOUT", None))
        # Try once more so the run can continue (mirrors a user re-press).
        bm.power_toggle()
        retry_t = spin(ON_TIMEOUT, until=lambda: bm.power_on is True)
        if retry_t is None:
            print("[STRESS] cycle %d: retry ALSO timed out - stopping" % n)
            break
        print("[STRESS] cycle %d: retry confirmed in %.2fs" % (n, retry_t))
    else:
        print("[STRESS] cycle %d: ON confirmed in %.2fs" % (n, on_t))
        results.append((n, gap, "OK", on_t))
    spin(2)                              # settle before next cycle

print("=" * 60)
ok = [r for r in results if r[2] == "OK"]
print("[STRESS] SUMMARY: %d/%d cycles clean" % (len(ok), len(results)))
for n, gap, verdict, t in results:
    print("[STRESS]   cycle %d gap %2ds -> %s%s" % (
        n, gap, verdict, "" if t is None else " (%.2fs)" % t))
if ok:
    ts = sorted(r[3] for r in ok)
    print("[STRESS] confirm latency min/med/max: %.2f / %.2f / %.2f s" % (
        ts[0], ts[len(ts) // 2], ts[-1]))
print("[STRESS] OVERALL: %s" % (
    "PASS" if len(ok) == len(OFF_GAPS) else "SEE FAILURES ABOVE"))
print("[STRESS] done - delete code.py to restore main.py")
print("=" * 60)

while True:
    for op, params in bm.poll():
        bm.ack_event(op)
        if op == bm.EVT_BTM_STATUS and params:
            bm.note_btm_state(params[0])
    bm.tick_power()
    bm.tick_link_recovery()
    time.sleep(0.05)

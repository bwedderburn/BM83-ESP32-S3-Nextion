# BM83 automated power-cycle validation harness.
#
# Usage: copy this file to the CIRCUITPY drive as `code.py` (CircuitPython
# runs code.py in preference to main.py), watch the serial console for the
# [TEST] lines and the final PASS/FAIL verdict, then DELETE code.py from
# CIRCUITPY to restore normal main.py operation. Safe to run with the unit
# live; it will power the BM83 off and back on, dropping any BT session.
#
# Drives the real chip through the same Bm83.power_toggle() path the
# BT_POWER touchscreen token uses, mirroring main.py's production loop
# (events are acknowledged and BTM status is dispatched through
# note_btm_state), and validates the PR #133 contract:
#   phase 0  probe the live chip (expect ON via non-ACK evidence)
#   phase 1  toggle -> OFF sequence, explicit-off latched
#   phase 2  6s quiet window: no power_on resurrection, and no TX besides
#            event acks (recovery probes must stay silent) -- asserted on
#            a per-frame TX op log, not just claimed
#   phase 3  toggle -> ON press; confirmation must be backed by at least
#            one non-ACK event from the chip (Command_ACKs are not boot
#            evidence), and the ops that served as evidence are printed
#
# History: the first run of this harness (2026-08-29) caught the ACK hole
# -- power_on flipped True +0.02s after the ON press, from the press ACK
# of a soft-off chip -- which became the EVT_CMD_ACK exclusion in
# bm83.py. This revision hardened the harness itself per Codex/Copilot
# review on PR #134 (evidence-quality check, TX accounting, production-
# faithful event dispatch, guarded access to Bm83 internals).

import time
import board
import busio
from bm83.bm83 import Bm83

print("=" * 60)
print("[TEST] BM83 power-cycle validation harness 2026-08-29")
print("=" * 60)


class CountingUART:
    """Delegating wrapper that logs the op byte of every TX frame.

    Bm83.send() always writes complete AudioUART frames
    (0xAA LEN_HI LEN_LO OP ... CHKSUM), so the op sits at index 3.
    """

    def __init__(self, real):
        self._real = real
        self.tx_ops = []

    @property
    def in_waiting(self):
        return self._real.in_waiting

    def read(self, n):
        return self._real.read(n)

    def write(self, data):
        try:
            self.tx_ops.append(data[3])
        except (IndexError, TypeError):
            self.tx_ops.append(None)
        return self._real.write(data)


uart = CountingUART(busio.UART(
    board.IO17, board.IO18, baudrate=115200, timeout=0.0,
    receiver_buffer_size=8192
))
bm = Bm83(uart)

# Private diagnostics, guarded so an internals rename degrades the verdict
# to an explicit message instead of an AttributeError mid-run.
_PRIV_SENTINEL = object()


def _priv(name):
    return getattr(bm, name, _PRIV_SENTINEL)


def _priv_ok():
    return (_priv("_explicit_off") is not _PRIV_SENTINEL
            and _priv("_power_confirm_deadline") is not _PRIV_SENTINEL)


if not _priv_ok():
    print("[TEST] NOTE: Bm83 internals renamed; private-field checks")
    print("[TEST] unavailable -- verdict falls back to public state only.")


def run(seconds):
    """Mirror main.py's loop for a window; return non-ACK ops received."""
    t0 = time.monotonic()
    end = t0 + seconds
    last_p = bm.power_on
    evidence = []
    while time.monotonic() < end:
        for op, params in bm.poll():
            bm.ack_event(op)
            if op != bm.EVT_CMD_ACK:
                evidence.append(op)
            if op == bm.EVT_BTM_STATUS and params:
                bm.note_btm_state(params[0])
        bm.tick_power()
        bm.tick_link_recovery()
        if bm.power_on != last_p:
            print("[TEST] power_on %s -> %s at +%.2fs" % (
                last_p, bm.power_on, time.monotonic() - t0))
            last_p = bm.power_on
        time.sleep(0.02)
    return evidence


def idle_forever():
    print("[TEST] idling - delete code.py to restore main.py")
    while True:
        for op, params in bm.poll():
            bm.ack_event(op)
            if op == bm.EVT_BTM_STATUS and params:
                bm.note_btm_state(params[0])
        bm.tick_power()
        bm.tick_link_recovery()
        time.sleep(0.05)


# Phase 0: chip was left ON. Poke it once so a real (non-ACK) reply lets
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
_eoff = _priv("_explicit_off")
off_ok = (bm.power_on is False) and (_eoff is True or not _priv_ok())
print("[TEST] phase 1 result: power_on=%s explicit_off=%s -> %s" % (
    bm.power_on,
    "n/a" if _eoff is _PRIV_SENTINEL else _eoff,
    "OK" if off_ok else "FAIL"))

# Phase 2: quiet window. Shutdown-time chatter must NOT resurrect
# power_on, and the ONLY permissible TX is acking inbound events --
# recovery probes and any other command traffic must stay silent.
print("[TEST] phase 2: 6s quiet window (no resurrect, no probe spam)")
_tx_base = len(uart.tx_ops)
run(6)
_quiet_tx = [op for op in uart.tx_ops[_tx_base:] if op != bm.OP_EVENT_ACK]
quiet_ok = (bm.power_on is False) and (not _quiet_tx)
print("[TEST] phase 2 result: power_on=%s non-ack TX=%s -> %s" % (
    bm.power_on,
    "none" if not _quiet_tx else " ".join("%02X" % op for op in _quiet_tx),
    "OK" if quiet_ok else "FAIL"))

# Phase 3: BT_POWER toggle while OFF -> must send ON, and the claimed
# confirmation must be backed by at least one non-ACK event so a
# regression that re-admits ACKs as boot evidence cannot slip a PASS.
print("[TEST] phase 3: power_toggle() -> expect ON + chip confirmation")
bm.power_toggle()
_evidence = run(12)
_deadline = _priv("_power_confirm_deadline")
on_ok = (
    (bm.power_on is True)
    and (_deadline == 0.0 or not _priv_ok())
    and len(_evidence) > 0
)
print("[TEST] phase 3 result: power_on=%s confirm_deadline=%s "
      "evidence_ops=%s -> %s" % (
          bm.power_on,
          "n/a" if _deadline is _PRIV_SENTINEL else _deadline,
          " ".join("%02X" % op for op in _evidence[:8]) or "NONE",
          "OK" if on_ok else "FAIL"))

print("=" * 60)
print("[TEST] VERDICT: OFF=%s QUIET=%s ON_CONFIRMED=%s" % (
    off_ok, quiet_ok, on_ok))
print("[TEST] OVERALL: %s" % (
    "PASS" if (off_ok and quiet_ok and on_ok) else "FAIL"))
print("=" * 60)

idle_forever()

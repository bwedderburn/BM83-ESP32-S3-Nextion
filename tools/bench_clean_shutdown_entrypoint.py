"""Temporary code.py: prepare one user OFF with Pause and A2DP disconnect.

Back up the existing device entrypoints first. This wrapper runs the unchanged
production main.py/lib, disables autoreload, and adds DEBUG device ticks. Restore
the prior entrypoints and reload after the capture. DEBUG changes timing and does
not prove production performance or audible recovery.

Only an accepted OFF from confirmed A2DP playback/link state can begin preparation.
A fresh single-database/AVRCP snapshot precedes explicit Pause, a three-second
settle, one A2DP-only disconnect, and a one-second settle. The original OFF driver
then runs unchanged. Any ambiguity/error/timeout falls back to that driver. There
is one preparation per interpreter, no PLAY/link-back/pairing/gain/automatic ON.
"""
import time

import supervisor

from utils import common
from utils.ticks import ticks_add, ticks_less, ticks_ms

_TRIAL_USED = False
_PREP_PHASES = ("snapshot", "pause_ack", "pause_settle", "disconnect", "disconnect_settle")
_TOTAL_PREP_MS = 10000
_COMMAND_TIMEOUT_MS = 2000
_PAUSE_SETTLE_MS = 3000
_DISCONNECT_SETTLE_MS = 1000


def _bench_dprint(*args):
    if common.DEBUG:
        print("[BENCH ticks_ms=%d]" % supervisor.ticks_ms(), *args)


class CleanShutdownTrial:
    """Bounded pre-OFF preparation; the production driver owns power state."""

    def __init__(self, bm):
        self.bm = bm
        self.phase = "idle"
        self.outcome = None
        self.prepared = False
        self.deadline = None
        self.total_deadline = None
        self.failure = None
        self.chip_off = False
        self.snapshot_ack = False
        self.snapshot_data = None
        self.command_ack = False
        self.saw_down = False
        self.sending = False
        self.log("idle: one clean preparation on a qualifying user OFF; boot is not armed")

    @property
    def active(self):
        return self.phase in _PREP_PHASES

    def log(self, *args):
        print("[CLEAN_OFF ticks_ms=%d]" % ticks_ms(), *args)

    def transition(self, phase, timeout_ms):
        self.phase = phase
        self.deadline = ticks_add(ticks_ms(), timeout_ms)
        self.log("phase:", phase)

    def eligible(self):
        bm = self.bm
        return (bm.power_on and bm.connected and not bm._explicit_off
                and bm._power_state is None and not bm._power_confirm_deadline
                and not bm.avrcp_suspended and bm.audio_source == bm.AUDIO_SRC_A2DP)

    def request_off(self):
        """Handle the user's OFF, immediately bypassing unsafe preparation."""
        global _TRIAL_USED
        if self.active:
            self.start_normal_off("repeated OFF: bypass preparation")
            return
        if _TRIAL_USED or not self.eligible():
            self.log("bypass: normal OFF (used trial or unconfirmed A2DP/AVRCP state)")
            self.bm._start_plain_off()
            return
        _TRIAL_USED = True
        self.total_deadline = ticks_add(ticks_ms(), _TOTAL_PREP_MS)
        self.transition("snapshot", _COMMAND_TIMEOUT_MS)
        self.send_command(0x0D, b"\x00")

    def send_command(self, op, params):
        # Only this controller may issue non-ACK traffic during preparation.
        self.sending = True
        try:
            self.bm.send(op, params)
        finally:
            self.sending = False

    def end(self, outcome):
        # Clear the send gate BEFORE invoking any original power method.
        self.phase = "done"
        self.outcome = outcome
        self.deadline = None
        self.total_deadline = None
        self.log("outcome:", outcome, "(preparation only; audibility not measured)")

    def start_normal_off(self, reason):
        self.end(reason)
        self.bm._start_plain_off()

    def cancel_for_on(self):
        if self.active:
            self.end("cancelled by explicit user ON; no automatic playback restart")

    def observe(self, op, params):
        """Observe frames without consuming them or transmitting during dispatch."""
        if not self.active:
            return
        if op == 0x01 and params:
            state = params[0]
            if state == 0x00:
                self.chip_off = True
            elif state == 0x81:
                self.failure = "AUX source observed"
            elif state in (0x06, 0x0B, 0x15):
                # A2DP/profile/ACL establishment can invalidate the single-peer
                # snapshot. Disconnect 0x18/0x04 affects every A2DP link.
                self.failure = "fresh link establishment during preparation"
            elif state == 0x08 and self.phase == "disconnect":
                self.saw_down = True
        elif op == 0x1E and self.phase == "snapshot":
            self.log("Read_Link_Status raw:", " ".join("%02X" % b for b in params))
            if len(params) != 7:
                self.failure = "invalid snapshot length"
            else:
                self.snapshot_data = bytes(params)
        elif op == 0x00 and params:
            expected = {"snapshot": 0x0D, "pause_ack": 0x04, "disconnect": 0x18}.get(self.phase)
            if params[0] != expected:
                return
            if len(params) != 2:
                # Command_ACK is exactly [command, status]; poll() checks only
                # framing/checksum. Latch so a valid ACK in the batch cannot win.
                self.log("command ACK: 0x%02X invalid raw:" % params[0], " ".join("%02X" % b for b in params))
                self.failure = "invalid command 0x%02X ACK length" % params[0]
                return
            self.log("command ACK: 0x%02X status=0x%02X" % (params[0], params[1]))
            if params[1] != 0:
                self.failure = "command 0x%02X rejected" % params[0]
            elif self.phase == "snapshot":
                self.snapshot_ack = True
            else:
                self.command_ack = True

    def tick(self):
        if not self.active:
            return
        bm = self.bm
        now = ticks_ms()
        if self.chip_off or (bm._explicit_off and not bm.power_on):
            self.end("chip reported OFF: no additional OFF command")
            return
        if bm._power_state is not None:
            self.end("existing power transition: preparation ended")
            return
        if self.failure:
            self.start_normal_off("fallback: " + self.failure)
            return
        if bm.audio_source == bm.AUDIO_SRC_AUX:
            self.start_normal_off("fallback: AUX source active")
            return
        if not bm.power_on or bm._explicit_off or bm._power_confirm_deadline:
            self.start_normal_off("fallback: power state changed")
            return
        if not ticks_less(now, self.total_deadline):
            self.start_normal_off("fallback: total preparation timeout")
            return
        if self.phase in ("snapshot", "pause_ack", "pause_settle") and (
                not bm.connected or bm.avrcp_suspended):
            self.start_normal_off("fallback: link/AVRCP lost before disconnect")
            return
        if self.phase in ("snapshot", "pause_ack", "disconnect") and not ticks_less(now, self.deadline):
            self.start_normal_off("fallback: " + self.phase + " timeout")
            return
        if self.phase == "snapshot":
            self.tick_snapshot()
        elif self.phase == "pause_ack" and self.command_ack:
            self.transition("pause_settle", _PAUSE_SETTLE_MS)
        elif self.phase == "pause_settle" and not ticks_less(now, self.deadline):
            self.command_ack = False
            self.saw_down = False
            self.transition("disconnect", _COMMAND_TIMEOUT_MS)
            self.send_command(0x18, b"\x04")
        elif self.phase == "disconnect" and self.command_ack and self.saw_down:
            self.transition("disconnect_settle", _DISCONNECT_SETTLE_MS)
        elif self.phase == "disconnect_settle" and not ticks_less(now, self.deadline):
            self.prepared = True
            self.start_normal_off("prepared: normal OFF sequence requested")

    def tick_snapshot(self):
        if not self.snapshot_ack or self.snapshot_data is None:
            return
        data = self.snapshot_data
        flags = (data[1], data[2])
        databases = int(bool(flags[0] & 0x03)) + int(bool(flags[1] & 0x03))
        if databases != 1 or data[0] not in (0x04, 0x06):
            self.start_normal_off("fallback: ambiguous/absent A2DP database")
            return
        active_flags = flags[0] if flags[0] & 0x03 else flags[1]
        if (active_flags & 0x05) != 0x05:
            self.start_normal_off("fallback: A2DP signaling/AVRCP not confirmed")
            return
        self.command_ack = False
        self.transition("pause_ack", _COMMAND_TIMEOUT_MS)
        # Music_Control's first byte is reserved, not a database index.
        self.send_command(0x04, b"\x00\x06")


def make_bench_type(base):
    """Wrap production BM83 without changing its power press/release logic."""
    class BenchBm83(base):
        __slots__ = ("_clean_shutdown_trial",)

        def __init__(self, uart=None):
            base.__init__(self, uart)
            self._clean_shutdown_trial = CleanShutdownTrial(self)

        def _start_plain_off(self):
            base.power_off_cmd(self)

        def power_off_cmd(self):
            self._clean_shutdown_trial.request_off()

        def power_on_cmd(self):
            preparing = self._clean_shutdown_trial.active
            self._clean_shutdown_trial.cancel_for_on()
            if preparing and self.power_on and self._power_state is None:
                # Cancellation leaves the already-powered chip ON; no second
                # power sequence or unrequested playback restart is needed.
                return
            base.power_on_cmd(self)

        def tick_power(self):
            base.tick_power(self)
            self._clean_shutdown_trial.tick()

        def poll(self, max_read=768, max_events=8):
            events = base.poll(self, max_read=max_read, max_events=max_events)
            for op, params in events:
                self._clean_shutdown_trial.observe(op, params)
            return events

        def send(self, op, params=b""):
            trial = getattr(self, "_clean_shutdown_trial", None)
            if trial is not None and trial.active:
                command = ((op == 0x0D and params == b"\x00")
                           or (op == 0x04 and params == b"\x00\x06")
                           or (op == 0x18 and params == b"\x04"))
                allowed = op == 0x14 or (trial.sending and command)
                if not allowed:
                    return
            base.send(self, op, params)

        def tick_avrcp(self):
            if not self._clean_shutdown_trial.active:
                return base.tick_avrcp(self)

        def tick_avrcp_attrs(self, now=None):
            if not self._clean_shutdown_trial.active:
                return base.tick_avrcp_attrs(self, now)

        def tick_notif_regs(self, now=None):
            if not self._clean_shutdown_trial.active:
                return base.tick_notif_regs(self, now)

        def tick_stream_kick(self, now=None):
            if not self._clean_shutdown_trial.active:
                return base.tick_stream_kick(self, now)

        def tick_avrcp_resume(self, now=None):
            if not self._clean_shutdown_trial.active:
                return base.tick_avrcp_resume(self, now)

        def tick_link_recovery(self, now=None):
            if not self._clean_shutdown_trial.active:
                return base.tick_link_recovery(self, now)

        def tick_boot_init(self, now=None):
            if not self._clean_shutdown_trial.active:
                return base.tick_boot_init(self, now)

    return BenchBm83


def run():
    supervisor.runtime.autoreload = False
    common.dprint = _bench_dprint
    common.DEBUG = True
    import bm83 as package
    from bm83 import bm83 as driver
    bench_type = make_bench_type(driver.Bm83)
    driver.Bm83 = bench_type
    package.Bm83 = bench_type
    print("[BENCH] One clean preparation on USER OFF; no automatic ON/PLAY/linkback")
    print("[BENCH] OFF may take up to 10s preparation plus the unchanged 1.5s hold")
    print("[BENCH] DEBUG changes timing; restore entrypoint and reload after capture")
    import main as firmware_main
    try:
        firmware_main.main()
    except Exception as e:
        try:
            import traceback
            print("[FATAL]", e)
            traceback.print_exception(e)
        except Exception:
            print("[FATAL]", e)
        while True:
            time.sleep(1)


if __name__ == "__main__":
    run()

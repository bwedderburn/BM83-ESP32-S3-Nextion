"""Temporary code.py: one A2DP reconnect experiment after a user OFF/ON cycle.

Back up existing code.py/main.py before deployment; leave production main.py and
lib/ unchanged. Reload to start, restore the prior entrypoint and reload afterward.
DEBUG printing alters allocations/timing and cannot establish production performance
or audible recovery. Device ticks wrap at 2**29 ms; use utils.ticks.ticks_diff.

The trial never drives pairing, bond erase, AUX gain, PLAY, or a power cycle. The
user must request OFF then ON normally. UART 0x18/04 disconnects ALL A2DP links,
so a fresh 0x1E snapshot must show exactly one A2DP database before that command.
UART 0x17/02 reconnects the last A2DP device; neither command takes a DB byte.
"""
import time

import supervisor

from utils import common
from utils.ticks import ticks_add, ticks_diff, ticks_less, ticks_ms

_TRIAL_USED = False
_EXCLUSIVE_PHASES = ("snapshot", "disconnect", "quiet", "relink")


def _bench_dprint(*args):
    if common.DEBUG:
        print("[BENCH ticks_ms=%d]" % supervisor.ticks_ms(), *args)


class ReconnectTrial:
    """Non-blocking one-shot controller; all power/session state belongs to BM83."""

    def __init__(self, bm):
        self.bm = bm
        self.phase = "idle"
        self.outcome = None
        self.off_requested = False
        self.deadline = None
        self.stable_since = None
        self.initial_press = False
        self.snapshot_ack = False
        self.snapshot_data = None
        self.command_ack = False
        self.saw_down = False
        self.a2dp_returned = False
        self.healthy_sent = False
        self.healthy_started = None
        self.healthy_ack = False
        self.healthy_reply = False
        self.log("idle: waiting for an accepted user OFF then ON; boot is not armed")

    @property
    def exclusive(self):
        return self.phase in _EXCLUSIVE_PHASES

    @property
    def active(self):
        return self.phase not in ("idle", "done", "aborted")

    def log(self, *args):
        print("[A2DP_TRIAL ticks_ms=%d]" % ticks_ms(), *args)

    def transition(self, phase, timeout_ms):
        self.phase = phase
        self.deadline = ticks_add(ticks_ms(), timeout_ms)
        self.log("phase:", phase)

    def finish(self, outcome, aborted=False):
        self.phase = "aborted" if aborted else "done"
        self.outcome = outcome
        self.deadline = None
        self.log("outcome:", outcome, "(protocol observation; audibility not measured)")

    def cancel_for_off(self):
        # Called BEFORE the base OFF method, so its press/release is not blocked.
        if self.active:
            self.finish("cancelled by explicit OFF", aborted=True)

    def arm_after_on(self):
        global _TRIAL_USED
        if _TRIAL_USED or not self.off_requested:
            return
        _TRIAL_USED = True
        self.initial_press = True
        self.stable_since = None
        self.transition("link", 30000)

    def eligible(self):
        bm = self.bm
        return (bm.power_on and bm.connected and not bm._explicit_off
                and bm._power_state is None and not bm._power_confirm_deadline
                and bm.audio_source != bm.AUDIO_SRC_AUX)

    def observe(self, op, params):
        """Observe returned events without consuming or changing their payloads."""
        if op == 0x1E:
            self.log("Read_Link_Status raw:", " ".join("%02X" % b for b in params))
            if len(params) == 7:
                self.log("fields dev/db0/db1/play0/play1/stream0/stream1:", tuple(params))
            if self.phase == "snapshot":
                if len(params) != 7:
                    self.finish("invalid pre-disconnect snapshot length", aborted=True)
                else:
                    self.snapshot_data = bytes(params)
            elif self.healthy_started is not None:
                self.healthy_reply = True
        elif op == 0x00 and params:
            self._observe_ack(params)
        elif op == 0x01 and params:
            self._observe_state(params[0])
        elif op == 0x23 and len(params) >= 2 and self.phase == "relink":
            if params[0] == 0x02 and params[1] != 0x00:
                self.finish("A2DP linkback reported failure", aborted=True)

    def _observe_ack(self, params):
        # Command_ACK is exactly [command, status]; poll() checks only framing
        # and checksum, so any other length is malformed and never authorizes.
        command = params[0]
        status = params[1] if len(params) == 2 else None
        expected = {"snapshot": 0x0D, "disconnect": 0x18, "relink": 0x17}.get(self.phase)
        if command == expected:
            if status is None:
                self.log("command ACK: 0x%02X invalid raw:" % command, " ".join("%02X" % b for b in params))
                self.finish("invalid command ACK length", aborted=True)
                return
            self.log("command ACK: 0x%02X status=0x%02X" % (command, status))
            if status != 0:
                self.finish("command rejected", aborted=True)
            elif self.phase == "snapshot":
                self.snapshot_ack = True
            else:
                self.command_ack = True
        elif command == 0x0D and self.healthy_started is not None:
            self.healthy_ack = status == 0
            if status is None:
                self.log("boot snapshot ACK has invalid length")
                self.healthy_started = None
            elif status != 0:
                self.log("boot snapshot command rejected:", status)
                self.healthy_started = None

    def _observe_state(self, state):
        if self.active and state in (0x00, 0x81):
            self.finish("OFF/AUX source observed", aborted=True)
            return
        if not self.exclusive:
            return
        if self.phase == "snapshot" and state in (0x06, 0x0B, 0x15):
            # A2DP/profile/ACL establishment can invalidate the single-database
            # snapshot, even in its own poll batch. 0x18/0x04 hits every A2DP link.
            self.finish("fresh link establishment during snapshot", aborted=True)
            return
        if state in (0x08, 0x11):
            self.saw_down = True
            self.a2dp_returned = False
        elif state in (0x06, 0x82) and self.saw_down:
            # Fresh evidence after an actual drop; cached audio_source is ignored.
            self.a2dp_returned = True
            self.log("fresh A2DP return: 0x%02X" % state)

    def tick(self):
        now = ticks_ms()
        self._tick_healthy(now)
        if not self.active:
            return
        bm = self.bm
        if bm._power_state is None:
            self.initial_press = False
        allowed_press = (self.phase == "link" and self.initial_press
                         and bm._power_state in ("on_press", "on_init"))
        if bm._explicit_off or (bm._power_state is not None and not allowed_press):
            self.finish("power transition/explicit OFF", aborted=True)
            return
        if bm.audio_source == bm.AUDIO_SRC_AUX:
            self.finish("AUX source active", aborted=True)
            return
        if self.phase != "quiet" and not ticks_less(now, self.deadline):
            self.finish(self.phase + " timeout", aborted=True)
            return
        if self.phase == "link":
            self._tick_link(now)
        elif self.phase == "snapshot":
            self._tick_snapshot()
        elif self.phase == "disconnect":
            if self.command_ack and self.saw_down:
                self.transition("quiet", 10000)
        elif self.phase == "quiet":
            self._tick_quiet(now)
        elif self.phase == "relink" and self.command_ack and self.a2dp_returned:
            self.finish("linkback ACK + fresh A2DP state observed")
            self.bm.send(0x0D, b"\x00")

    def _tick_healthy(self, now):
        if self.healthy_started is not None:
            if self.healthy_ack and self.healthy_reply:
                self.healthy_started = None
            elif ticks_diff(now, self.healthy_started) >= 5000:
                self.log("boot snapshot timed out")
                self.healthy_started = None
        if self.phase != "idle" or self.healthy_sent or not self.eligible():
            if self.phase == "idle" and not self.eligible():
                self.stable_since = None
            return
        if self.stable_since is None:
            self.stable_since = now
        elif ticks_diff(now, self.stable_since) >= 2000:
            self.healthy_sent = True
            self.healthy_started = now
            self.log("boot settled; read-only link snapshot (not a healthy-audio claim)")
            self.bm.send(0x0D, b"\x00")

    def _tick_link(self, now):
        if not self.eligible():
            self.stable_since = None
            return
        if self.stable_since is None:
            self.stable_since = now
        if ticks_diff(now, self.stable_since) < 2000 or self.healthy_started is not None:
            return
        self.snapshot_ack = False
        self.snapshot_data = None
        self.transition("snapshot", 5000)
        self.bm.send(0x0D, b"\x00")

    def _tick_snapshot(self):
        if not self.snapshot_ack or self.snapshot_data is None:
            return
        data = self.snapshot_data
        databases = int(bool(data[1] & 0x03)) + int(bool(data[2] & 0x03))
        if databases != 1:
            self.finish("snapshot requires exactly one A2DP database; found %d" % databases, aborted=True)
            return
        self.command_ack = False
        self.saw_down = False
        self.a2dp_returned = False
        self.transition("disconnect", 8000)
        self.bm.send(0x18, b"\x04")

    def _tick_quiet(self, now):
        if ticks_less(now, self.deadline):
            return
        if self.a2dp_returned and self.bm.connected:
            self.finish("auto-reconnected during quiet gap; no redundant linkback")
            self.bm.send(0x0D, b"\x00")
            return
        self.command_ack = False
        self.a2dp_returned = False
        self.transition("relink", 30000)
        self.bm.send(0x17, b"\x02")


def make_bench_type(base):
    """Wrap the current production driver, retaining its power implementation."""
    class BenchBm83(base):
        __slots__ = ("_bench_trial",)

        def __init__(self, uart=None):
            base.__init__(self, uart)
            self._bench_trial = ReconnectTrial(self)

        def power_off_cmd(self):
            self._bench_trial.cancel_for_off()
            before = self._power_state
            base.power_off_cmd(self)
            if before is None and self._power_state == "off_press":
                self._bench_trial.off_requested = True

        def power_on_cmd(self):
            before = self._power_state
            base.power_on_cmd(self)
            if before is None and self._power_state == "on_press":
                self._bench_trial.arm_after_on()

        def tick_power(self):
            base.tick_power(self)
            self._bench_trial.tick()

        def poll(self, max_read=768, max_events=8):
            events = base.poll(self, max_read=max_read, max_events=max_events)
            for op, params in events:
                self._bench_trial.observe(op, params)
            return events

        def send(self, op, params=b""):
            trial = getattr(self, "_bench_trial", None)
            if trial is not None and trial.exclusive and op not in (0x14, 0x0D, 0x18, 0x17):
                return
            base.send(self, op, params)

        def tick_avrcp(self):
            if not self._bench_trial.exclusive:
                return base.tick_avrcp(self)

        def tick_avrcp_attrs(self, now=None):
            if not self._bench_trial.exclusive:
                return base.tick_avrcp_attrs(self, now)

        def tick_notif_regs(self, now=None):
            if not self._bench_trial.exclusive:
                return base.tick_notif_regs(self, now)

        def tick_stream_kick(self, now=None):
            if not self._bench_trial.exclusive:
                return base.tick_stream_kick(self, now)

        def tick_avrcp_resume(self, now=None):
            if not self._bench_trial.exclusive:
                return base.tick_avrcp_resume(self, now)

        def tick_link_recovery(self, now=None):
            if not self._bench_trial.exclusive:
                return base.tick_link_recovery(self, now)

        def tick_boot_init(self, now=None):
            if not self._bench_trial.exclusive:
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
    print("[BENCH] One A2DP trial after USER OFF/ON; no audible PASS is inferred")
    print("[BENCH] DEBUG alters timing; restore entrypoint and reload after capture")
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

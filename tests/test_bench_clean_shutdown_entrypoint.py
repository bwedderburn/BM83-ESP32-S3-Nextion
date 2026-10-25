"""Host integration checks for the temporary clean-shutdown preparation."""
import importlib.util
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace

import pytest

from bm83.bm83 import Bm83
from utils import ticks

ENTRYPOINT = Path(__file__).resolve().parents[1] / "tools" / "bench_clean_shutdown_entrypoint.py"


class FakeUART:
    def __init__(self):
        self.writes = []
        self.timed_writes = []
        self.rx = bytearray()

    @property
    def in_waiting(self):
        return len(self.rx)

    def write(self, data):
        command = (data[3], bytes(data[4:-1]))
        self.writes.append(command)
        self.timed_writes.append((ticks.ticks_ms(),) + command)
        return len(data)

    def read(self, count):
        chunk = bytes(self.rx[:count])
        del self.rx[:count]
        return chunk


@pytest.fixture
def bench(monkeypatch):
    now = [100000]
    supervisor = ModuleType("supervisor")
    supervisor.runtime = SimpleNamespace(autoreload=True)
    supervisor.ticks_ms = lambda: now[0] & ticks.TICKS_MAX
    monkeypatch.setitem(sys.modules, "supervisor", supervisor)
    monkeypatch.setattr(ticks, "_hw_ticks_ms", supervisor.ticks_ms)
    monkeypatch.setattr(time, "monotonic", lambda: now[0] / 1000)
    spec = importlib.util.spec_from_file_location("bench_clean_shutdown_under_test", ENTRYPOINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    uart = FakeUART()
    bm = module.make_bench_type(Bm83)(uart)
    return SimpleNamespace(module=module, bm=bm, uart=uart, now=now, trial=bm._clean_shutdown_trial)


def advance(bench, milliseconds):
    bench.now[0] += milliseconds
    bench.bm.tick_power()


def event_batch(bench, events):
    """Retain production ACK/BTM dispatch after parsing actual UART frames."""
    for op, params in events:
        bench.uart.rx.extend(bench.bm.frame(op, params))
    parsed = bench.bm.poll()
    assert parsed == events
    for op, params in parsed:
        bench.bm.ack_event(op)
        if op == 0x01 and params:
            bench.bm.note_btm_state(params[0])
    bench.bm.tick_power()


def event(bench, op, params):
    event_batch(bench, [(op, params)])


def confirm_a2dp(bench):
    for state in (0x06, 0x0B, 0x82):
        bench.bm.note_btm_state(state)


def start(bench):
    confirm_a2dp(bench)
    bench.bm.power_off_cmd()
    assert bench.trial.phase == "snapshot"
    assert bench.bm._power_state is None
    assert bench.bm.power_on is True
    assert bench.bm._explicit_off is False


def snapshot(bench, database=0):
    data = b"\x04\x07\x00\x01\x00\x01\x00"
    if database == 1:
        data = b"\x04\x00\x07\x00\x01\x00\x01"
    event_batch(bench, [(0x1E, data), (0x00, b"\x0D\x00")])
    assert bench.trial.phase == "pause_ack"


def reach(bench, phase):
    start(bench)
    if phase == "snapshot":
        return
    snapshot(bench)
    if phase == "pause_ack":
        return
    event(bench, 0x00, b"\x04\x00")
    assert bench.trial.phase == "pause_settle"
    if phase == "pause_settle":
        return
    advance(bench, 3000)
    assert bench.trial.phase == "disconnect"
    if phase == "disconnect":
        return
    event_batch(bench, [(0x01, b"\x08\x00"), (0x00, b"\x18\x00")])
    assert bench.trial.phase == "disconnect_settle"


def finish_off(bench):
    assert bench.bm._power_state == "off_press"
    assert bench.bm.power_on is True
    advance(bench, 1499)
    assert bench.bm._power_state == "off_press"
    advance(bench, 1)
    assert bench.bm._power_state is None
    assert bench.bm.power_on is False
    assert bench.bm._explicit_off is True
    assert bench.bm.connected is False
    assert bench.bm.tick_link_recovery() is False


def test_boot_and_readonly_observation_do_not_arm(bench):
    confirm_a2dp(bench)
    advance(bench, 20000)
    event(bench, 0x1E, b"\x04\x07\x00\x01\x00\x01\x00")
    assert bench.trial.phase == "idle"
    assert bench.module._TRIAL_USED is False
    assert bench.uart.writes == [(0x14, b"\x1E")]


@pytest.mark.parametrize("database", [0, 1])
def test_successful_order_settle_gaps_and_original_off_hold(bench, database):
    start(bench)
    snapshot(bench, database)
    assert bench.uart.writes[-1] == (0x04, b"\x00\x06")  # First byte is reserved.
    advance(bench, 20)
    event(bench, 0x00, b"\x04\x00")
    advance(bench, 2999)
    assert not any(op == 0x18 for op, _ in bench.uart.writes)
    advance(bench, 1)
    assert bench.uart.writes[-1] == (0x18, b"\x04")
    event(bench, 0x00, b"\x18\x00")
    assert bench.trial.phase == "disconnect"
    event(bench, 0x01, b"\x08\x00")
    advance(bench, 999)
    assert bench.bm._power_state is None
    advance(bench, 1)
    assert bench.trial.prepared is True
    finish_off(bench)
    commands = [item for item in bench.uart.writes if item[0] != 0x14]
    assert commands == [
        (0x0D, b"\x00"), (0x04, b"\x00\x06"), (0x18, b"\x04"),
        (0x02, b"\x00\x53"), (0x02, b"\x00\x54"),
    ]
    timed = [item for item in bench.uart.timed_writes if item[1] != 0x14]
    assert ticks.ticks_diff(timed[2][0], timed[1][0]) >= 3000
    assert ticks.ticks_diff(timed[4][0], timed[3][0]) == 1500


@pytest.mark.parametrize("data", [
    b"\x04\x07",                                      # Truncated reply.
    b"\x04\x00\x00\x00\x00\x00\x00",              # No A2DP database.
    b"\x06\x07\x07\x01\x01\x01\x01",              # Two databases.
    b"\x02\x07\x00\x01\x00\x01\x00",              # Standby, despite flags.
    b"\x04\x03\x00\x01\x00\x01\x00",              # AVRCP missing.
    b"\x04\x06\x00\x01\x00\x01\x00",              # A2DP signaling missing.
])
def test_invalid_or_ambiguous_snapshot_falls_back_without_pause(bench, data):
    start(bench)
    event_batch(bench, [(0x00, b"\x0D\x00"), (0x1E, data)])
    assert bench.trial.outcome.startswith("fallback:")
    assert not any(op in (0x04, 0x18) for op, _ in bench.uart.writes)
    finish_off(bench)


@pytest.mark.parametrize("only_event", [
    (0x00, b"\x0D\x00"),
    (0x1E, b"\x04\x07\x00\x01\x00\x01\x00"),
])
def test_snapshot_requires_ack_and_fresh_data(bench, only_event):
    start(bench)
    event_batch(bench, [only_event])
    assert bench.trial.phase == "snapshot"
    advance(bench, 2000)
    assert bench.trial.outcome == "fallback: snapshot timeout"
    assert not any(op in (0x04, 0x18) for op, _ in bench.uart.writes)
    finish_off(bench)


@pytest.mark.parametrize("phase,command", [("snapshot", 0x0D), ("pause_ack", 0x04), ("disconnect", 0x18)])
def test_command_rejection_falls_back_once(bench, phase, command):
    reach(bench, phase)
    event(bench, 0x00, bytes((command, 0x01)))
    assert bench.trial.outcome == "fallback: command 0x%02X rejected" % command
    finish_off(bench)
    sent = list(bench.uart.writes)
    advance(bench, 40000)
    assert bench.uart.writes == sent


@pytest.mark.parametrize("valid_in_batch", ["none", "after", "before"])
@pytest.mark.parametrize("tail", [b"", b"\x00\xFF"])
@pytest.mark.parametrize("phase,command", [("snapshot", 0x0D), ("pause_ack", 0x04), ("disconnect", 0x18)])
def test_malformed_command_ack_length_latches_fallback(bench, phase, command, tail, valid_in_batch):
    reach(bench, phase)
    before = [item for item in bench.uart.writes if item[0] in (0x04, 0x18)]
    events = [(0x00, bytes((command,)) + tail)]
    if valid_in_batch != "none":
        events.insert(len(events) if valid_in_batch == "after" else 0, (0x00, bytes((command, 0x00))))
    if phase == "snapshot":
        events.insert(0, (0x1E, b"\x04\x07\x00\x01\x00\x01\x00"))
    elif phase == "disconnect":
        events.insert(0, (0x01, b"\x08\x00"))
    event_batch(bench, events)
    assert bench.trial.outcome == "fallback: invalid command 0x%02X ACK length" % command
    assert bench.trial.prepared is False
    finish_off(bench)
    advance(bench, 40000)
    assert [item for item in bench.uart.writes if item[0] in (0x04, 0x18)] == before


@pytest.mark.parametrize("phase", ["snapshot", "pause_ack", "disconnect"])
def test_phase_timeouts_fall_back_to_original_off(bench, phase):
    reach(bench, phase)
    advance(bench, 2000)
    assert bench.trial.outcome == "fallback: " + phase + " timeout"
    assert bench.trial.prepared is False
    finish_off(bench)


@pytest.mark.parametrize("events", [
    [(0x00, b"\x18\x00")],
    [(0x01, b"\x08\x00")],
    [(0x00, b"\x18\x00"), (0x01, b"\x11\x00")],
])
def test_disconnect_needs_ack_and_actual_a2dp_down(bench, events):
    reach(bench, "disconnect")
    event_batch(bench, events)
    assert bench.trial.phase == "disconnect"
    advance(bench, 2000)
    assert bench.trial.outcome == "fallback: disconnect timeout"
    finish_off(bench)


def test_delayed_loop_hits_total_deadline_without_late_disconnect(bench):
    reach(bench, "pause_settle")
    advance(bench, 10000)
    assert bench.trial.outcome == "fallback: total preparation timeout"
    assert not any(op == 0x18 for op, _ in bench.uart.writes)
    finish_off(bench)


@pytest.mark.parametrize("condition", ["aux", "unknown_source", "disconnected", "suspended", "confirmation"])
def test_ineligible_state_bypasses_preparation(bench, condition):
    confirm_a2dp(bench)
    if condition == "aux":
        bench.bm.note_btm_state(0x81)
    elif condition == "unknown_source":
        bench.bm.audio_source = None
    elif condition == "disconnected":
        bench.bm.connected = False
    elif condition == "suspended":
        bench.bm._avrcp_suspended = True
    elif condition == "confirmation":
        bench.bm._power_confirm_deadline = time.monotonic() + 3
    bench.bm.power_off_cmd()
    assert bench.module._TRIAL_USED is False
    assert bench.uart.writes == [(0x02, b"\x00\x53")]
    finish_off(bench)


def test_existing_on_press_is_not_stolen_by_off_preparation(bench):
    bench.bm.power_on_cmd()
    before = list(bench.uart.writes)
    bench.bm.power_off_cmd()
    assert bench.trial.phase == "idle"
    assert bench.module._TRIAL_USED is False
    assert bench.bm._power_state == "on_press"
    assert bench.uart.writes == before


@pytest.mark.parametrize("phase", ["snapshot", "pause_ack", "pause_settle", "disconnect", "disconnect_settle"])
def test_aux_arrival_falls_back_without_further_preparation(bench, phase):
    reach(bench, phase)
    before = [item for item in bench.uart.writes if item[0] in (0x04, 0x18)]
    event(bench, 0x01, b"\x81\x00")
    assert bench.trial.outcome == "fallback: AUX source observed"
    finish_off(bench)
    assert [item for item in bench.uart.writes if item[0] in (0x04, 0x18)] == before


@pytest.mark.parametrize("phase", ["snapshot", "pause_ack", "pause_settle", "disconnect", "disconnect_settle"])
def test_repeated_off_forces_original_shutdown(bench, phase):
    reach(bench, phase)
    bench.bm.power_off_cmd()
    assert bench.trial.outcome == "repeated OFF: bypass preparation"
    assert bench.uart.writes[-1] == (0x02, b"\x00\x53")
    finish_off(bench)


@pytest.mark.parametrize("phase", ["snapshot", "pause_ack", "pause_settle", "disconnect", "disconnect_settle"])
def test_explicit_on_cancels_without_a_conflicting_power_sequence(bench, phase):
    reach(bench, phase)
    before = list(bench.uart.writes)
    bench.bm.power_on_cmd()
    assert bench.trial.phase == "done"
    assert "cancelled by explicit user ON" in bench.trial.outcome
    assert bench.bm._power_state is None
    assert bench.bm.power_on is True
    advance(bench, 40000)
    assert bench.uart.writes == before


def test_actual_chip_off_ends_preparation_without_an_extra_off_press(bench):
    reach(bench, "pause_settle")
    event(bench, 0x01, b"\x00\x00")
    assert bench.trial.outcome == "chip reported OFF: no additional OFF command"
    assert bench.bm.power_on is False
    assert bench.bm._explicit_off is True
    assert not any(op == 0x02 for op, _ in bench.uart.writes)
    bench.bm.power_on_cmd()  # A later explicit ON still uses the real driver.
    assert bench.uart.writes[-1] == (0x02, b"\x00\x51")
    assert bench.bm._power_state == "on_press"


def test_batched_aux_and_a2dp_return_does_not_clear_fallback(bench):
    start(bench)
    event_batch(bench, [
        (0x00, b"\x0D\x00"), (0x1E, b"\x04\x07\x00\x01\x00\x01\x00"),
        (0x01, b"\x81\x00"), (0x01, b"\x82\x00"),
    ])
    assert bench.trial.outcome == "fallback: AUX source observed"
    assert not any(op in (0x04, 0x18) for op, _ in bench.uart.writes)
    finish_off(bench)


@pytest.mark.parametrize("state", [0x06, 0x0B, 0x15])
def test_fresh_establishment_invalidates_single_peer_snapshot_before_disconnect(bench, state):
    reach(bench, "pause_settle")
    event(bench, 0x01, bytes((state, 0x00)))
    assert bench.trial.outcome == "fallback: fresh link establishment during preparation"
    assert not any(op == 0x18 for op, _ in bench.uart.writes)
    finish_off(bench)


def test_ordinary_a2dp_source_report_does_not_invalidate_snapshot(bench):
    reach(bench, "pause_settle")
    event(bench, 0x01, b"\x82\x00")
    assert bench.trial.phase == "pause_settle"
    advance(bench, 3000)
    assert bench.uart.writes[-1] == (0x18, b"\x04")


def test_late_framed_snapshot_after_fallback_cannot_restart_preparation(bench):
    start(bench)
    advance(bench, 2000)
    finish_off(bench)
    event_batch(bench, [
        (0x1E, b"\x04\x07\x00\x01\x00\x01\x00"), (0x00, b"\x0D\x00"),
    ])
    assert bench.trial.outcome == "fallback: snapshot timeout"
    assert bench.bm.power_on is False
    assert bench.bm._explicit_off is True
    assert not any(op in (0x04, 0x18) for op, _ in bench.uart.writes)


def test_preparation_blocks_unowned_commands_but_keeps_event_acks(bench):
    reach(bench, "pause_settle")
    bm = bench.bm
    bm._pending_notif_regs = [(0.0, 0x02, 0)]
    bm._next_attrs_at = 1.0
    bm._avrcp_suspend_at = 1.0
    bm._boot_init_at = 1.0
    before = list(bench.uart.writes)
    bm.tick_avrcp()
    bm.tick_avrcp_attrs()
    bm.tick_notif_regs()
    bm.tick_stream_kick()
    bm.tick_avrcp_resume()
    bm.tick_link_recovery()
    bm.tick_boot_init()
    for op, params in [(0x04, b"\x00\x05"), (0x04, b"\x00\x06"), (0x17, b"\x02"),
                       (0x02, b"\x00\x5D"), (0x02, b"\x00\x82"),
                       (0x0D, b"\x00"), (0x18, b"\x04")]:
        bm.send(op, params)
    assert bench.uart.writes == before
    assert bm._pending_notif_regs == [(0.0, 0x02, 0)]
    assert bm._next_attrs_at == 1.0
    bm.ack_event(0x01)
    assert bench.uart.writes[-1] == (0x14, b"\x01")


def test_one_preparation_per_interpreter_without_play_or_linkback(bench):
    reach(bench, "disconnect_settle")
    advance(bench, 1000)
    finish_off(bench)
    confirm_a2dp(bench)
    bench.bm.power_off_cmd()
    assert bench.uart.writes[-1] == (0x02, b"\x00\x53")
    finish_off(bench)
    assert [op for op, _ in bench.uart.writes].count(0x0D) == 1
    assert [op for op, _ in bench.uart.writes].count(0x18) == 1
    assert (0x04, b"\x00\x05") not in bench.uart.writes
    assert not any(op == 0x17 for op, _ in bench.uart.writes)


def test_preparation_and_original_off_hold_survive_tick_wrap(bench):
    bench.now[0] = ticks.TICKS_PERIOD - 2500
    reach(bench, "disconnect_settle")
    advance(bench, 1000)
    finish_off(bench)
    assert bench.trial.prepared is True
    power = [item for item in bench.uart.timed_writes if item[1] == 0x02]
    assert ticks.ticks_diff(power[1][0], power[0][0]) == 1500


def test_run_disables_autoreload_and_patches_driver_before_main_import(bench, monkeypatch):
    import bm83 as package
    from bm83 import bm83 as driver
    from utils import common

    monkeypatch.setattr(package, "Bm83", Bm83)
    monkeypatch.setattr(driver, "Bm83", Bm83)
    monkeypatch.setattr(common, "dprint", common.dprint)
    monkeypatch.setattr(common, "DEBUG", common.DEBUG)
    firmware = ModuleType("main")
    captured = []

    def main():
        from bm83 import Bm83 as exported_type
        assert exported_type is driver.Bm83
        assert issubclass(exported_type, Bm83)
        captured.append(exported_type)

    firmware.main = main
    monkeypatch.setitem(sys.modules, "main", firmware)
    bench.module.run()
    assert len(captured) == 1
    assert sys.modules["supervisor"].runtime.autoreload is False

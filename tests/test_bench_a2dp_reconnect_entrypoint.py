"""Host-only checks for the temporary one-shot A2DP reconnect experiment."""
import importlib.util
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace

import pytest

from bm83.bm83 import Bm83
from utils import ticks

ENTRYPOINT = Path(__file__).resolve().parents[1] / "tools" / "bench_a2dp_reconnect_entrypoint.py"


class FakeUART:
    def __init__(self):
        self.writes = []
        self.rx = bytearray()

    @property
    def in_waiting(self):
        return len(self.rx)

    def write(self, data):
        self.writes.append((data[3], bytes(data[4:-1])))
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
    spec = importlib.util.spec_from_file_location("bench_reconnect_under_test", ENTRYPOINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    uart = FakeUART()
    bm = module.make_bench_type(Bm83)(uart)
    return SimpleNamespace(module=module, bm=bm, uart=uart, now=now, trial=bm._bench_trial)


def advance(bench, milliseconds):
    bench.now[0] += milliseconds
    bench.bm.tick_power()


def user_cycle(bench):
    bm = bench.bm
    bm.power_on = True
    bm.connected = True
    bm.power_off_cmd()
    advance(bench, 1500)
    bm.power_on_cmd()
    advance(bench, 2200)
    assert bm._power_state == "on_init"
    assert bench.trial.phase == "link"
    advance(bench, 500)
    assert bm._power_state is None
    bm.note_btm_state(0x02)
    bm.note_btm_state(0x06)
    bm.tick_power()
    advance(bench, 2000)
    assert bench.trial.phase == "snapshot"


def event(bench, opcode, params):
    event_batch(bench, [(opcode, params)])


def event_batch(bench, events):
    """Feed real frames together, retaining only ACK/BTM production dispatch."""
    for opcode, params in events:
        bench.uart.rx.extend(bench.bm.frame(opcode, params))
    parsed = bench.bm.poll()
    assert parsed == events
    for op, payload in parsed:
        bench.bm.ack_event(op)
        if op == 0x01 and payload:
            bench.bm.note_btm_state(payload[0])
    bench.bm.tick_power()


def valid_snapshot(bench):
    event(bench, 0x1E, b"\x02\x02\x00\x00\x00\x00\x00")
    assert not any(op == 0x18 for op, _ in bench.uart.writes)
    event(bench, 0x00, b"\x0D\x00")
    assert bench.trial.phase == "disconnect"


def enter_quiet(bench):
    user_cycle(bench)
    valid_snapshot(bench)
    event(bench, 0x01, b"\x08\x00")
    assert bench.trial.phase == "disconnect"
    event(bench, 0x00, b"\x18\x00")
    assert bench.trial.phase == "quiet"


def test_boot_never_arms_and_only_requests_read_only_snapshot(bench):
    bench.bm.note_btm_state(0x06)
    bench.bm.tick_power()
    advance(bench, 1999)
    assert bench.uart.writes == []
    advance(bench, 1)
    assert bench.uart.writes == [(0x0D, b"\x00")]
    assert bench.trial.phase == "idle"
    advance(bench, 10000)
    assert bench.uart.writes == [(0x0D, b"\x00")]


def test_on_without_user_off_does_not_arm(bench):
    bench.bm.power_on_cmd()
    assert bench.trial.phase == "idle"


def test_ignored_on_press_does_not_arm(bench):
    bench.bm.power_off_cmd()
    bench.bm.power_on_cmd()
    assert bench.bm._power_state == "off_press"
    assert bench.trial.phase == "idle"


def test_exactly_one_disconnect_then_linkback_and_fresh_confirmation(bench):
    enter_quiet(bench)
    advance(bench, 9999)
    assert not any(op == 0x17 for op, _ in bench.uart.writes)
    advance(bench, 1)
    assert bench.trial.phase == "relink"
    event(bench, 0x00, b"\x17\x00")
    assert bench.trial.phase == "relink"  # ACK alone cannot prove the link.
    event(bench, 0x01, b"\x06\x00")
    assert bench.trial.phase == "done"
    assert [item for item in bench.uart.writes if item[0] in (0x17, 0x18)] == [
        (0x18, b"\x04"), (0x17, b"\x02"),
    ]
    bench.bm.power_off_cmd()
    advance(bench, 1500)
    bench.bm.power_on_cmd()
    assert bench.trial.phase == "done"


@pytest.mark.parametrize("flags", [(0, 0), (2, 2), (1, 3)])
def test_snapshot_rejects_zero_or_multiple_a2dp_databases(bench, flags):
    user_cycle(bench)
    event(bench, 0x00, b"\x0D\x00")
    event(bench, 0x1E, bytes((2, flags[0], flags[1], 0, 0, 0, 0)))
    assert bench.trial.phase == "aborted"
    assert not any(op in (0x17, 0x18) for op, _ in bench.uart.writes)


def test_invalid_snapshot_length_aborts(bench):
    user_cycle(bench)
    event(bench, 0x1E, b"\x02\x02")
    assert bench.trial.phase == "aborted"


def test_snapshot_timeout_aborts_without_disconnect(bench):
    user_cycle(bench)
    advance(bench, 5000)
    assert bench.trial.outcome == "snapshot timeout"
    assert not any(op == 0x18 for op, _ in bench.uart.writes)


def test_disconnect_needs_ack_and_real_drop(bench):
    user_cycle(bench)
    valid_snapshot(bench)
    event(bench, 0x00, b"\x18\x00")
    assert bench.trial.phase == "disconnect"
    advance(bench, 8000)
    assert bench.trial.outcome == "disconnect timeout"
    assert not any(op == 0x17 for op, _ in bench.uart.writes)


@pytest.mark.parametrize("command", [0x0D, 0x18, 0x17])
def test_command_rejection_aborts_without_retry(bench, command):
    user_cycle(bench)
    if command in (0x18, 0x17):
        valid_snapshot(bench)
    if command == 0x17:
        event(bench, 0x00, b"\x18\x00")
        event(bench, 0x01, b"\x08\x00")
        advance(bench, 10000)
    event(bench, 0x00, bytes((command, 0x01)))
    assert bench.trial.outcome == "command rejected"
    sent = list(bench.uart.writes)
    advance(bench, 40000)
    assert bench.uart.writes == sent


def test_auto_reconnect_completes_quiet_gap_without_redundant_linkback(bench):
    enter_quiet(bench)
    event(bench, 0x01, b"\x06\x00")
    assert bench.trial.phase == "quiet"
    advance(bench, 10000)
    assert bench.trial.phase == "done"
    assert "auto-reconnected" in bench.trial.outcome
    assert not any(op == 0x17 for op, _ in bench.uart.writes)


def test_batched_framed_drop_and_return_avoids_redundant_linkback(bench):
    enter_quiet(bench)
    event_batch(bench, [(0x01, b"\x08\x00"), (0x01, b"\x06\x00")])
    assert bench.trial.phase == "quiet"
    assert bench.bm.connected is True
    advance(bench, 10000)
    assert bench.trial.phase == "done"
    assert "auto-reconnected" in bench.trial.outcome
    assert [item for item in bench.uart.writes if item[0] in (0x17, 0x18)] == [
        (0x18, b"\x04"),
    ]


def test_batched_aux_then_a2dp_return_cannot_revive_cancelled_trial(bench):
    enter_quiet(bench)
    event_batch(bench, [(0x01, b"\x81\x00"), (0x01, b"\x06\x00")])
    assert bench.trial.phase == "aborted"
    assert bench.trial.outcome == "OFF/AUX source observed"
    assert bench.bm.audio_source == bench.bm.AUDIO_SRC_AUX
    advance(bench, 40000)
    assert [item for item in bench.uart.writes if item[0] in (0x17, 0x18)] == [
        (0x18, b"\x04"),
    ]


def test_quiet_blocks_all_nonessential_tx_and_scheduler_work(bench):
    enter_quiet(bench)
    bm = bench.bm
    before = list(bench.uart.writes)
    bm._pending_notif_regs = [(0.0, 0x02, 0)]
    bm._next_attrs_at = 1.0
    bm._avrcp_suspend_at = 1.0
    bm._boot_init_at = 1.0
    bm.tick_avrcp()
    bm.tick_avrcp_attrs()
    bm.tick_notif_regs()
    bm.tick_stream_kick()
    bm.tick_avrcp_resume()
    bm.tick_link_recovery()
    bm.tick_boot_init()
    bm.avrcp_get_play_status()
    bm.send(0x04, b"\x00\x05")
    bm.send(0x02, b"\x00\x82")
    assert bench.uart.writes == before
    assert bm._pending_notif_regs == [(0.0, 0x02, 0)]
    assert bm._next_attrs_at == 1.0
    bm.ack_event(0x01)
    assert bench.uart.writes[-1] == (0x14, b"\x01")


def test_off_cancels_first_and_preserves_full_base_off_driver(bench):
    enter_quiet(bench)
    bench.bm.power_off_cmd()
    assert bench.trial.phase == "aborted"
    assert bench.uart.writes[-1] == (0x02, b"\x00\x53")
    advance(bench, 1499)
    assert bench.bm._power_state == "off_press"
    advance(bench, 1)
    assert bench.uart.writes[-1] == (0x02, b"\x00\x54")
    assert bench.bm._explicit_off is True
    assert bench.bm.power_on is False
    assert bench.bm.tick_link_recovery() is False


def test_off_during_snapshot_cancels_and_ignores_late_framed_reply(bench):
    user_cycle(bench)
    bench.bm.power_off_cmd()
    assert bench.trial.phase == "aborted"
    assert bench.uart.writes[-1] == (0x02, b"\x00\x53")
    advance(bench, 1499)
    assert bench.bm._power_state == "off_press"
    advance(bench, 1)
    assert bench.uart.writes[-1] == (0x02, b"\x00\x54")
    event_batch(bench, [
        (0x1E, b"\x04\x07\x00\x01\x00\x00\x00"),
        (0x00, b"\x0D\x00"),
    ])
    advance(bench, 40000)
    assert bench.trial.phase == "aborted"
    assert bench.bm._explicit_off is True
    assert bench.bm.power_on is False
    assert not any(op in (0x17, 0x18) for op, _ in bench.uart.writes)


def test_aux_event_aborts_and_no_linkback_is_sent(bench):
    enter_quiet(bench)
    event(bench, 0x01, b"\x81\x00")
    assert bench.trial.phase == "aborted"
    advance(bench, 10000)
    assert not any(op == 0x17 for op, _ in bench.uart.writes)


def test_initial_link_and_relink_timeouts_are_bounded(bench):
    bench.trial.off_requested = True
    bench.bm.power_on_cmd()
    advance(bench, 2200)
    advance(bench, 500)
    advance(bench, 30000)
    assert bench.trial.outcome == "link timeout"


def test_relink_timeout_has_no_second_attempt(bench):
    enter_quiet(bench)
    advance(bench, 10000)
    advance(bench, 30000)
    assert bench.trial.outcome == "relink timeout"
    assert [op for op, _ in bench.uart.writes].count(0x17) == 1


def test_trial_timing_survives_integer_tick_wrap(bench):
    bench.now[0] = ticks.TICKS_PERIOD - 7000
    enter_quiet(bench)
    advance(bench, 9999)
    assert bench.trial.phase == "quiet"
    advance(bench, 1)
    assert bench.trial.phase == "relink"


def test_run_patches_package_and_module_before_main_import(bench, monkeypatch):
    import bm83 as package
    from bm83 import bm83 as driver
    from utils import common

    monkeypatch.setattr(package, "Bm83", Bm83)
    monkeypatch.setattr(driver, "Bm83", Bm83)
    monkeypatch.setattr(common, "dprint", common.dprint)
    monkeypatch.setattr(common, "DEBUG", common.DEBUG)
    captured = []
    firmware = ModuleType("main")

    def main():
        from bm83 import Bm83 as exported_type
        assert exported_type is driver.Bm83
        assert exported_type is not Bm83
        assert issubclass(exported_type, Bm83)
        captured.append(exported_type)

    firmware.main = main
    monkeypatch.setitem(sys.modules, "main", firmware)
    bench.module.run()
    assert len(captured) == 1
    assert sys.modules["supervisor"].runtime.autoreload is False

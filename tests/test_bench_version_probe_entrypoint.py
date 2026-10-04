"""Host checks for a read-only version probe using production UART framing."""
import importlib.util
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace

import pytest

from bm83.bm83 import Bm83
from utils import ticks

ENTRYPOINT = Path(__file__).resolve().parents[1] / "tools" / "bench_version_probe_entrypoint.py"
REPLIES = (b"\x00\x02\x09", b"\x01\x01\x03", b"\x03\x01\x03\x05\x06",
           b"\x04\x01\x04\x04\x12", b"\x05SPP")


class FakeUART:
    def __init__(self):
        self.writes = []
        self.rx = bytearray()

    @property
    def in_waiting(self):
        return len(self.rx)

    def write(self, data):
        self.writes.append(bytes(data))
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
    spec = importlib.util.spec_from_file_location("bench_version_under_test", ENTRYPOINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    uart = FakeUART()
    bm = module.make_bench_type(Bm83)(uart)
    return SimpleNamespace(module=module, bm=bm, uart=uart, now=now, probe=bm._version_probe)


def commands(bench):
    return [(data[3], bytes(data[4:-1])) for data in bench.uart.writes]


def advance(bench, milliseconds):
    bench.now[0] += milliseconds
    bench.bm.tick_power()


def event_batch(bench, events):
    """Parse real frames, leaving ACK and BTM dispatch with the normal caller."""
    for op, params in events:
        bench.uart.rx.extend(bench.bm.frame(op, params))
    parsed = bench.bm.poll()
    assert parsed == events
    for op, params in parsed:
        bench.bm.ack_event(op)
        if op == 0x01 and params:
            bench.bm.note_btm_state(params[0])
    bench.bm.tick_power()


def start(bench):
    bench.bm.note_btm_state(0x06)
    event_batch(bench, [(0x00, b"\x0D\x00")])
    advance(bench, 1999)
    assert not any(op == 0x08 for op, _ in commands(bench))
    advance(bench, 1)
    assert bench.probe.phase == "query"
    assert commands(bench)[-1] == (0x08, b"\x00")


def complete_query(bench, reply):
    event_batch(bench, [(0x00, b"\x08\x00"), (0x18, reply)])


def test_queries_are_sequential_typed_and_do_not_repeat_on_power(bench, capsys):
    start(bench)
    for i, reply in enumerate(REPLIES):
        if i:
            advance(bench, 249)
            assert len([op for op, _ in commands(bench) if op == 0x08]) == i
            advance(bench, 1)
        assert commands(bench)[-1] == (0x08, reply[:1])
        # A matching reply alone stays outstanding until its separate ACK.
        event_batch(bench, [(0x18, reply)])
        assert bench.probe.phase == "query"
        event_batch(bench, [(0x00, b"\x08\x00")])
    assert bench.probe.phase == "done"
    assert [result[1] for result in bench.probe.results] == ["OBSERVED"] * 5
    assert [result[3] for result in bench.probe.results] == list(REPLIES)
    frames = [data.hex(" ").upper() for data in bench.uart.writes if data[3] == 0x08]
    assert frames == ["AA 00 02 08 00 F6", "AA 00 02 08 01 F5", "AA 00 02 08 03 F3",
                      "AA 00 02 08 04 F2", "AA 00 02 08 05 F1"]
    assert [p for op, p in commands(bench) if op == 0x14] == [b"\x18"] * 5
    assert all(op in (0x08, 0x14) for op, _ in commands(bench))
    output = capsys.readouterr().out
    assert "ACK opcode=08 raw: 08 00" in output
    assert "RX event=18 raw: 03 01 03 05 06" in output
    assert "project ASCII rendering: SPP" in output
    bench.bm.power_off_cmd()
    advance(bench, 1500)
    assert bench.bm._explicit_off is True
    assert bench.bm.power_on is False
    bench.bm.power_on_cmd()
    advance(bench, 2200)
    advance(bench, 500)
    bench.bm.note_btm_state(0x06)
    advance(bench, 20000)
    assert len([op for op, _ in commands(bench) if op == 0x08]) == 5


def test_already_powered_module_after_vm_reload_queries_without_false_on_confirmation(bench):
    # Initial ACK is a valid frame from an already-on module; it cannot turn
    # production power_on True, but suffices for this read-only diagnostic.
    event_batch(bench, [(0x00, b"\x0D\x00")])
    assert bench.bm.power_on is False
    advance(bench, 1999)
    assert commands(bench) == []
    advance(bench, 1)
    assert commands(bench) == [(0x08, b"\x00")]
    assert bench.bm.power_on is False
    assert bench.bm.connected is False
    assert bench.bm._power_state is None
    assert bench.bm._power_confirm_deadline == 0
    for i, reply in enumerate(REPLIES):
        if i:
            advance(bench, 250)
        complete_query(bench, reply)
    assert bench.probe.phase == "done"
    assert all(result[1] == "OBSERVED" for result in bench.probe.results)
    assert bench.bm.power_on is False
    assert all(op in (0x08, 0x14) for op, _ in commands(bench))


def test_power_cache_and_raw_or_corrupt_uart_bytes_cannot_establish_readiness(bench):
    bench.bm.note_btm_state(0x06)
    bench.uart.rx.extend(b"noise")
    corrupt = bytearray(bench.bm.frame(0x00, b"\x0D\x00"))
    corrupt[-1] ^= 1
    bench.uart.rx.extend(corrupt)
    assert bench.bm.poll() == []
    assert bench.probe.last_event_at is None
    bench.bm.tick_power()
    advance(bench, 2000)
    assert commands(bench) == []
    advance(bench, 30000)
    assert bench.probe.phase == "done"
    assert all(result[1] == "INCONCLUSIVE" for result in bench.probe.results)
    assert commands(bench) == []


def test_stale_validated_event_restarts_settle_without_reusing_cached_liveness(bench):
    event_batch(bench, [(0x00, b"\x0D\x00")])
    advance(bench, 2251)
    assert bench.probe.stable_since is None
    assert commands(bench) == []
    event_batch(bench, [(0x00, b"\x0F\x00")])
    advance(bench, 2001)
    assert commands(bench) == [(0x08, b"\x00")]


def test_validated_event_timestamp_zero_is_fresh_and_queries_without_power_mutation(bench):
    bench.now[0] = ticks.TICKS_PERIOD
    bench.probe.deadline = ticks.ticks_add(0, 30000)
    event_batch(bench, [(0x00, b"\x0D\x00")])
    assert bench.probe.last_event_at == 0
    advance(bench, 2000)
    assert commands(bench) == [(0x08, b"\x00")]
    assert bench.bm.power_on is False


def test_stale_validated_event_before_next_query_stops_remaining_types(bench):
    start(bench)
    complete_query(bench, REPLIES[0])
    advance(bench, 2251)
    assert bench.probe.phase == "done"
    assert bench.probe.results[0][1] == "OBSERVED"
    assert all(result[1] == "INCONCLUSIVE" for result in bench.probe.results[1:])
    assert len([op for op, _ in commands(bench) if op == 0x08]) == 1


@pytest.mark.parametrize("guard", ["_power_state", "_power_confirm_deadline"])
def test_active_or_pending_on_transition_prevents_readiness(bench, guard):
    # Use the controller tick directly: production owns these transition fields.
    setattr(bench.bm, guard, "on_press" if guard == "_power_state" else 200.0)
    bench.uart.rx.extend(bench.bm.frame(0x00, b"\x0D\x00"))
    bench.bm.poll()
    bench.probe.tick()
    bench.now[0] += 2000
    bench.probe.tick()
    assert not any(op == 0x08 for op, _ in commands(bench))
    setattr(bench.bm, guard, None if guard == "_power_state" else 0)
    event_batch(bench, [(0x00, b"\x0D\x00")])
    advance(bench, 2000)
    assert commands(bench)[-1] == (0x08, b"\x00")


@pytest.mark.parametrize("chip_off", [False, True])
def test_user_or_chip_off_before_probe_cancels_permanently(bench, chip_off):
    event_batch(bench, [(0x00, b"\x0D\x00")])
    if chip_off:
        event_batch(bench, [(0x01, b"\x00\x00")])
    else:
        bench.bm.power_off_cmd()
        advance(bench, 1500)
    assert bench.probe.phase == "done"
    event_batch(bench, [(0x00, b"\x0D\x00"), (0x01, b"\x06\x00")])
    advance(bench, 5000)
    assert not any(op == 0x08 for op, _ in commands(bench))


def test_debug_logs_version_body_once_and_keeps_other_event_dumps(bench, monkeypatch, capsys):
    from bm83 import bm83 as driver
    from utils import common

    monkeypatch.setattr(common, "DEBUG", True)
    # In actual run(), the adapter is set before this driver's first import.
    monkeypatch.setattr(driver, "dprint", bench.module._bench_dprint)
    start(bench)
    complete_query(bench, REPLIES[0])
    event_batch(bench, [(0x01, b"\x82\x00")])
    output = capsys.readouterr().out
    assert output.count("00 02 09") == 1
    assert "[BM83 EVT] op=0x18" not in output
    assert "[BM83 EVT] op=0x01" in output
    assert "ACK opcode=08 raw: 08 00" in output


@pytest.mark.parametrize("events", [
    [(0x00, b"\x08\x00"), (0x18, REPLIES[0])],
    [(0x18, REPLIES[0]), (0x00, b"\x08\x00")],
])
def test_batched_reply_and_ack_order_is_preserved(bench, events):
    start(bench)
    event_batch(bench, events)
    assert bench.probe.results[0][1] == "OBSERVED"
    assert commands(bench)[-1] == (0x14, b"\x18")
    assert len([op for op, _ in commands(bench) if op == 0x08]) == 1


@pytest.mark.parametrize("status", [1, 2, 3, 4, 5])
def test_rejected_query_is_inconclusive_once_then_next_type(bench, status):
    start(bench)
    event_batch(bench, [(0x00, bytes((0x08, status)))])
    assert bench.probe.results[0][1] == "INCONCLUSIVE"
    assert bench.probe.results[0][2] == status
    advance(bench, 250)
    assert [params for op, params in commands(bench) if op == 0x08] == [b"\x00", b"\x01"]


@pytest.mark.parametrize("events", [[], [(0x00, b"\x08\x00")], [(0x18, REPLIES[0])]])
def test_missing_ack_or_reply_has_fixed_timeout_and_no_retry(bench, events):
    start(bench)
    event_batch(bench, events)
    advance(bench, 1999)
    assert bench.probe.phase == "query"
    advance(bench, 1)
    assert bench.probe.results[0][1] == "INCONCLUSIVE"
    advance(bench, 250)
    if events == [(0x00, b"\x08\x00")]:
        assert [params for op, params in commands(bench) if op == 0x08] == [b"\x00", b"\x01"]
    else:
        assert bench.probe.phase == "done"
        assert [params for op, params in commands(bench) if op == 0x08] == [b"\x00"]
        assert len(bench.probe.results) == 5
        if events:
            assert bench.probe.results[0][3] == REPLIES[0]


def test_delayed_ack_after_unresolved_timeout_cannot_start_or_complete_later_query(bench):
    start(bench)
    event_batch(bench, [(0x18, REPLIES[0])])
    advance(bench, 2000)
    assert bench.probe.phase == "done"
    before = list(bench.probe.results)
    event_batch(bench, [(0x00, b"\x08\x00"), (0x18, REPLIES[1])])
    advance(bench, 10000)
    assert bench.probe.results == before
    assert bench.probe.results[0][3] == REPLIES[0]
    assert all(result[1] == "INCONCLUSIVE" for result in bench.probe.results)
    assert [params for op, params in commands(bench) if op == 0x08] == [b"\x00"]


@pytest.mark.parametrize("payload", [b"\x00", b"\x00\x01", b"\x00\x01\x02\x03"])
def test_matching_type_wrong_length_is_inconclusive(bench, payload):
    start(bench)
    event_batch(bench, [(0x18, payload), (0x00, b"\x08\x00")])
    assert bench.probe.results[0][1] == "INCONCLUSIVE"


def test_wrong_type_unrelated_ack_and_conflicting_replies(bench):
    start(bench)
    event_batch(bench, [(0x18, REPLIES[1]), (0x00, b"\x0D\x00"), (0x18, b"\xFF\xFF\xFF")])
    assert bench.probe.ack is None
    assert bench.probe.reply is None
    event_batch(bench, [(0x18, REPLIES[0]), (0x18, b"\x00\x01\x00"), (0x00, b"\x08\x00")])
    assert bench.probe.results[0][1] == "INCONCLUSIVE"


def test_late_previous_reply_cannot_satisfy_next_type(bench):
    start(bench)
    event_batch(bench, [(0x00, b"\x08\x00")])
    advance(bench, 2000)
    advance(bench, 250)
    event_batch(bench, [(0x00, b"\x08\x00"), (0x18, REPLIES[0])])
    assert bench.probe.index == 1
    assert bench.probe.reply is None
    event_batch(bench, [(0x18, REPLIES[1])])
    assert bench.probe.results[1][3] == REPLIES[1]


def test_frames_received_at_deadline_are_logged_but_not_accepted(bench, capsys):
    start(bench)
    bench.now[0] += 2000
    complete_query(bench, REPLIES[0])
    assert bench.probe.results[0][1] == "INCONCLUSIVE"
    assert bench.probe.results[0][3] is None
    assert "RX event=18 raw: 00 02 09" in capsys.readouterr().out


@pytest.mark.parametrize("phase", ["query", "gap"])
def test_user_off_cancels_probe_and_keeps_original_shutdown(bench, phase):
    start(bench)
    if phase == "gap":
        complete_query(bench, REPLIES[0])
    bench.bm.power_off_cmd()
    bench.bm.tick_power()
    assert bench.probe.phase == "done"
    assert bench.bm._power_state == "off_press"
    assert bench.probe.results[-1][3] is None
    advance(bench, 1499)
    assert bench.bm._power_state == "off_press"
    advance(bench, 1)
    assert bench.bm._explicit_off is True
    assert bench.bm.power_on is False
    assert [p for op, p in commands(bench) if op == 0x02] == [b"\x00\x53", b"\x00\x54"]
    assert len([op for op, _ in commands(bench) if op == 0x08]) == 1


def test_chip_off_in_reply_batch_wins_without_generated_power_action(bench):
    start(bench)
    event_batch(bench, [(0x18, REPLIES[0]), (0x00, b"\x08\x00"), (0x01, b"\x00\x00")])
    assert bench.probe.phase == "done"
    assert bench.probe.results[0][1] == "INCONCLUSIVE"
    assert bench.bm.power_on is False
    assert all(op in (0x08, 0x14) for op, _ in commands(bench))


def test_probe_timeout_survives_tick_wrap_and_other_driver_controls_continue(bench):
    bench.now[0] = ticks.TICKS_PERIOD - 2500
    start(bench)
    bench.bm.avrcp_get_play_status(0)
    assert commands(bench)[-1][0] == 0x0B
    for _ in REPLIES:
        event_batch(bench, [(0x00, b"\x08\x00")])
        advance(bench, 2000)
        if bench.probe.phase != "done":
            advance(bench, 250)
    assert bench.probe.phase == "done"
    assert len([op for op, _ in commands(bench) if op == 0x08]) == 5
    assert all(result[1] == "INCONCLUSIVE" for result in bench.probe.results)


def test_send_failure_is_inconclusive_without_reset_or_retry(bench, monkeypatch):
    def failed_write(data):
        raise OSError("test transport failure")

    monkeypatch.setattr(bench.uart, "write", failed_write)
    bench.bm.note_btm_state(0x06)
    event_batch(bench, [(0x00, b"\x0D\x00")])
    advance(bench, 2000)
    # Production send() logs/swallow write errors, so the no-ACK deadline
    # handles transport failure without adding any driver behavior.
    advance(bench, 2000)
    assert bench.probe.results[0][1] == "INCONCLUSIVE"
    assert "timeout waiting for command ACK" in bench.probe.results[0][4]
    assert bench.probe.phase == "done"
    assert bench.uart.writes == []
    assert bench.bm._power_state is None


@pytest.mark.parametrize("payload", [b"\x08", b"\x08\x00\x00"])
def test_malformed_ack_stops_remaining_queries(bench, payload):
    start(bench)
    event_batch(bench, [(0x00, payload)])
    assert bench.probe.phase == "done"
    assert len(bench.probe.results) == 5
    assert all(result[1] == "INCONCLUSIVE" for result in bench.probe.results)
    advance(bench, 10000)
    assert len([op for op, _ in commands(bench) if op == 0x08]) == 1


@pytest.mark.parametrize("acks", [
    [b"\x08\x00", b"\x08\x00\x00"],
    [b"\x08\x00\x00", b"\x08\x00"],
    [b"\x08\x00", b"\x08\x02"],
])
def test_ack_ambiguity_is_latched_across_whole_framed_batch(bench, acks):
    start(bench)
    event_batch(bench, [(0x00, ack) for ack in acks] + [(0x18, REPLIES[0])])
    assert bench.probe.phase == "done"
    assert all(result[1] == "INCONCLUSIVE" for result in bench.probe.results)
    assert bench.probe.results[0][3] == REPLIES[0]


def test_second_instance_cannot_repeat_probe_in_same_interpreter(bench):
    bm = bench.module.make_bench_type(Bm83)(FakeUART())
    bm.note_btm_state(0x06)
    bm.tick_power()
    bench.now[0] += 5000
    bm.tick_power()
    assert bm._version_probe.phase == "done"
    assert bm.uart.writes == []


def test_run_disables_autoreload_and_patches_exports_before_delegation(bench, monkeypatch):
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
        assert package.Bm83 is driver.Bm83
        assert issubclass(driver.Bm83, Bm83)
        captured.append(driver.Bm83)

    firmware.main = main
    monkeypatch.setitem(sys.modules, "main", firmware)
    bench.module.run()
    assert len(captured) == 1
    assert sys.modules["supervisor"].runtime.autoreload is False
    assert common.DEBUG is True

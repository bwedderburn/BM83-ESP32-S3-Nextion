"""Bounded timing, exact delegation and separation of measured/unknown data."""

import hashlib
import hmac
import json
import builtins

import pytest

from remote import badge_remote
from remote.espnow_rx import EspNowRemote
from utils import phase1_metrics as metrics_module
from utils.phase1_metrics import Phase1Metrics, TimingUART
from utils.ticks import TICKS_PERIOD


class Clock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value

    def advance(self, nanoseconds):
        self.value += nanoseconds


def observer(clock, **kwargs):
    return Phase1Metrics(clock=clock, heap_sampler=lambda: {
        "python_gc_free": 60000, "python_gc_alloc": 12000,
        "native_8bit_free": 4000000, "native_8bit_largest": 3000000}, **kwargs)


def test_nanosecond_units_do_not_claim_hardware_resolution_or_budget():
    clock = Clock()
    metrics = observer(clock)
    metrics.loop_begin()
    clock.advance(2700000000)
    metrics.loop_begin()
    snapshot = metrics.snapshot()
    assert snapshot["clock_unit_ns"] == 1
    assert snapshot["resolution_ns"] is None
    assert snapshot["acceptance_budget"] == "not_derived"
    assert snapshot["timing"]["loop_gap"]["max_ns"] == 2700000000
    assert snapshot["timing"]["loop_gap"]["histogram"][-1] == 1
    assert snapshot["timing"]["espnow_send_call"]["max_ns"] is None


def test_tick_fallback_handles_wrap_and_reports_millisecond_quantization():
    clock = Clock()
    clock.value = TICKS_PERIOD - 3
    metrics = observer(clock, clock_kind="ticks_ms")
    metrics.loop_begin()
    clock.value = 4
    metrics.loop_begin()
    snapshot = metrics.snapshot()
    assert snapshot["resolution_ns"] == 1000000
    assert snapshot["timing"]["loop_gap"]["max_ns"] == 7000000
    assert snapshot["events"]["clock_regression"] == 0


def test_clock_regression_cannot_be_a_healthy_zero_sample():
    clock = Clock()
    metrics = observer(clock)
    clock.value = 3
    metrics.loop_begin()
    clock.value = 1
    metrics.loop_begin()
    snapshot = metrics.snapshot()
    assert snapshot["events"]["clock_regression"] == 1
    assert snapshot["timing"]["loop_gap"]["samples"] == 0


def test_reporting_and_heap_samples_are_bounded_without_forced_gc(monkeypatch):
    monkeypatch.setattr(metrics_module.gc, "collect", lambda: pytest.fail("observer forced GC"))
    clock = Clock()
    metrics = observer(clock)
    output = []
    assert not metrics.report_if_due(output.append)
    for _ in range(1000):
        clock.advance(1000000)
        metrics.loop_begin()
        metrics.report_if_due(output.append)
    assert output == []
    assert metrics.snapshot()["heap"]["samples"] == 1
    clock.value = 10000000000
    assert metrics.report_if_due(output.append)
    assert len(output) == 1
    captured = json.loads(output[0].split(" ", 1)[1])
    assert captured["heap"]["samples"] == 2
    assert captured["heap"]["native_dma_only"] is None
    assert captured["heap"]["native_internal_only"] is None
    assert captured["heap"]["native_tx_queue_depth"] is None
    assert captured["heap"]["system_socket_count"] is None
    assert not metrics.report_if_due(output.append)
    assert len(metrics._histograms) == len(metrics_module.METRICS)
    assert all(len(row) == len(metrics_module.BUCKET_NS) + 1 for row in metrics._histograms)


def test_observer_output_failure_is_explicit_and_does_not_change_controls():
    clock = Clock()
    metrics = observer(clock)
    clock.advance(10000000000)

    def unavailable(_line):
        raise OSError("console closed")

    assert not metrics.report_if_due(unavailable)
    assert metrics.snapshot()["events"]["report_error"] == 1
    assert metrics.snapshot()["timing"]["report"]["samples"] == 1


def test_unavailable_heap_and_uart_observations_are_not_healthy_zero():
    clock = Clock()
    metrics = Phase1Metrics(clock=clock, heap_sampler=lambda: (_ for _ in ()).throw(RuntimeError()))
    metrics.sample_heap_if_due()
    metrics.uart_poll(0, None)
    snapshot = metrics.snapshot()
    assert snapshot["heap"]["latest"] is None
    assert snapshot["heap"]["samples"] == 0
    assert snapshot["uart"][0]["queue_samples"] == 0
    assert snapshot["uart"][0]["nominal_min_wire_headroom_ns"] is None
    assert snapshot["events"]["heap_sample_error"] == 1
    assert snapshot["events"]["uart_observation_unavailable"] == 1


def test_heap_sampler_cannot_add_identifiers_or_convert_unknown_values_to_zero():
    clock = Clock()
    metrics = Phase1Metrics(clock=clock, heap_sampler=lambda: {
        "python_gc_free": 14, "python_gc_alloc": -1,
        "native_8bit_free": "unknown", "private_identifier": "DO-NOT-REPORT"})
    metrics.sample_heap_if_due()
    snapshot = metrics.snapshot()
    assert snapshot["heap"]["latest"] == {"python_gc_free": 14, "python_gc_alloc": None,
                                           "native_8bit_free": None, "native_8bit_largest": None}
    assert "DO-NOT-REPORT" not in json.dumps(snapshot)


def test_uart_exact_delegation_bytes_gaps_and_nominal_capacity():
    clock = Clock()
    metrics = observer(clock)

    class UART:
        baudrate = 115200
        in_waiting = 200

        def read(self, size):
            assert size == 8
            clock.advance(2000000)
            return b"received"

        def write(self, data):
            assert data is payload
            clock.advance(3000000)
            return len(data) - 1  # preserve partial writes

    payload = bytearray(b"request")
    uart = TimingUART(UART(), metrics, 0)
    assert uart.baudrate == 115200
    assert uart.in_waiting == 200
    assert uart.read(8) == b"received"
    assert uart.write(payload) == 6
    assert uart.in_waiting == 200
    snapshot = metrics.snapshot()
    assert snapshot["timing"]["bm_uart_read"]["max_ns"] == 2000000
    assert snapshot["timing"]["bm_uart_write"]["max_ns"] == 3000000
    assert snapshot["timing"]["bm_uart_queue_poll_gap"]["max_ns"] == 5000000
    status = snapshot["uart"][0]
    assert status["rx_bytes"] == 8 and status["tx_bytes"] == 6
    assert status["max_observed_waiting"] == 200
    assert status["nominal_min_wire_headroom_ns"] == (8192 - 200) * 10000000000 // 115200
    assert status["driver_fifo_reserve_bytes"] is None
    assert status["capacity_verified"] is False
    assert status["native_overflow_events"] is None
    assert status["queue_observation"] == "in_waiting_before_conditional_read_not_full_drain"


def test_uart_original_errors_propagate_with_failure_and_timing_record():
    clock = Clock()
    metrics = observer(clock)
    failure = RuntimeError("original UART failure")

    class UART:
        def read(self, _size):
            clock.advance(5000000)
            raise failure

    with pytest.raises(RuntimeError) as captured:
        TimingUART(UART(), metrics, 1).read(4)
    assert captured.value is failure
    assert metrics.snapshot()["events"]["uart_read_error"] == 1
    assert metrics.snapshot()["timing"]["nx_uart_read"]["max_ns"] == 5000000


def test_uart_queue_observation_failure_is_preserved_and_not_counted_as_zero():
    metrics = observer(Clock())
    failure = RuntimeError("native observation failed")

    class UART:
        @property
        def in_waiting(self):
            raise failure

    with pytest.raises(RuntimeError) as captured:
        _ = TimingUART(UART(), metrics, 0).in_waiting
    assert captured.value is failure
    snapshot = metrics.snapshot()
    assert snapshot["events"]["uart_observation_unavailable"] == 1
    assert snapshot["uart"][0]["queue_samples"] == 0


def test_espnow_synchronous_stall_and_observed_completion_are_distinct():
    clock = Clock()
    metrics = observer(clock)

    class Radio:
        send_success = 0
        send_failure = 0
        calls = 0

        def send(self, data, peer):
            assert data is frame and peer is chosen_peer
            self.calls += 1
            clock.advance(2700000000)

    radio = Radio()
    frame, chosen_peer = b"BMS2example", object()
    remote = EspNowRemote(clock=lambda: clock() / 1000000000, phase1_metrics=metrics)
    remote._radio = radio
    remote._tx_peer = chosen_peer
    remote.state_tx_enabled = True
    remote._tx_counts = (0, 0)
    assert remote.send_state_frame(frame)
    assert not remote.state_tx_ready()
    assert radio.calls == 1
    snapshot = metrics.snapshot()
    assert snapshot["timing"]["espnow_send_call"]["max_ns"] == 2700000000
    assert snapshot["timing"]["espnow_completion_observed"]["samples"] == 0
    clock.advance(20000000)
    radio.send_success += 1
    assert remote.state_tx_ready()
    snapshot = metrics.snapshot()
    assert snapshot["timing"]["espnow_completion_observed"]["max_ns"] == 2720000000
    assert snapshot["espnow_callbacks"]["success_observed"] == 1
    assert snapshot["espnow_callbacks"]["failure_observed"] == 0


def test_async_espnow_failure_has_its_own_outcome_and_neutral_completion():
    clock = Clock()
    metrics = observer(clock)

    class Radio:
        send_success = 0
        send_failure = 0

        def send(self, _data, _peer):
            pass

    remote = EspNowRemote(phase1_metrics=metrics)
    remote._radio = Radio()
    remote.state_tx_enabled = True
    assert remote.send_state_frame(b"BMS2example")
    clock.advance(12000000)
    remote._radio.send_failure += 1
    assert remote.state_tx_ready()
    snapshot = metrics.snapshot()
    assert snapshot["espnow_callbacks"]["success_observed"] == 0
    assert snapshot["espnow_callbacks"]["failure_observed"] == 1
    assert snapshot["events"]["espnow_send_error"] == 0  # send() itself did not raise.
    assert snapshot["timing"]["espnow_completion_observed"]["samples"] == 1
    assert snapshot["timing"]["espnow_completion_observed"]["max_ns"] == 12000000


def test_espnow_counter_read_error_is_explicit_and_keeps_existing_ready_failure():
    metrics = observer(Clock())
    failure = OSError("counter getter unavailable")

    class Radio:
        @property
        def send_success(self):
            raise failure

    remote = EspNowRemote(phase1_metrics=metrics)
    remote._radio = Radio()
    remote.state_tx_enabled = True
    assert not remote.state_tx_ready()
    snapshot = metrics.snapshot()
    assert snapshot["events"]["espnow_counter_read_error"] == 1
    assert snapshot["events"]["espnow_counter_unavailable"] == 1
    assert snapshot["espnow_callbacks"]["latest_observation_available"] is False
    assert snapshot["espnow_callbacks"]["success_observed"] is None
    assert snapshot["espnow_callbacks"]["failure_observed"] is None
    assert snapshot["timing"]["espnow_completion_observed"]["samples"] == 0


@pytest.mark.parametrize("invalid", [None, True, 1.0, -1, 0x100000000])
def test_espnow_outcome_counter_requires_exact_uint32_and_rebaselines_gaps(invalid):
    metrics = observer(Clock())
    metrics.espnow_counters((10, 4))
    metrics.espnow_counters((invalid, 5))
    missing = metrics.snapshot()
    assert missing["events"]["espnow_counter_unavailable"] == 1
    assert missing["espnow_callbacks"]["latest_observation_available"] is False
    metrics.espnow_counters((15, 6))  # Fresh baseline; do not hide the missing interval.
    metrics.espnow_counters((16, 8))
    snapshot = metrics.snapshot()
    assert snapshot["espnow_callbacks"]["success_observed"] == 1
    assert snapshot["espnow_callbacks"]["failure_observed"] == 2
    assert snapshot["espnow_callbacks"]["samples"] == 3


def test_espnow_uint32_wrap_counts_positive_deltas_but_not_reset_like_jumps():
    metrics = observer(Clock())
    metrics.espnow_counters((0xFFFFFFFF, 0xFFFFFFFE))
    metrics.espnow_counters((0, 1))
    snapshot = metrics.snapshot()
    assert snapshot["espnow_callbacks"]["success_observed"] == 1
    assert snapshot["espnow_callbacks"]["failure_observed"] == 3
    metrics.espnow_counters((0xFFFFFFFE, 1))  # Backward/reset-like, not 4 billion successes.
    metrics.espnow_counters((0xFFFFFFFF, 2))
    metrics.espnow_counter_reset()  # A reconstructed radio starts a distinct generation.
    metrics.espnow_counters((0, 0))
    snapshot = metrics.snapshot()
    assert snapshot["events"]["espnow_counter_discontinuity"] == 1
    assert snapshot["events"]["espnow_counter_baseline_reset"] == 1
    assert snapshot["espnow_callbacks"]["success_observed"] == 2
    assert snapshot["espnow_callbacks"]["failure_observed"] == 4


def test_enabled_main_wires_real_uart_parsers_crypto_and_radio_to_one_observer(monkeypatch):
    """Finite production loop over fake pins/UART/radio, with no input controls."""
    import importlib.util
    from pathlib import Path
    import sys
    import time
    import types
    from bm83.bm83 import Bm83
    from nextion.display import Nextion
    from remote.metadata_bridge import MetadataBridge
    from tests.test_main_metadata_retry import _Ble, _metadata, _play_status

    class Finished(BaseException):
        pass

    clock = Clock()
    captured = {}
    loop_sleeps = []

    def sleep(seconds):
        clock.advance(int(seconds * 1000000000))
        if seconds < 0.5:  # boot_sync's existing sleep is not a loop checkpoint.
            loop_sleeps.append(seconds)
            if len(loop_sleeps) == 3:
                raise Finished
            clock.advance(100000000)

    monkeypatch.setattr(time, "monotonic", lambda: clock() / 1000000000)
    monkeypatch.setattr(time, "monotonic_ns", clock)
    monkeypatch.setattr(time, "sleep", sleep)

    class UART(BufferedUART):
        def __init__(self, *_pins, baudrate, **_kwargs):
            incoming = (_metadata((1, "Observed Song"), (2, "Observed Artist")) + _play_status(1000)
                        if baudrate == 115200 else b"\x66\x01\xff\xff\xff")
            super().__init__(incoming)
            self.writes = []

        def read(self, size):
            clock.advance(2000000)
            return super().read(size)

        def write(self, data):
            clock.advance(1000000)
            self.writes.append(bytes(data))
            return len(data)

    board = types.ModuleType("board")
    for pin in (15, 16, 17, 18):
        setattr(board, "IO%d" % pin, pin)
    busio = types.ModuleType("busio")
    busio.UART = UART
    microcontroller = types.ModuleType("microcontroller")
    microcontroller.cpu = types.SimpleNamespace(reset_reason="host test")
    for name, module in (("board", board), ("busio", busio), ("microcontroller", microcontroller)):
        monkeypatch.setitem(sys.modules, name, module)

    path = Path(__file__).resolve().parents[1] / "firmware" / "circuitpython" / "main.py"
    spec = importlib.util.spec_from_file_location("_phase1_enabled_main", path)
    firmware = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(firmware)

    def nextion(uart, *, phase1_metrics):
        captured["nextion"] = Nextion(uart, phase1_metrics=phase1_metrics)
        return captured["nextion"]

    def bm83(uart, *, phase1_metrics):
        captured["bm83"] = Bm83(uart, phase1_metrics=phase1_metrics)
        return captured["bm83"]

    class Radio:
        def __init__(self):
            self.send_success = self.send_failure = 0
            self.peers = []
            self.frames = []

        def __bool__(self):
            return False

        def send(self, frame, peer):
            assert peer in self.peers
            self.frames.append(bytes(frame))
            clock.advance(3000000)
            self.send_success += 1

    radio = Radio()
    module = types.SimpleNamespace(ESPNow=lambda: radio, Peer=lambda **kwargs: kwargs)

    def remote(**kwargs):
        captured["remote"] = EspNowRemote(espnow_module=module, **kwargs)
        return captured["remote"]

    class Badge(badge_remote.BadgeRemote):
        def __init__(self):
            super().__init__(profile_path="/nonexistent-phase1-host-test-profile.json")

        def poll(self, state_fn, now=None):
            assert badge_remote.tag(bytes(32), b"host-wiring-vector") == hmac.new(
                bytes(32), b"host-wiring-vector", hashlib.sha256).hexdigest()[:32].encode()
            return super().poll(state_fn, now)

    monkeypatch.setattr(firmware, "Nextion", nextion)
    monkeypatch.setattr(firmware, "Bm83", bm83)
    monkeypatch.setattr(firmware, "EspNowRemote", remote)
    monkeypatch.setattr(firmware, "BleHid", _Ble)
    monkeypatch.setattr(firmware, "BadgeRemote", Badge)
    monkeypatch.setattr(firmware, "MetadataBridge", lambda: MetadataBridge(
        profile_path="/nonexistent-phase1-host-test-metadata.json"))
    monkeypatch.setattr(firmware, "start_artwork_wifi", lambda: False)
    try:
        with pytest.raises(Finished):
            firmware.main(phase1_timing=True)
        metrics = captured["remote"]._phase1_metrics
        assert isinstance(metrics, Phase1Metrics)
        assert captured["bm83"]._phase1_metrics is captured["nextion"]._phase1_metrics is metrics
        assert badge_remote._phase1_metrics is metrics
        for key in ("bm83", "nextion"):
            assert isinstance(captured[key].uart, TimingUART)
            assert captured[key].uart._metrics is metrics
            assert isinstance(captured[key].uart._uart, UART)
        snapshot = metrics.snapshot()
        assert snapshot["timing"]["loop_gap"]["samples"] == 2
        for name in ("bm_uart_read", "nx_uart_read", "bm_uart_write", "nx_uart_write", "espnow_send_call"):
            assert snapshot["timing"][name]["max_ns"] > 0
        assert snapshot["timing"]["hmac"]["samples"] == 3
        assert snapshot["timing"]["sha256"]["samples"] == 6
        assert snapshot["espnow_callbacks"]["success_observed"] > 0
        assert all(frame.startswith((b"BMS2", b"BLS2")) for frame in radio.frames)
        assert captured["nextion"].current_page == 1
    finally:
        badge_remote.set_phase1_metrics(None)


def test_production_hmac_unchanged_and_never_reports_credentials_or_payload():
    clock = Clock()
    metrics = observer(clock)
    key = b"private-test-key-never-report!??"
    assert len(key) == 32
    payload = b"PRIVATE-TRACK-AND-AUTHENTICATION-PAYLOAD"
    expected = hmac.new(key, payload, hashlib.sha256).hexdigest()[:32].encode()
    try:
        badge_remote.set_phase1_metrics(metrics)
        assert badge_remote.tag(key, payload) == expected
    finally:
        badge_remote.set_phase1_metrics(None)
    snapshot = metrics.snapshot()
    assert snapshot["timing"]["sha256"]["samples"] == 2
    assert snapshot["timing"]["hmac"]["samples"] == 1
    assert snapshot["sha256"]["input_bytes"] == len(payload) + 160
    assert snapshot["hmac"]["input_bytes"] == len(payload)
    serialized = json.dumps(snapshot)
    assert key.decode() not in serialized and key.hex() not in serialized
    assert payload.decode() not in serialized


def test_hash_allocation_update_failure_still_records_cleanup_and_original_error(monkeypatch):
    clock = Clock()
    metrics = observer(clock)
    failure = RuntimeError("hash update failure")
    closed = []

    class Digest:
        def update(self, _data):
            clock.advance(3000000)
            raise failure

        def deinit(self):
            clock.advance(2000000)
            closed.append(True)

    def create(_algorithm):
        clock.advance(1000000)
        return Digest()

    monkeypatch.setattr(badge_remote.hashlib, "new", create)
    try:
        badge_remote.set_phase1_metrics(metrics)
        with pytest.raises(RuntimeError) as captured:
            badge_remote._sha256(b"public-test-vector")
    finally:
        badge_remote.set_phase1_metrics(None)
    assert captured.value is failure
    assert closed == [True]
    assert metrics.snapshot()["timing"]["sha256"]["max_ns"] == 6000000


def test_disabled_metrics_do_not_import_timing_module_in_production_crypto_or_radio(monkeypatch):
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert name != "utils.phase1_metrics", "default-off path imported diagnostics"
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    badge_remote.set_phase1_metrics(None)
    assert badge_remote.tag(bytes(32), b"vector") == hmac.new(bytes(32), b"vector", hashlib.sha256).hexdigest()[:32].encode()
    remote = EspNowRemote()

    class Radio:
        def send(self, data, peer):
            return data, peer

    remote._radio = Radio()
    assert remote._native_send(b"data", "peer") == (b"data", "peer")


class BufferedUART:
    def __init__(self, incoming=b""):
        self.incoming = bytearray(incoming)

    @property
    def in_waiting(self):
        return len(self.incoming)

    def read(self, size):
        result = bytes(self.incoming[:size])
        del self.incoming[:size]
        return result


def test_bm83_parser_errors_counted_without_changing_resync_or_returned_events():
    from bm83.bm83 import Bm83
    metrics = observer(Clock())
    valid = Bm83()._frame(0x59, b"\x01")
    invalid_checksum = valid[:-1] + bytes([valid[-1] ^ 1])
    incoming = b"\xaa\xff\xff\x00" + invalid_checksum + valid
    plain = Bm83(BufferedUART(incoming))
    measured = Bm83(BufferedUART(incoming), phase1_metrics=metrics)
    assert measured.poll() == plain.poll() == [(0x59, b"\x01")]
    events = metrics.snapshot()["events"]
    assert events["bm83_invalid_length"] == 1
    assert events["bm83_checksum_error"] == 1
    assert events["bm83_resync_discarded_bytes"] == 4 + len(invalid_checksum)
    assert measured._rx == plain._rx and measured._rx_head == plain._rx_head


def test_bm83_parser_overflow_preserves_original_trim_and_counts_lost_bytes():
    from bm83.bm83 import Bm83
    metrics = observer(Clock())
    plain = Bm83(BufferedUART())
    measured = Bm83(BufferedUART(), phase1_metrics=metrics)
    plain._rx = bytearray(4200)
    measured._rx = bytearray(4200)
    assert measured.poll() == plain.poll() == []
    events = metrics.snapshot()["events"]
    assert events["bm83_parser_overflow"] == 1
    assert events["bm83_parser_dropped_bytes"] == 4200 - 256
    assert measured._rx == plain._rx and measured._rx_head == plain._rx_head
    assert metrics.snapshot()["parsers"][0]["max_pretrim_active_bytes"] == 4200


def test_bm83_parser_observes_eight_event_limit_backlog_and_partial_frame():
    from bm83.bm83 import Bm83
    metrics = observer(Clock())
    valid = Bm83()._frame(0x59, b"\x01")
    uart = BufferedUART(valid * 10 + valid[:3])
    plain = Bm83(BufferedUART(bytes(uart.incoming)))
    measured = Bm83(uart, phase1_metrics=metrics)
    assert measured.poll() == plain.poll() == [(0x59, b"\x01")] * 8
    parser = metrics.snapshot()["parsers"][0]
    assert parser["max_pretrim_active_bytes"] == 10 * len(valid) + 3
    assert parser["latest_postparse_active_bytes"] == 2 * len(valid) + 3
    assert parser["max_returned_per_poll"] == 8
    assert parser["returned_items"] == 8
    assert parser["input_bytes"] == 10 * len(valid) + 3
    assert measured.poll() == plain.poll() == [(0x59, b"\x01")] * 2
    assert measured._rx[measured._rx_head:] == valid[:3]
    assert metrics.snapshot()["parsers"][0]["latest_postparse_active_bytes"] == 3
    uart.incoming.extend(valid[3:])
    assert measured.poll() == [(0x59, b"\x01")]
    parser = metrics.snapshot()["parsers"][0]
    assert parser["pretrim_samples"] == parser["postparse_samples"] == 3
    assert parser["input_bytes"] == 11 * len(valid)
    assert parser["returned_items"] == 11
    assert parser["latest_postparse_active_bytes"] == 0
    assert parser["max_postparse_active_bytes"] == 2 * len(valid) + 3


def test_nextion_parser_observes_partial_frame_without_token_or_payload_retention():
    from nextion.display import Nextion
    metrics = observer(Clock())
    uart = BufferedUART(b"\x66\x01\xff")
    panel = Nextion(uart, phase1_metrics=metrics)
    assert panel.read() == ([], False)
    parser = metrics.snapshot()["parsers"][1]
    assert parser["input_bytes"] == 3
    assert parser["latest_postparse_active_bytes"] == 3
    uart.incoming.extend(b"\xff\xff")
    assert panel.read() == ([], True)
    parser = metrics.snapshot()["parsers"][1]
    assert parser["max_pretrim_active_bytes"] == 5
    assert parser["input_bytes"] == 5
    assert parser["latest_postparse_active_bytes"] == 0
    assert parser["returned_items"] == 0  # A page response is not a control token.


def test_nextion_parser_overflow_preserves_original_trim_and_counts_lost_bytes():
    from nextion.display import Nextion, _RX_KEEP
    metrics = observer(Clock())
    plain = Nextion(BufferedUART(bytes(200)))
    measured = Nextion(BufferedUART(bytes(200)), phase1_metrics=metrics)
    plain._rx = bytearray(400)
    measured._rx = bytearray(400)
    plain._read_more()
    measured._read_more()
    assert measured._rx == plain._rx == bytes(_RX_KEEP)
    events = metrics.snapshot()["events"]
    assert events["nextion_parser_overflow"] == 1
    assert events["nextion_parser_dropped_bytes"] == 600 - _RX_KEEP
    assert metrics.snapshot()["parsers"][1]["max_pretrim_active_bytes"] == 600

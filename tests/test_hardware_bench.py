"""Host-only passive bench tests: no physical ports or filesystem writes."""

import importlib.util
import io
import json
from pathlib import Path
import queue
from types import SimpleNamespace

import pytest


SPEC = importlib.util.spec_from_file_location(
    "hardware_bench", Path(__file__).resolve().parents[1] / "tools" / "hardware_bench.py")
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


def device(port="COM6", serial_number="BENCH-UNIT-001", vid=0x303A, pid=0x7003):
    return {"port": port, "vid": vid, "pid": pid, "serial_number": serial_number,
            "description": "CircuitPython USB CDC", "hwid": "USB VID:PID=303A:7003"}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeSerial:
    """Only implements permitted serial operations; all TX would fail."""
    def __init__(self, clock, chunks, open_error=None, close_error=None):
        self.clock = clock
        self.chunks = iter(chunks)
        self.open_error = open_error
        self.close_error = close_error
        self.opened = False
        self.closed = False

    def open(self):
        assert self.port == "COM6"
        assert self.dtr is True and self.rts is False
        if self.open_error:
            raise self.open_error
        self.opened = True

    def read(self, size):
        assert self.opened
        assert size == 4096
        self.clock.now += 0.1
        chunk = next(self.chunks, b"")
        if isinstance(chunk, BaseException):
            raise chunk
        return chunk

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error

    def write(self, _):
        pytest.fail("capture must never transmit serial bytes")

    def send_break(self, *_):
        pytest.fail("capture must never send a break/reset")


def run_capture(chunks, duration=0.5, markers=None, open_error=None, close_error=None):
    clock = Clock()
    serial = FakeSerial(clock, chunks, open_error=open_error, close_error=close_error)
    created = []

    def factory(**kwargs):
        assert kwargs == {"port": None, "baudrate": 115200, "timeout": 0.2}
        created.append(serial)
        return serial

    logfile = io.StringIO()
    summary = bench.capture(device(), duration, factory, logfile, marker_queue=markers,
                            clock=clock, timestamp=lambda: "2026-10-04T00:00:00.000+00:00")
    assert created == [serial]
    assert serial.closed
    assert summary["serial_tx_bytes"] == 0
    assert summary["hardware_verdict"] == "NOT_ASSESSED"
    return summary, logfile.getvalue()


def test_inventory_keeps_stable_usb_identity():
    source = SimpleNamespace(**dict(device(), device="COM6"))
    assert bench.device_inventory([source]) == [device()]


def test_selection_never_falls_back_to_another_vidpid():
    other = device(vid=0x1A86, pid=0x7523)
    with pytest.raises(ValueError, match="No CircuitPython"):
        bench.select_device([other])
    with pytest.raises(ValueError, match="No CircuitPython"):
        bench.select_device([other], "BENCH-UNIT-001")


def test_selection_refuses_ambiguity_and_duplicate_identity():
    devices = [device(), device("COM7", "OTHER")]
    with pytest.raises(ValueError, match="--serial"):
        bench.select_device(devices)
    assert bench.select_device(devices, "BENCH-UNIT-001") == device()
    with pytest.raises(ValueError, match="--serial"):
        bench.select_device([device(), device("COM7")], "BENCH-UNIT-001")
    with pytest.raises(ValueError, match="No CircuitPython"):
        bench.select_device(devices, "MISSING")


def test_split_log_lines_and_error_evidence_are_preserved():
    data = [b"[BM83 RX] ali", b"ve: 0.1s\r\n[FATAL] Memory", b"Error\nTraceback (most recent call last):\n"]
    summary, logfile = run_capture(data)
    assert summary["rx_bytes"] == sum(map(len, data))
    assert summary["rx_lines"] == 3
    counts = summary["evidence_counts"]
    assert counts["heartbeat"] == counts["fatal"] == counts["memory_error"] == counts["traceback"] == 1
    assert "[BM83 RX] alive: 0.1s" in logfile
    assert "[FATAL] MemoryError" in logfile
    assert summary["runtime_version"] == summary["loaded_source_identity"] == "unknown"


def test_disconnect_keeps_unterminated_received_text_and_error():
    summary, logfile = run_capture([b"[FATAL] incomplete", OSError("USB disconnected")])
    assert summary["completion"] == "serial_disconnect_or_read_error"
    assert summary["evidence_counts"]["disconnect"] == 1
    assert summary["evidence_counts"]["io_error"] == 1
    assert summary["evidence_counts"]["fatal"] == 1
    assert "USB disconnected" in logfile
    assert "RX_PARTIAL [FATAL] incomplete" in logfile


def test_open_and_close_errors_are_logged_and_returned():
    summary, logfile = run_capture([], open_error=OSError("port busy"))
    assert summary["completion"] == "serial_open_or_capture_error"
    assert summary["evidence_counts"]["io_error"] == 1
    assert "port busy" in logfile
    summary, logfile = run_capture([], close_error=OSError("close failed"))
    assert summary["completion"] == "serial_close_error"
    assert "close failed" in logfile


def test_markers_only_go_to_host_log():
    markers = queue.Queue()
    bench.enqueue_stdin_markers(markers, io.StringIO("Volume up once\nPower off\n"))
    summary, logfile = run_capture([], markers=markers)
    assert [m["text"] for m in summary["markers"]] == ["Volume up once", "Power off"]
    assert "MARKER Volume up once" in logfile
    assert summary["rx_bytes"] == 0


def test_no_heartbeat_or_serial_text_never_becomes_crash_or_pass():
    summary, logfile = run_capture([])
    assert summary["completion"] == "duration_elapsed"
    assert sum(summary["evidence_counts"].values()) == 0
    assert "absence does not prove a crash" in " ".join(summary["limitations"])
    assert "NOT_ASSESSED" in logfile


def test_long_and_invalid_utf8_text_is_retained_as_fragments():
    summary, logfile = run_capture([b"x" * (bench.MAX_LINE_CHARS + 1) + b"\xff"])
    assert summary["rx_bytes"] == bench.MAX_LINE_CHARS + 2
    assert summary["rx_lines"] == 2
    assert "RX_PARTIAL" in logfile
    assert "x\\xff" in logfile


def test_interrupt_is_local_and_partial_text_survives():
    summary, logfile = run_capture([b"last output", KeyboardInterrupt()])
    assert summary["completion"] == "interrupted"
    assert "last output" in logfile
    assert "no control character sent to serial" in logfile


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf"), 86401])
def test_invalid_duration_never_opens_serial(duration):
    def forbidden_factory(**_):
        pytest.fail("invalid duration must not open a port")

    with pytest.raises(ValueError, match="duration"):
        bench.capture(device(), duration, forbidden_factory, io.StringIO())


def test_direct_capture_rejects_non_circuitpython_identity():
    def forbidden_factory(**_):
        pytest.fail("unexpected USB identity must not open a port")

    with pytest.raises(ValueError, match="No CircuitPython"):
        bench.capture(device(vid=0x1A86, pid=0x7523), 1, forbidden_factory, io.StringIO())


def test_unicode_osc_and_failing_host_echo_do_not_abort_capture():
    clock = Clock()
    text = "\x1b]0;\U0001f40d CircuitPython\x07[BM83 RX] alive: 0.1s\n"
    serial = FakeSerial(clock, [text.encode("utf-8")])
    log = io.StringIO()

    def broken_echo(line):
        raise UnicodeEncodeError("cp1252", line, 0, 1, "cannot encode emoji")

    summary = bench.capture(device(), 0.3, lambda **_: serial, log, clock=clock, echo=broken_echo)
    assert summary["completion"] == "duration_elapsed"
    assert summary["host_echo_errors"] > 0
    assert summary["evidence_counts"]["heartbeat"] == 1
    assert summary["evidence_counts"]["io_error"] == 0
    assert text.rstrip("\n") in log.getvalue()
    assert serial.closed


def test_terminal_escapes_stay_in_log_but_are_inert_in_host_echo():
    clock = Clock()
    # OSC 52 clipboard write, CSI clear-screen, 8-bit CSI, BEL, and a
    # mid-line carriage return that could overwrite the displayed line.
    text = ("\x1b]52;c;cHduZWQ=\x07\x1b[2J\x9b31m\x1b]0;\U0001f40d title\x1b\\"
            "[BM83 RX] alive\rspoof\x07\r\n")
    serial = FakeSerial(clock, [text.encode("utf-8")])
    log = io.StringIO()
    echoed = []
    summary = bench.capture(device(), 0.3, lambda **_: serial, log, clock=clock, echo=echoed.append)
    assert summary["completion"] == "duration_elapsed"
    assert summary["evidence_counts"]["heartbeat"] == 1
    # The evidence log keeps every received character unchanged.
    assert "RX " + text.rstrip("\n") + "\n" in log.getvalue()
    rx_echo = [line for line in echoed if " RX " in line]
    assert len(rx_echo) == 1
    for line in echoed:
        assert not any(ord(ch) < 0x20 and ch != "\t" or 0x7F <= ord(ch) <= 0x9F for ch in line)
    assert "\\x1b]52;c;cHduZWQ=\\x07\\x1b[2J\\x9b31m" in rx_echo[0]
    assert "\U0001f40d title" in rx_echo[0]
    assert rx_echo[0].endswith("[BM83 RX] alive\\x0dspoof\\x07")


def test_classifies_actual_firmware_diagnostic_messages():
    cases = {
        "[BM83 RX] SILENT for 5.0s | free=12000": {"heartbeat", "bm83_rx_silent"},
        "[BM83 RX] DEGRADED: max 3.00s in last 10s window": {"heartbeat", "bm83_rx_degraded"},
        "[BOOT] reset_reason: microcontroller.ResetReason.BROWNOUT": {"brownout"},
        "Brownout detector was triggered": {"brownout"},
        "[POWER] ON not confirmed - chip stayed silent.": {"power_on_unconfirmed"},
        "[BM83] write err: OSError('UART failed')": {"bm83_write_error"},
        "[REMOTE] ESP-NOW read error #1: OSError('radio hiccup') -> pausing 5s": {"remote_read_error"},
    }
    for line, expected in cases.items():
        assert set(bench.classify_line(line)) == expected


def test_bench_diagnostics_do_not_misclassify_other_subsystems_or_normal_boot():
    for line in (
        "[NX] write err: OSError('display failed')",
        "[BOOT] reset_reason: microcontroller.ResetReason.POWER_ON",
        "[REMOTE] BT_VOLUP_P seq=1 rssi=-46",
        "[POWER] ON confirmed in 1.10s",
    ):
        assert bench.classify_line(line) == []


def test_diagnostic_counts_remain_evidence_without_a_hardware_verdict():
    raw = (b"[BM83 RX] SILENT for 5.0s\n"
           b"[POWER] ON not confirmed - chip stayed silent.\n"
           b"[BM83] write error: UART failed\n"
           b"[REMOTE] ESP-NOW read error #2: radio hiccup\n")
    summary, logfile = run_capture([raw])
    for kind in ("bm83_rx_silent", "power_on_unconfirmed", "bm83_write_error", "remote_read_error"):
        assert summary["evidence_counts"][kind] == 1
    assert summary["completion"] == "duration_elapsed"
    assert summary["hardware_verdict"] == "NOT_ASSESSED"
    assert "[POWER] ON not confirmed" in logfile


@pytest.mark.parametrize("diagnostic,kind", [
    ("SILENT for 5.0s", "bm83_rx_silent"),
    ("DEGRADED: max 3.0s", "bm83_rx_degraded"),
])
def test_classifies_partial_osc_title_prefix_seen_in_live_capture(diagnostic, kind):
    prefix = "Wi-Fi: No IP | BLE:Ok | main.py | 10.3.1\x1b\\"
    raw = (prefix + "[BM83 RX] " + diagnostic + "\n").encode("utf-8")
    summary, logfile = run_capture([raw])
    assert summary["evidence_counts"][kind] == 1
    assert summary["evidence_counts"]["heartbeat"] == 1
    assert prefix in logfile


@pytest.mark.parametrize("failed_operation", ["write", "flush"])
def test_failed_host_log_closes_port_and_leaves_json_summary_available(failed_operation):
    class FailedLog:
        def __init__(self):
            self.writes = 0
            self.flushes = 0

        def write(self, _):
            self.writes += 1
            if failed_operation == "write" and self.writes > 1:
                raise OSError("host log disk full")

        def flush(self):
            self.flushes += 1
            if failed_operation == "flush" and self.flushes > 1:
                raise OSError("host log disk full")

    clock = Clock()
    serial = FakeSerial(clock, [b"complete line\n[FATAL] partial tail"])
    logfile = FailedLog()
    summary = bench.capture(device(), 1, lambda **_: serial, logfile, clock=clock)
    assert serial.closed
    assert summary["completion"] == "host_log_error"
    assert summary["host_log_errors"] == 1
    assert summary["host_log_error_details"][0]["operation"] == failed_operation
    assert "host log disk full" in summary["host_log_error_details"][0]["error"]
    assert summary["evidence_counts"]["disconnect"] == summary["evidence_counts"]["io_error"] == 0
    assert summary["evidence_counts"]["fatal"] == 1
    assert summary["elapsed_s"] < summary["requested_duration_s"]
    assert summary["hardware_verdict"] == "NOT_ASSESSED"
    assert logfile.writes == 2
    # The CLI's separate JSON sink remains usable even though text logging
    # failed; the returned summary is complete and JSON serializable.
    separate_summary_file = io.StringIO()
    json.dump(summary, separate_summary_file)
    assert json.loads(separate_summary_file.getvalue())["completion"] == "host_log_error"


def test_initial_host_log_failure_does_not_open_port():
    class FailedLog:
        def write(self, _):
            raise OSError("log unavailable")

        def flush(self):
            pytest.fail("do not flush after a failed write")

    def forbidden_factory(**_):
        pytest.fail("an initial log failure must not open the physical port")

    summary = bench.capture(device(), 1, forbidden_factory, FailedLog())
    assert summary["completion"] == "host_log_error"
    assert summary["host_log_errors"] == 1
    assert summary["rx_bytes"] == 0
    assert "ended_at_utc" in summary

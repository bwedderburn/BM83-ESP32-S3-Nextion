"""Host-only, passive evidence capture for the native CircuitPython USB console.

List devices with ``python tools/hardware_bench.py --list``. Capture with
``--serial <USB serial number> --duration 120 --markers``; lines entered on
stdin label user actions in the log and are never sent to the board.

Only VID:PID 303A:7003 is eligible. Serial parameters are fixed at 115200;
DTR is asserted to connect CircuitPython's USB CDC console and RTS is off.
These are terminal connection settings, not reset commands. No bytes,
control characters, baud-rate reset sequence, deployment, or flash are sent.
Logs establish observations, not a hardware PASS or source-version identity.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import queue
import re
import sys
import threading
import time
import uuid


TARGET_VID = 0x303A
TARGET_PID = 0x7003
BAUDRATE = 115200
READ_TIMEOUT_S = 0.2
MAX_LINE_CHARS = 16384
MAX_EVIDENCE_SAMPLES = 50
# C0 (except TAB), DEL and C1 controls: ESC/OSC/CSI, BEL, CR and 8-bit CSI.
_TERMINAL_CONTROLS = re.compile(r"[\x00-\x08\x0a-\x1f\x7f-\x9f]")


def inert_echo_text(text):
    """Escape terminal controls for the operator echo; logs keep raw text."""
    return _TERMINAL_CONTROLS.sub(lambda m: "\\x%02x" % ord(m.group()), text)


def utc_timestamp():
    """Return an explicitly UTC timestamp for the capture record."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def device_inventory(ports):
    """Convert pyserial descriptors into JSON-safe identity records."""
    return [
        {"port": p.device, "vid": p.vid, "pid": p.pid,
         "serial_number": p.serial_number, "description": p.description,
         "hwid": p.hwid}
        for p in ports
    ]


def select_device(devices, serial_number=None):
    """Fail closed unless exactly one permitted USB identity matches."""
    matches = [d for d in devices if d["vid"] == TARGET_VID and d["pid"] == TARGET_PID]
    if serial_number is not None:
        matches = [d for d in matches if d["serial_number"] == serial_number]
    if not matches:
        raise ValueError("No CircuitPython USB console (303A:7003) matches the requested identity; use --list.")
    if len(matches) != 1:
        raise ValueError("Multiple matching consoles; supply a unique USB serial number with --serial.")
    return dict(matches[0])


def classify_line(line):
    """Identify log evidence without interpreting it as a hardware verdict."""
    # CircuitPython can prepend an OSC terminal title (including Unicode).
    # Strip terminal controls only for classification; retain them in logs.
    line = re.sub(r"\x1b\](?:[^\x07\x1b]|\x1b(?!\\))*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]", "", line)
    kinds = []
    if re.search(r"\bFATAL\b", line, re.IGNORECASE):
        kinds.append("fatal")
    if "Traceback (most recent call last)" in line:
        kinds.append("traceback")
    if "MemoryError" in line:
        kinds.append("memory_error")
    # Captures can begin in the middle of an OSC title, leaving a title tail
    # before the tag. Recognize firmware tags after that decoration too.
    if "[BM83 RX]" in line or re.search(r"\b(?:heartbeat|alive)\b", line, re.IGNORECASE):
        kinds.append("heartbeat")
    if re.search(r"\[BM83 RX\]\s+SILENT\b", line):
        kinds.append("bm83_rx_silent")
    if re.search(r"\[BM83 RX\]\s+DEGRADED\b", line):
        kinds.append("bm83_rx_degraded")
    if (re.search(r"\breset[_ ]reason\b.*\bBROWNOUT\b", line, re.IGNORECASE)
            or "brownout detector was triggered" in line.lower()):
        kinds.append("brownout")
    if "[POWER] ON not confirmed" in line:
        kinds.append("power_on_unconfirmed")
    if re.search(r"\[BM83\]\s+write err(?:or)?\b", line, re.IGNORECASE):
        kinds.append("bm83_write_error")
    if "[REMOTE] ESP-NOW read error" in line:
        kinds.append("remote_read_error")
    return kinds


def capture(device, duration_s, serial_factory, log_file, marker_queue=None,
            clock=time.monotonic, timestamp=utc_timestamp, echo=None):
    """Capture bounded RX-only evidence using injected serial, file and clocks.

    Read/open/close failures are retained in both outputs. ``serial_factory``
    must follow pyserial's Serial(port=None, ...) interface. The returned
    dictionary remains evidence-only even when there are no error messages.
    """
    if not math.isfinite(duration_s) or not 0 < duration_s <= 86400:
        raise ValueError("duration must be finite and between 0 and 86400 seconds")
    # Enforce identity even for direct callers, not only CLI selection.
    select_device([device], device.get("serial_number"))
    start = clock()
    summary = {
        "schema_version": 1, "started_at_utc": timestamp(), "device": dict(device),
        "requested_duration_s": duration_s, "completion": "duration_elapsed",
        "hardware_verdict": "NOT_ASSESSED", "serial_tx_bytes": 0,
        "serial_settings": {"baudrate": BAUDRATE, "dtr": True, "rts": False},
        "runtime_version": "unknown", "loaded_source_identity": "unknown",
        "rx_bytes": 0, "rx_lines": 0, "markers": [], "host_echo_errors": 0,
        "host_log_errors": 0, "host_log_error_details": [],
        "evidence_counts": {k: 0 for k in (
            "fatal", "traceback", "memory_error", "heartbeat", "disconnect", "io_error",
            "bm83_rx_silent", "bm83_rx_degraded", "brownout", "power_on_unconfirmed",
            "bm83_write_error", "remote_read_error")},
        "evidence_samples": [],
        "limitations": [
            "Passive logs alone do not prove a hardware test passed.",
            "A heartbeat shows log output; its absence does not prove a crash.",
            "Running CircuitPython and loaded source identity are unverified by this capture.",
            "Invalid UTF-8 bytes are escaped in the text log; fragments are marked explicitly.",
            "DTR connects the native CircuitPython console; no serial bytes or reset commands are sent.",
        ],
    }
    handle = None
    pending = bytearray()
    log_failed = False

    def record(kind, text):
        nonlocal log_failed
        event = {"at_utc": timestamp(), "elapsed_s": round(clock() - start, 3), "text": text}
        rendered = "[%s +%.3fs] %s %s\n" % (event["at_utc"], event["elapsed_s"], kind, text)
        if not log_failed:
            operation = "write"
            try:
                log_file.write(rendered)
                operation = "flush"
                log_file.flush()
            except Exception as exc:
                # Stop capture and retain this host failure in the separate
                # JSON summary. Never report it as a serial disconnect or
                # recursively attempt to log through the failed sink.
                log_failed = True
                summary["completion"] = "host_log_error"
                summary["host_log_errors"] += 1
                summary["host_log_error_details"].append(dict(
                    event, operation=operation, error="%s: %s" % (type(exc).__name__, exc)))
        if echo is not None:
            try:
                # Device text must not drive the operator's terminal (OSC 52
                # clipboard, CSI redraws, mid-line CR overwrite). Only the
                # CRLF terminator is dropped; the evidence log stays raw.
                echo(inert_echo_text(rendered.rstrip("\r\n")))
            except Exception:
                # A cp1252 console or closed stdout pipe must not stop the
                # UTF-8 log or get misclassified as a device disconnect.
                summary["host_echo_errors"] += 1
        return event

    def evidence(kind, event):
        summary["evidence_counts"][kind] += 1
        if len(summary["evidence_samples"]) < MAX_EVIDENCE_SAMPLES:
            summary["evidence_samples"].append(dict(event, kind=kind))

    def rx_line(raw, partial=False):
        text = raw.decode("utf-8", errors="backslashreplace")
        event = record("RX_PARTIAL" if partial else "RX", text)
        summary["rx_lines"] += 1
        for kind in classify_line(text):
            evidence(kind, event)

    def drain_markers():
        if marker_queue is None:
            return
        # Bound marker processing so a producer cannot starve serial reads.
        for _ in range(100):
            try:
                label = marker_queue.get_nowait()
            except queue.Empty:
                break
            event = record("MARKER", str(label).rstrip("\r\n"))
            summary["markers"].append(event)

    record("CAPTURE", "Passive console capture; hardware verdict NOT_ASSESSED")
    try:
        if log_failed:
            # If the initial log write failed, leave the physical port alone.
            return summary
        handle = serial_factory(port=None, baudrate=BAUDRATE, timeout=READ_TIMEOUT_S)
        # Configure signals before open; never invoke reset_input_buffer(),
        # write(), send_break(), or change baud rate while connected.
        handle.dtr = True
        handle.rts = False
        handle.port = device["port"]
        handle.open()
        while not log_failed and clock() - start < duration_s:
            drain_markers()
            if log_failed:
                break
            try:
                chunk = handle.read(4096)
            except (OSError, IOError) as exc:
                summary["completion"] = "serial_disconnect_or_read_error"
                event = record("IO_ERROR", "%s: %s" % (type(exc).__name__, exc))
                evidence("disconnect", event)
                evidence("io_error", event)
                break
            if not chunk:
                continue
            summary["rx_bytes"] += len(chunk)
            pending.extend(chunk)
            while b"\n" in pending:
                newline = pending.index(10)
                raw = bytes(pending[:newline])
                del pending[:newline + 1]
                rx_line(raw)
            while len(pending) >= MAX_LINE_CHARS:
                raw = bytes(pending[:MAX_LINE_CHARS])
                del pending[:MAX_LINE_CHARS]
                rx_line(raw, partial=True)
    except KeyboardInterrupt:
        summary["completion"] = "interrupted"
        record("CAPTURE", "Interrupted by host; no control character sent to serial")
    except Exception as exc:
        summary["completion"] = "serial_open_or_capture_error"
        event = record("IO_ERROR", "%s: %s" % (type(exc).__name__, exc))
        evidence("io_error", event)
    finally:
        try:
            if pending:
                rx_line(bytes(pending), partial=True)
            drain_markers()
        finally:
            # Release the port independently of all text/marker cleanup.
            if handle is not None:
                try:
                    handle.close()
                except Exception as exc:
                    event = record("IO_ERROR", "Close failed: %s: %s" % (type(exc).__name__, exc))
                    evidence("io_error", event)
                    if summary["completion"] == "duration_elapsed":
                        summary["completion"] = "serial_close_error"
        summary["ended_at_utc"] = timestamp()
        summary["elapsed_s"] = round(clock() - start, 3)
        record("CAPTURE", "Finished: %s; hardware verdict NOT_ASSESSED" % summary["completion"])
    return summary


def enqueue_stdin_markers(marker_queue, stream):
    """Read local action labels only; this function has no serial handle."""
    for line in stream:
        marker_queue.put(line.rstrip("\r\n"))


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="print all USB serial identities; do not open any port")
    parser.add_argument("--serial", help="exact USB serial number; required if multiple 303A:7003 consoles match")
    parser.add_argument("--duration", type=float, default=120, help="bounded capture seconds (default 120, maximum 86400)")
    parser.add_argument("--markers", action="store_true", help="label user actions using stdin lines (never sent to serial)")
    parser.add_argument("--output-prefix", type=Path,
                        help="path prefix for new .log and .json files; existing files are refused")
    args = parser.parse_args(argv)
    try:
        import serial
        from serial.tools import list_ports
    except ImportError:
        parser.exit(2, "pyserial is required for inventory/capture: python -m pip install pyserial\n")
    devices = device_inventory(list_ports.comports())
    if args.list:
        print(json.dumps(devices, indent=2), flush=True)
        return 0
    if not math.isfinite(args.duration) or not 0 < args.duration <= 86400:
        parser.error("--duration must be finite and between 0 and 86400 seconds")
    try:
        device = select_device(devices, args.serial)
    except ValueError as exc:
        parser.error(str(exc))
    prefix = args.output_prefix or Path("build") / "hardware" / (
        "console-%s-%s" % (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), uuid.uuid4().hex[:8]))
    log_path = Path(str(prefix) + ".log")
    summary_path = Path(str(prefix) + ".json")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists() or summary_path.exists():
        parser.error("output already exists; choose a new --output-prefix")
    markers = queue.Queue() if args.markers else None
    if markers is not None:
        threading.Thread(target=enqueue_stdin_markers, args=(markers, sys.stdin), daemon=True).start()
        print("Enter action labels here; stdin is never transmitted to the board.", flush=True)
    print("Capturing %s (USB serial %s) for %.1fs" % (device["port"], device["serial_number"], args.duration), flush=True)
    with log_path.open("x", encoding="utf-8", newline="") as logfile, summary_path.open("x", encoding="utf-8") as summaryfile:
        summary = capture(device, args.duration, serial.Serial, logfile, marker_queue=markers,
                          echo=lambda line: print(line, flush=True))
        summary["log_path"] = str(log_path.resolve())
        json.dump(summary, summaryfile, indent=2)
        summaryfile.write("\n")
    print("Evidence log: %s\nSummary: %s\nHardware verdict: NOT_ASSESSED" % (
        log_path.resolve(), summary_path.resolve()), flush=True)
    return 0 if summary["completion"] == "duration_elapsed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

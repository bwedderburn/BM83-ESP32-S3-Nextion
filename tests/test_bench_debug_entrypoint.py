"""Exercise the optional bench entrypoint without a device or hardware imports."""
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace

import pytest


ENTRYPOINT = Path(__file__).resolve().parents[1] / "tools" / "bench_debug_entrypoint.py"


class StopFatalHold(BaseException):
    """End the infinite fatal hold in a host test without entering its handler."""


@pytest.fixture
def bench_modules(monkeypatch):
    """Replace every device-facing import with an isolated host module."""
    events = []
    common = ModuleType("utils.common")
    common.DEBUG = False
    utils = ModuleType("utils")
    utils.common = common
    supervisor = ModuleType("supervisor")
    supervisor.runtime = SimpleNamespace(autoreload=True)
    supervisor.ticks_ms = lambda: 12345
    firmware = ModuleType("main")

    def enter_firmware():
        assert common.DEBUG is True
        assert supervisor.runtime.autoreload is False
        assert events == []
        events.append("main")

    firmware.main = enter_firmware
    clock = ModuleType("time")

    def sleep(seconds):
        events.append(("sleep", seconds))
        raise StopFatalHold()

    clock.sleep = sleep
    traceback = ModuleType("traceback")
    traceback.print_exception = lambda error: events.append(("traceback", error))
    for name, module in (
        ("utils", utils),
        ("utils.common", common),
        ("supervisor", supervisor),
        ("main", firmware),
        ("time", clock),
        ("traceback", traceback),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    return SimpleNamespace(
        events=events, common=common, firmware=firmware, traceback=traceback, supervisor=supervisor,
    )


def test_debug_entrypoint_runs_current_main_once(bench_modules, capsys):
    namespace = runpy.run_path(str(ENTRYPOINT), run_name="__main__")

    assert bench_modules.events == ["main"]
    assert bench_modules.supervisor.runtime.autoreload is False
    assert bench_modules.common.dprint is namespace["_bench_dprint"]
    output = capsys.readouterr().out
    assert "[BENCH] Debug capture" in output
    assert "not a performance verdict" in output
    assert "restore entrypoint and reload" in output


def test_importing_wrapper_does_not_start_firmware(bench_modules):
    runpy.run_path(str(ENTRYPOINT), run_name="bench_debug_entrypoint")

    assert bench_modules.events == []
    assert bench_modules.common.DEBUG is False
    assert bench_modules.supervisor.runtime.autoreload is True


def test_debug_prefix_uses_device_ticks_and_preserves_gate(bench_modules, capsys):
    namespace = runpy.run_path(str(ENTRYPOINT), run_name="bench_debug_entrypoint")
    ticks_called = []

    def device_ticks():
        ticks_called.append(True)
        return (1 << 29) - 1

    bench_modules.supervisor.ticks_ms = device_ticks
    debug_print = namespace["_bench_dprint"]
    debug_print("[TX]", b"example")
    assert capsys.readouterr().out == ""
    assert ticks_called == []

    bench_modules.common.DEBUG = True
    debug_print("[TX]", b"example")
    assert capsys.readouterr().out == "[BENCH ticks_ms=536870911] [TX] b'example'\n"
    assert ticks_called == [True]


def test_fatal_runtime_reports_error_and_holds(bench_modules, capsys):
    error = RuntimeError("bench runtime failure")

    def fail():
        bench_modules.events.append("main")
        raise error

    bench_modules.firmware.main = fail
    with pytest.raises(StopFatalHold):
        runpy.run_path(str(ENTRYPOINT), run_name="__main__")

    assert bench_modules.events == [
        "main", ("traceback", error), ("sleep", 1),
    ]
    assert "[FATAL] bench runtime failure" in capsys.readouterr().out


def test_traceback_failure_retains_fatal_hold(bench_modules, capsys):
    def fail():
        raise RuntimeError("bench runtime failure")

    def broken_traceback(error):
        raise RuntimeError("traceback unavailable")

    bench_modules.firmware.main = fail
    bench_modules.traceback.print_exception = broken_traceback
    with pytest.raises(StopFatalHold):
        runpy.run_path(str(ENTRYPOINT), run_name="__main__")

    assert bench_modules.events == [("sleep", 1)]
    assert "[FATAL] bench runtime failure" in capsys.readouterr().out


def test_import_failure_stays_outside_runtime_handler(bench_modules, monkeypatch):
    # Production main.py imports its hardware modules before the fatal guard.
    monkeypatch.setitem(sys.modules, "main", None)
    with pytest.raises(ModuleNotFoundError):
        runpy.run_path(str(ENTRYPOINT), run_name="__main__")

    assert bench_modules.events == []
    assert bench_modules.supervisor.runtime.autoreload is False

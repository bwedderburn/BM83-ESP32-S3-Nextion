"""Bond-preserving BLE release under asynchronous native callbacks."""
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from blehid import ble as module
from utils.ticks import TICKS_PERIOD


class Runtime:
    def __init__(self, events):
        self.events = events
        self.enabled = True
        self.failure = False

    @property
    def ble_workflow(self):
        return self.enabled

    @ble_workflow.setter
    def ble_workflow(self, value):
        self.events.append("workflow-off")
        if self.failure:
            raise RuntimeError("workflow unavailable")
        self.enabled = value


class Radio:
    def __init__(self, runtime, events):
        self.runtime = runtime
        self.events = events
        self.links = []
        self.hid_advertising = False
        self.stop_failure = False
        self.observe_failure = False
        self.empty_connections = False
        self.name = "Volume remote"
        self.erase_bonding = lambda: pytest.fail("handoff erased bonds")

    @property
    def connected(self):
        if self.observe_failure:
            raise RuntimeError("link observation unavailable")
        return any(link.connected for link in self.links)

    @property
    def connections(self):
        if self.empty_connections:
            return ()
        return tuple(link for link in self.links if link.connected)

    @property
    def advertising(self):
        # Native workflow advertising is independent of the application's.
        return self.hid_advertising or (self.runtime.enabled and not self.connected)

    def stop_advertising(self):
        self.events.append("stop-adv")
        if self.stop_failure:
            raise RuntimeError("stop failed")
        self.hid_advertising = False

    def start_advertising(self, advertisement):
        self.events.append("start-adv")
        self.hid_advertising = True


class Connection:
    def __init__(self, radio, *, immediate=False, failure=False):
        self.connected = True
        self.paired = True
        self.immediate = immediate
        self.failure = failure
        self.calls = 0
        self.radio = radio
        radio.links.append(self)

    def disconnect(self):
        self.calls += 1
        self.radio.events.append("disconnect")
        if self.failure:
            raise RuntimeError("termination rejected")
        if self.immediate:
            self.connected = False

    def pair(self):
        pytest.fail("handoff initiated pairing")


@pytest.fixture
def ready(monkeypatch):
    events = []
    runtime = Runtime(events)
    monkeypatch.setitem(sys.modules, "supervisor", SimpleNamespace(runtime=runtime))
    now = [0]
    monkeypatch.setattr(module, "ticks_ms", lambda: now[0])
    hid = module.BleHid(True, "Volume remote")
    radio = Radio(runtime, events)
    hid._ble = radio
    hid._adv = object()
    hid._ready = True
    hid._cc = SimpleNamespace(send=lambda code: events.append(("send", code)))
    hid._CCC = SimpleNamespace(VOLUME_INCREMENT=1, VOLUME_DECREMENT=2, MUTE=3)
    monkeypatch.setattr(module, "_write_ble_counter", lambda count: pytest.fail("name counter written"))
    return hid, radio, runtime, now, events


def settle(hid, now):
    hid.tick()
    now[0] = module.ticks_add(now[0], module._BLE_STABILIZE_MS)
    hid.tick()


def test_pause_callback_is_only_intent_and_stops_sends_immediately(ready):
    hid, radio, _, _, events = ready
    link = Connection(radio)
    assert hid.request_pause()
    hid.volume(True)
    hid.mute()
    assert events == []
    assert link.calls == 0
    assert hid.snapshot_status()["mode"] == module.MODE_PAUSING


def test_workflow_and_advertising_stop_before_single_native_termination(ready):
    hid, radio, runtime, now, events = ready
    radio.hid_advertising = True
    link = Connection(radio)
    settle(hid, now)
    # No pause intent means normal connection handling never terminates it.
    assert link.calls == 0
    events.clear()
    assert hid.request_pause()
    settle(hid, now)
    assert events == ["workflow-off", "stop-adv", "disconnect"]
    assert not runtime.enabled
    assert link.calls == 1
    for _ in range(10):
        now[0] += 5
        hid.tick()
    assert link.calls == 1
    assert hid.snapshot_status()["connected"]
    assert hid.snapshot_status()["mode"] == module.MODE_PAUSING
    link.connected = False
    hid.tick()
    assert hid.snapshot_status()["mode"] == module.MODE_PAUSED
    assert not radio.advertising


def test_pause_without_connection_suppresses_workflow_and_periodic_kicks(ready):
    hid, radio, _, now, events = ready
    assert radio.advertising  # maintenance workflow would reconnect a host
    hid.request_pause()
    settle(hid, now)
    assert hid.snapshot_status()["mode"] == module.MODE_PAUSED
    events.clear()
    now[0] += 120000
    for _ in range(5):
        hid.tick()
        hid._start_adv(force=True)
    assert events == []
    assert not radio.advertising


def test_idempotent_pause_does_not_extend_timeout_or_retry_connection(ready):
    hid, radio, _, now, _ = ready
    link = Connection(radio)
    hid.request_pause()
    settle(hid, now)
    deadline = hid._pause_deadline
    assert hid.request_pause()
    assert hid._pause_deadline == deadline
    now[0] = deadline
    hid.tick()
    assert hid.snapshot_status()["mode"] == module.MODE_ERROR
    assert hid.snapshot_status()["error"] == module.ERROR_TIMEOUT
    assert hid.snapshot_status()["connected"]
    for _ in range(4):
        assert not hid.request_pause()
        hid.tick()
    assert link.calls == 1


def test_multiple_connections_terminate_at_most_one_per_tick(ready):
    hid, radio, _, now, _ = ready
    links = [Connection(radio, immediate=True) for _ in range(3)]
    hid.request_pause()
    settle(hid, now)
    assert [link.calls for link in links] == [1, 0, 0]
    hid.tick()
    assert [link.calls for link in links] == [1, 1, 0]
    hid.tick()
    assert [link.calls for link in links] == [1, 1, 1]
    hid.tick()
    assert hid.snapshot_status()["mode"] == module.MODE_PAUSED


def test_late_callback_never_publishes_paused_while_connected(ready):
    hid, radio, _, now, _ = ready
    hid.request_pause()
    settle(hid, now)
    assert hid.snapshot_status()["mode"] == module.MODE_PAUSED
    late = Connection(radio)
    assert hid.snapshot_status()["mode"] == module.MODE_PAUSING
    settle(hid, now)
    assert late.calls == 1
    late.connected = False
    hid.tick()
    assert hid.snapshot_status()["mode"] == module.MODE_PAUSED


def test_enable_cancels_unserviced_pause_without_stale_disconnect(ready):
    hid, radio, _, _, events = ready
    link = Connection(radio)
    hid.request_pause()
    assert hid.request_enable()
    assert events == []
    hid.tick()
    assert link.calls == 0
    assert hid.snapshot_status()["intent_enabled"]
    assert hid.snapshot_status()["mode"] == module.MODE_ENABLED
    hid.volume(True)
    assert ("send", 1) in events


def test_enable_during_native_termination_allows_later_advertising(ready):
    hid, radio, _, now, events = ready
    link = Connection(radio)
    hid.request_pause()
    settle(hid, now)
    hid.request_enable()
    hid.tick()
    link.connected = False
    events.clear()
    hid.tick()
    assert "start-adv" in events
    assert link.calls == 1
    assert hid.snapshot_status()["mode"] == module.MODE_ENABLED


@pytest.mark.parametrize("enable_before_callback", [False, True])
def test_intentional_early_disconnect_does_not_suggest_forgetting_bonds(
        ready, monkeypatch, capsys, enable_before_callback):
    hid, radio, _, now, _ = ready
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0] / 1000)
    link = Connection(radio)
    hid.tick()
    # The link is paired, but the passive observer has not run yet.
    assert not hid._ever_paired_this_conn
    hid.request_pause()
    settle(hid, now)
    assert link.calls == 1
    if enable_before_callback:
        assert hid.request_enable()
    link.connected = False
    now[0] += 20
    hid.tick()
    output = capsys.readouterr().out
    assert "Disconnected" in output
    assert "stale bond" not in output
    assert "Forget Device" not in output
    assert "EBIND" not in output
    assert not hid._erase_pending
    assert hid._erase_stage == module._ERASE_IDLE


def test_new_unrequested_fast_disconnect_still_reports_stale_bond(
        ready, monkeypatch, capsys):
    hid, radio, _, now, _ = ready
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0] / 1000)
    previous = Connection(radio)
    hid.tick()
    hid.request_pause()
    settle(hid, now)
    previous.connected = False
    hid.tick()
    hid.request_enable()
    hid.tick()
    # A later host failing to encrypt is a separate connection, even while
    # the previous intentional release would still be inside its time bound.
    fresh = Connection(radio)
    fresh.paired = False
    hid.tick()
    capsys.readouterr()
    now[0] += 20
    fresh.connected = False
    hid.tick()
    output = capsys.readouterr().out
    assert "likely stale bond" in output
    assert "Forget Device" in output
    assert not hid._erase_pending
    assert hid._erase_stage == module._ERASE_IDLE


def test_failed_termination_does_not_hide_unrequested_disconnect(
        ready, monkeypatch, capsys):
    hid, radio, _, now, _ = ready
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0] / 1000)
    link = Connection(radio, failure=True)
    hid.tick()
    hid.request_pause()
    settle(hid, now)
    assert hid.snapshot_status()["error"] == module.ERROR_DISCONNECT
    link.connected = False
    hid.tick()
    assert "likely stale bond" in capsys.readouterr().out
    assert not hid._erase_pending


def test_intentional_disconnect_marker_survives_tick_wrap(ready, monkeypatch, capsys):
    hid, radio, _, now, _ = ready
    # Keep the independent diagnostics clock near boot while ms ticks wrap.
    monkeypatch.setattr(module.time, "monotonic", lambda: 0.5)
    link = Connection(radio)
    hid.tick()
    now[0] = TICKS_PERIOD - 75
    hid.request_pause()
    settle(hid, now)
    assert link.calls == 1
    now[0] = 5
    link.connected = False
    hid.tick()
    assert "stale bond" not in capsys.readouterr().out


def test_resume_preserves_name_counter_and_existing_paired_link(ready):
    hid, radio, _, now, events = ready
    hid._memory_counter = 7
    hid.name = radio.name = "Volume remote_7"
    old = Connection(radio, immediate=True)
    hid.request_pause()
    settle(hid, now)
    hid.tick()
    assert old.paired
    hid.request_enable()
    assert "start-adv" not in events
    hid.tick()
    assert radio.advertising
    assert radio.name == hid.name == "Volume remote_7"
    assert hid._memory_counter == 7
    assert old.paired


@pytest.mark.parametrize("failure,expected", [
    ("stop", module.ERROR_STOP_ADV),
    ("workflow", module.ERROR_WORKFLOW),
    ("disconnect", module.ERROR_DISCONNECT),
    ("observe", module.ERROR_OBSERVATION),
])
def test_failures_are_observed_once_without_reset_or_retry(ready, failure, expected):
    hid, radio, runtime, now, events = ready
    link = Connection(radio, failure=failure == "disconnect")
    radio.hid_advertising = True
    hid.request_pause()
    radio.stop_failure = failure == "stop"
    runtime.failure = failure == "workflow"
    radio.observe_failure = failure == "observe"
    settle(hid, now)
    assert hid.snapshot_status()["mode"] == module.MODE_ERROR
    assert hid.snapshot_status()["error"] == expected
    count = len(events)
    for _ in range(5):
        hid.tick()
    assert len(events) == count
    assert link.calls <= 1


def test_empty_native_connection_tuple_does_not_fake_disconnect(ready):
    hid, radio, _, now, _ = ready
    link = Connection(radio)
    radio.empty_connections = True
    hid.request_pause()
    settle(hid, now)
    assert link.calls == 0
    assert hid.snapshot_status()["mode"] == module.MODE_PAUSING
    radio.empty_connections = False
    hid.tick()
    assert link.calls == 1
    assert hid.snapshot_status()["mode"] == module.MODE_PAUSING


def test_pause_cancels_unstarted_erase_and_never_changes_counter(ready):
    hid, radio, _, now, _ = ready
    Connection(radio, immediate=True)
    hid._erase_pending = True
    hid.request_pause()
    assert not hid._erase_pending
    settle(hid, now)
    hid.tick()
    assert hid._erase_stage == module._ERASE_IDLE
    assert hid._memory_counter == 0


def test_pause_rejected_during_explicit_erase(ready):
    hid, _, _, _, events = ready
    hid._erase_stage = module._ERASE_WIPE
    assert not hid.request_pause()
    assert hid.snapshot_status()["error"] == module.ERROR_BUSY
    assert hid.snapshot_status()["intent_enabled"]
    assert events == []


def test_enable_rejected_during_explicit_erase_without_changing_intent(ready):
    hid, _, _, _, events = ready
    hid._intent_enabled = False
    hid._erase_stage = module._ERASE_WIPE
    assert not hid.request_enable()
    assert hid.snapshot_status()["mode"] == module.MODE_ERROR
    assert hid.snapshot_status()["error"] == module.ERROR_BUSY
    assert not hid.snapshot_status()["intent_enabled"]
    assert events == []


def test_pause_deadline_and_settle_survive_tick_wrap(ready):
    hid, radio, _, now, _ = ready
    link = Connection(radio)
    now[0] = TICKS_PERIOD - 25
    hid.request_pause()
    settle(hid, now)
    assert link.calls == 1
    now[0] = hid._pause_deadline
    hid.tick()
    assert hid.snapshot_status()["error"] == module.ERROR_TIMEOUT


@pytest.mark.parametrize("enabled", [False, True])
def test_not_ready_status_cannot_claim_paused(enabled):
    hid = module.BleHid(enabled, "Volume remote")
    assert not hid.request_enable()
    assert not hid.request_pause()
    assert not hid.request_enable()
    status = hid.snapshot_status()
    assert not status["ready"]
    assert status["mode"] == module.MODE_ERROR
    assert status["error"] == module.ERROR_NOT_READY


def test_unsupported_workflow_control_does_not_claim_pause(ready, monkeypatch):
    hid, _, _, _, _ = ready
    monkeypatch.setitem(sys.modules, "supervisor", SimpleNamespace(runtime=object()))
    assert hid.request_pause()
    hid.tick()
    assert hid.snapshot_status()["mode"] == module.MODE_ERROR
    assert hid.snapshot_status()["error"] == module.ERROR_WORKFLOW


def test_boot_disables_workflow_before_application_start(monkeypatch):
    events = []
    runtime = Runtime(events)
    monkeypatch.setitem(sys.modules, "supervisor", SimpleNamespace(runtime=runtime))
    path = Path(__file__).parents[1] / "firmware/circuitpython/boot.py"
    runpy.run_path(str(path))
    assert events == ["workflow-off"]
    assert not runtime.enabled


def test_boot_capability_failure_does_not_abort_startup(monkeypatch, capsys):
    runtime = Runtime([])
    runtime.failure = True
    monkeypatch.setitem(sys.modules, "supervisor", SimpleNamespace(runtime=runtime))
    path = Path(__file__).parents[1] / "firmware/circuitpython/boot.py"
    runpy.run_path(str(path))
    assert "workflow control unavailable" in capsys.readouterr().out

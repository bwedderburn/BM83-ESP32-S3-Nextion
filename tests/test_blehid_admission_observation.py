"""Inert bounded admission emitter tests: no BLE, transport or target access."""
import json
from types import SimpleNamespace

import pytest

from blehid.admission_observation import AdmissionObserver, FIELDS, TAG, checked_cache, install_after_tick
from blehid.host_policy import DIAG_UINT_FIELDS, DIAG_INT_FIELDS


def counters(**updates):
    values = dict.fromkeys(FIELDS, 0)
    values.update(version=1, **updates)
    return values


def decode(lines):
    return [json.loads(line[len(TAG):]) for line in lines]


def test_fixed_cadence_native_counters_preserve_fast_events_without_native_calls():
    now, lines = [0.0], []
    class CachedOwner:
        diagnostics = counters()
        @property
        def adapter(self):
            raise AssertionError("Emitter must not access native adapter")
        def snapshot(self):
            raise AssertionError("Emitter must not take another policy snapshot")
    owner = CachedOwner()
    observer = AdmissionObserver(lambda: now[0], emit=lines.append)
    for step in range(51):
        now[0] = step/10
        owner.diagnostics = counters(connect_events=step, refused_saved_identity=step//2, last_refusal_reason=8)
        observer.observe(owner)
    rows = decode(lines)
    assert len(rows) == 2 and rows[-1]["observer_elapsed_ms"] == 5000
    assert rows[-1]["diagnostics"]["connect_events"] == 50
    assert rows[-1]["diagnostics"]["refused_saved_identity"] == 25
    assert rows[-1]["diagnostics"]["last_refusal_reason"] == 8
    assert set(rows[-1]["diagnostics"]) == set(FIELDS) | {"version"}
    assert len(DIAG_UINT_FIELDS) == 30 and len(DIAG_INT_FIELDS) == 3


def test_exact_scalar_contract_rejects_old_cache_wrong_types_and_private_fields():
    assert checked_cache(None) is None
    assert checked_cache(counters(last_stop_result=-123)) is not None
    for key in FIELDS:
        value = counters()
        value[key] = True
        assert checked_cache(value) is None
    for patch in (dict(version=2), dict(irk="PRIVATE-MARKER"), dict(address="PRIVATE-MARKER"),
                  dict(connect_events=-1), dict(last_connect_status=0x80000000)):
        value = counters();value.update(patch)
        assert checked_cache(value) is None
    now, lines = [0], []
    observer = AdmissionObserver(lambda: now[0], emit=lines.append)
    observer.observe(SimpleNamespace(diagnostics=dict(counters(), alias="PRIVATE-MARKER")))
    assert "PRIVATE-MARKER" not in "".join(lines)
    row = decode(lines)[0]
    assert row["kind"] == "admission_unavailable" and row["diagnostics"] is None


def test_six_hundred_seconds_and_small_record_budget_reserve_stop_record():
    now, lines = [0], []
    observer = AdmissionObserver(lambda: now[0], emit=lines.append)
    owner = SimpleNamespace(diagnostics=counters())
    for value in range(601):
        now[0] = value;observer.observe(owner)
    assert len(lines) == 121 and observer.finished is True
    assert decode(lines)[-1]["kind"] == "admission_observer_stopped"
    assert decode(lines)[-1]["observer_elapsed_ms"] == 600000
    now[0] = 700;observer.observe(owner)
    assert len(lines) == 121
    now[0] = 0;small = AdmissionObserver(lambda: now[0], emit=lines.append, max_records=2)
    small.observe(owner);now[0] = 599;small.observe(owner);now[0] = 600;small.observe(owner)
    assert small.records == 2 and small.finished is True


def test_output_and_clock_failure_are_bounded_and_never_raise_into_owner():
    now = [0.0]
    def unavailable():
        raise OSError("PRIVATE-MARKER")
    observer = AdmissionObserver(lambda: now[0], output_ready=unavailable)
    owner = SimpleNamespace(diagnostics=counters())
    for value in (0, 0.1, 5, 600, 700):
        now[0] = value;observer.observe(owner)
    assert observer.finished and observer.records == 0 and observer.output_ready_errors == 3
    emitted = []
    def failed(line):
        emitted.append(line)
        raise OSError("PRIVATE-MARKER")
    now[0] = 0;observer = AdmissionObserver(lambda: now[0], emit=failed, max_records=2)
    observer.observe(owner);now[0] = 600;observer.observe(owner)
    assert observer.records == observer.emit_errors == 2 and len(emitted) == 2
    assert "PRIVATE-MARKER" not in "".join(emitted)
    lines = [];now[0] = 0;observer = AdmissionObserver(lambda: now[0], emit=lines.append)
    observer.observe(owner);now[0] = -1;observer.observe(owner)
    assert observer.finished and decode(lines)[-1]["clock_valid"] is False
    for value in (0, 601, float("nan"), True):
        with pytest.raises(ValueError):
            AdmissionObserver(lambda: 0, duration_s=value)


def test_composed_tick_order_return_exception_and_restoration():
    events = []
    sentinel = object()
    class Owner:
        def tick(self):
            events.append("original-and-state-observer")
            return sentinel
    original = Owner.tick
    class Probe:
        def observe(self, owner):
            events.append("cached-admission-observer")
    restore = install_after_tick(Owner, Probe())
    assert Owner().tick() is sentinel
    assert events == ["original-and-state-observer", "cached-admission-observer"]
    with pytest.raises(ValueError):
        install_after_tick(Owner, Probe())
    restore()
    assert Owner.tick is original and not hasattr(Owner, "_admission_observer_installed")
    class BrokenOwner:
        def tick(self):
            raise RuntimeError("original policy error")
    restore = install_after_tick(BrokenOwner, Probe())
    try:
        with pytest.raises(RuntimeError, match="original policy error"):
            BrokenOwner().tick()
    finally:
        restore()

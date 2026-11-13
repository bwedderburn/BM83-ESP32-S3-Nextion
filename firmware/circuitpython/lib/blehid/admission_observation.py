"""Explicit bounded scalar-only admission diagnostics; no radio or policy calls.

Normal firmware does not install this probe. The temporary diagnostic entrypoint
wraps the already installed state observer, so this reads only the owner's cache
after its normal tick. Native counters retain fast events between these records.
"""
import json
from .host_policy import DIAG_UINT_FIELDS, DIAG_INT_FIELDS, u32

TAG = "[HOST_ADMISSION] "
FIELDS = DIAG_UINT_FIELDS + DIAG_INT_FIELDS
MAX_RECORD_BYTES = 4096
PERIOD_S = 5


def checked_cache(value):
    """Copy only version1's exact33 numeric scalars, never native/private objects."""
    if (len(DIAG_UINT_FIELDS) != 30 or len(DIAG_INT_FIELDS) != 3
            or type(value) is not dict or set(value) != set(FIELDS) | {"version"}
            or type(value.get("version")) is not int or value["version"] != 1
            or any(not u32(value[key]) for key in DIAG_UINT_FIELDS)
            or any(type(value[key]) is not int or not -0x80000000 <= value[key] <= 0x7FFFFFFF
                   for key in DIAG_INT_FIELDS)):
        return None
    return dict(version=1, **{key: value[key] for key in FIELDS})


class AdmissionObserver:
    """At most128 attempted records, a fixed5second cadence and600second window.

    Time/output failures finish or consume bounded attempts without influencing
    the owner. A stop record is reserved, but delivery is not guaranteed. The
    advancing observer clock is distinct from the host capture deadline.
    """
    def __init__(self, clock, emit=print, output_ready=lambda: True, duration_s=600, max_records=128):
        if (type(duration_s) not in (int, float) or duration_s-duration_s != 0
                or not 1 <= duration_s <= 600 or type(max_records) is not int or not 2 <= max_records <= 128):
            raise ValueError("Admission observer bounds")
        self.clock, self.emit, self.output_ready = clock, emit, output_ready
        self.duration_s, self.max_records = duration_s, max_records
        self.started = self.last_clock = self.last_attempt = None
        self.records = self.emit_errors = self.cache_errors = self.output_ready_errors = 0
        self.finished = False

    def _ready(self):
        try:
            return self.output_ready() is True
        except Exception:
            self.output_ready_errors += 1
            return False

    def _emit(self, record):
        if self.records >= self.max_records or not self._ready():
            return
        self.records += 1
        record.update(sequence=self.records, records_attempted=self.records,
                      emit_errors=self.emit_errors, cache_errors=self.cache_errors,
                      output_ready_errors=self.output_ready_errors)
        try:
            line = TAG + json.dumps(record)
            if len(line.encode("utf8")) > MAX_RECORD_BYTES:
                raise ValueError("Admission record bound")
            self.emit(line)
        except Exception:
            self.emit_errors += 1

    def _metadata(self, now, kind, clock_valid=True):
        elapsed = min(self.duration_s, max(0, now-self.started)) if self.started is not None else 0
        return dict(schema=1, kind=kind, observer_elapsed_ms=int(elapsed*1000),
                    observer_remaining_ms=max(0, int(self.duration_s*1000)-int(elapsed*1000)),
                    clock_valid=clock_valid, observer_active=not self.finished,
                    fixed_emit_period_ms=5000, diagnostics=None)

    def _finish(self, reason, now, clock_valid=True):
        self.finished = True
        record = self._metadata(now, "admission_observer_stopped", clock_valid)
        record["reason"] = reason
        self._emit(record)

    def observe(self, owner):
        if self.finished:
            return
        try:
            now = self.clock()
            if type(now) not in (int, float) or now < 0 or now-now != 0:
                raise ValueError("Admission clock")
        except Exception:
            self._finish("clock_error", self.last_clock or 0, False)
            return
        if self.last_clock is not None and now < self.last_clock:
            self._finish("clock_regression", self.last_clock, False)
            return
        self.last_clock = now
        if self.started is None:
            self.started = now
        if now-self.started >= self.duration_s:
            self._finish("duration", now)
            return
        if self.last_attempt is not None and now-self.last_attempt < PERIOD_S:
            return
        if self.records >= self.max_records-1:
            return  # Keep duration bound; reserve the terminal record.
        self.last_attempt = now
        try:
            diagnostics = checked_cache(owner.diagnostics)
        except Exception:
            diagnostics = None
        if diagnostics is None:
            self.cache_errors += 1
        record = self._metadata(now, "admission_counters" if diagnostics is not None else "admission_unavailable")
        record["diagnostics"] = diagnostics
        self._emit(record)


def install_after_tick(policy_class, observer):
    """Compose after the current tick; preserve its result and exception behavior."""
    if getattr(policy_class, "_admission_observer_installed", False):
        raise ValueError("Admission observer already installed")
    original = policy_class.tick
    def tick(owner):
        result = original(owner)
        try:
            observer.observe(owner)
        except Exception:
            observer.finished = True
        return result
    policy_class.tick = tick
    policy_class._admission_observer_installed = True
    def restore():
        policy_class.tick = original
        del policy_class._admission_observer_installed
    return restore

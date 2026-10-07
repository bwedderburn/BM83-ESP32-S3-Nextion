"""Wrap-safe millisecond tick arithmetic for sub-second timers.

Why this exists (issue #149, audit finding R-03): on CircuitPython,
``time.monotonic()`` is a float counting seconds since boot, and floats on
this runtime carry only ~22 bits of precision. The gap between adjacent
representable values grows with uptime: ~1 ms after an hour, ~62 ms after
1.5 days, ~125 ms after 3 days, ~250 ms after 6 days. A timer of 35-200 ms
measured on that clock fires early or late by up to one gap, and a
deadline like ``now + 0.05`` can round back to ``now`` and fire at once.

``supervisor.ticks_ms()`` is an int that keeps 1 ms resolution forever but
wraps every 2**29 ms (~6.2 days); CircuitPython starts it so the first
wrap lands ~65 s after power-on, so every boot exercises the wrap path.
Values stay inside the small-int range, so these helpers do not allocate.

Rules for callers:
  * Never compare raw tick values with ``<`` / ``-``; use ``ticks_diff``.
  * ``ticks_diff`` is only meaningful for spans under 2**28 ms (~3.1
    days). A timestamp that may sit untouched for days (a "last sent at"
    rate limit) must be checked with ``ticks_recent``, which treats a
    negative (aliased) difference as "long ago" instead of "in the future".
  * Keep each timer on one clock. A deadline set with ``ticks_add`` must
    be read with ``ticks_ms``, never with ``time.monotonic()``.

On host Python (tests) there is no ``supervisor`` module, so ``ticks_ms``
derives ticks from ``time.monotonic()`` at call time; tests that
monkeypatch ``time.monotonic`` therefore drive these ticks too.
"""
import time

try:
    from supervisor import ticks_ms as _hw_ticks_ms
except ImportError:  # pragma: no cover - exercised implicitly on host
    _hw_ticks_ms = None

TICKS_PERIOD = 1 << 29
TICKS_MAX = TICKS_PERIOD - 1
TICKS_HALFPERIOD = TICKS_PERIOD // 2


def ticks_ms():
    """Return the current tick count in ms, wrapping at ``TICKS_PERIOD``."""
    if _hw_ticks_ms is not None:
        return _hw_ticks_ms()
    return int(time.monotonic() * 1000) & TICKS_MAX


def ticks_add(ticks, delta):
    """Return ``ticks`` advanced by ``delta`` ms, wrapped into the tick range."""
    return (ticks + delta) & TICKS_MAX


def ticks_diff(ticks1, ticks2):
    """Return the signed ms from ``ticks2`` to ``ticks1`` (``ticks1 - ticks2``).

    Correct across a wrap as long as the true span is under 2**28 ms.
    """
    diff = (ticks1 - ticks2) & TICKS_MAX
    return ((diff + TICKS_HALFPERIOD) & TICKS_MAX) - TICKS_HALFPERIOD


def ticks_less(ticks1, ticks2):
    """Return True when ``ticks1`` is earlier than ``ticks2``."""
    return ticks_diff(ticks1, ticks2) < 0


def ticks_recent(now, then, window_ms):
    """Return True when ``then`` is set and less than ``window_ms`` before ``now``.

    ``then is None`` means "never". A negative difference can only come
    from a timestamp so old that it aliased across the wrap, so it counts
    as long ago (not recent) rather than blocking for up to ~3 days.
    """
    if then is None:
        return False
    d = ticks_diff(now, then)
    return 0 <= d < window_ms

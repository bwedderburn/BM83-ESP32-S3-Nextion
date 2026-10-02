"""Tests for utils.ticks and the timers moved onto it (issue #149, R-03).

The firmware's sub-second timers moved off float ``time.monotonic()``
(whose step grows to 125-250 ms after days of uptime on CircuitPython)
onto wrap-safe ``supervisor.ticks_ms()`` arithmetic. On host, ticks are
derived from ``time.monotonic()``, so these tests drive a fake clock
parked just before the 2**29 ms wrap to prove every consumer survives it.
"""
import time

import pytest

from utils import ticks
from utils.ticks import (
    TICKS_HALFPERIOD,
    TICKS_MAX,
    TICKS_PERIOD,
    ticks_add,
    ticks_diff,
    ticks_less,
    ticks_ms,
    ticks_recent,
)


class FakeClock:
    """Settable stand-in for time.monotonic(), counted in whole ms.

    Returns the mid-point of the current ms so the host fallback's
    int(seconds * 1000) truncation never lands one ms short.
    """

    def __init__(self, start_ms):
        self.ms = start_ms

    def __call__(self):
        return (self.ms + 0.5) / 1000.0

    def advance_ms(self, ms):
        self.ms += ms


@pytest.fixture
def clock(monkeypatch):
    # 20 ms before the tick counter wraps.
    c = FakeClock(TICKS_PERIOD - 20)
    monkeypatch.setattr(time, "monotonic", c)
    return c


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------

def test_ticks_add_wraps_into_range():
    assert ticks_add(TICKS_MAX, 1) == 0
    assert ticks_add(0, -1) == TICKS_MAX
    assert ticks_add(100, 50) == 150


def test_ticks_diff_across_wrap():
    before = TICKS_MAX - 9       # 10 ms before the wrap
    after = ticks_add(before, 25)
    assert after == 15
    assert ticks_diff(after, before) == 25
    assert ticks_diff(before, after) == -25


def test_ticks_diff_half_period_boundary():
    assert ticks_diff(TICKS_HALFPERIOD - 1, 0) == TICKS_HALFPERIOD - 1
    # Exactly half a period apart is ambiguous; the convention is negative.
    assert ticks_diff(TICKS_HALFPERIOD, 0) == -TICKS_HALFPERIOD


def test_ticks_less_across_wrap():
    a = TICKS_MAX - 5
    b = ticks_add(a, 10)
    assert ticks_less(a, b)
    assert not ticks_less(b, a)
    assert not ticks_less(a, a)


def test_ticks_recent_none_means_never():
    assert ticks_recent(1234, None, 60) is False


def test_ticks_recent_window():
    then = TICKS_MAX - 10
    assert ticks_recent(ticks_add(then, 0), then, 60)
    assert ticks_recent(ticks_add(then, 59), then, 60)
    assert not ticks_recent(ticks_add(then, 60), then, 60)


def test_ticks_recent_treats_aliased_stale_timestamp_as_old():
    # A "last sent" stamp untouched for > 2**28 ms (~3.1 days) aliases to a
    # negative difference. It must read as long ago, not block for days.
    then = 1000
    now = ticks_add(then, TICKS_HALFPERIOD + 5000)
    assert ticks_diff(now, then) < 0
    assert ticks_recent(now, then, 60) is False


def test_host_ticks_follow_monotonic_and_wrap(clock):
    t0 = ticks_ms()
    assert t0 == TICKS_PERIOD - 20
    clock.advance_ms(30)
    t1 = ticks_ms()
    assert t1 == 10
    assert ticks_diff(t1, t0) == 30


def test_ticks_ms_prefers_hardware_counter(monkeypatch):
    monkeypatch.setattr(ticks, "_hw_ticks_ms", lambda: 4242)
    assert ticks.ticks_ms() == 4242


# ---------------------------------------------------------------------------
# Why: float precision on the target runtime
# ---------------------------------------------------------------------------

def _round_to_precision(x, bits=22):
    """Round x to ``bits`` significant bits, like a 30-bit CircuitPython float."""
    import math
    m, e = math.frexp(x)
    scale = 1 << bits
    return math.ldexp(round(m * scale) / scale, e)


def test_float_monotonic_step_after_days_exceeds_short_timers():
    """Documents R-03: a 22-bit float clock cannot resolve 35-200 ms after days."""
    six_days = 6.1 * 24 * 3600
    now = _round_to_precision(six_days)
    # A 50 ms deadline rounds straight back to "now" -> fires immediately.
    assert _round_to_precision(now + 0.05) == now
    # And the clock itself only advances in 0.25 s steps.
    assert _round_to_precision(now + 0.2) - now in (0.0, 0.25)


# ---------------------------------------------------------------------------
# Consumers
# ---------------------------------------------------------------------------

def test_nextion_tx_pacing_survives_wrap(clock):
    from nextion.display import Nextion

    class UART:
        def __init__(self):
            self.written = []

        def write(self, data):
            self.written.append(data)

    uart = UART()
    nx = Nextion(uart)
    nx.enqueue("a")
    nx.enqueue("b")
    nx.enqueue("c")
    nx.tick()
    assert len(uart.written) == 1
    clock.advance_ms(34)       # crosses the wrap; still inside the 35 ms gap
    nx.tick()
    assert len(uart.written) == 1
    clock.advance_ms(1)
    nx.tick()
    assert len(uart.written) == 2
    nx.tick()                  # same instant: paced
    assert len(uart.written) == 2


def test_nextion_tx_not_blocked_by_stale_last_tx(clock):
    from nextion.display import Nextion

    class UART:
        def __init__(self):
            self.written = []

        def write(self, data):
            self.written.append(data)

    uart = UART()
    nx = Nextion(uart)
    # Last write ~3.2 days ago: aliased negative diff must not block TX.
    nx._last_tx_at = ticks_add(ticks_ms(), -(TICKS_HALFPERIOD + 1000))
    nx.enqueue("x")
    nx.tick()
    assert len(uart.written) == 1


def _bm83():
    from bm83.bm83 import Bm83
    from tests.test_bm83_uart import MockUART
    uart = MockUART()
    return Bm83(uart), uart


def test_power_on_hold_is_full_2200ms_across_wrap(clock):
    from bm83.bm83 import Bm83
    bm, uart = _bm83()
    bm.power_on_cmd()
    assert len(uart.writes) == 1
    clock.advance_ms(2199)     # crosses the wrap
    bm.tick_power()
    assert bm._power_state == "on_press", "released before the 2.2 s MMI hold"
    assert len(uart.writes) == 1
    clock.advance_ms(1)
    bm.tick_power()
    assert bm._power_state == "on_init"
    assert Bm83.MMI_POWER_ON_RELEASE in uart.writes[1]
    clock.advance_ms(499)
    bm.tick_power()
    assert bm._power_state == "on_init"
    clock.advance_ms(1)
    bm.tick_power()
    assert bm._power_state is None


def test_power_off_hold_is_full_1500ms(clock):
    from bm83.bm83 import Bm83
    bm, uart = _bm83()
    bm.power_on = True
    bm.power_off_cmd()
    clock.advance_ms(1499)
    bm.tick_power()
    assert bm._power_state == "off_press"
    clock.advance_ms(1)
    bm.tick_power()
    assert bm._power_state is None
    assert Bm83.MMI_POWER_OFF_RELEASE in uart.writes[1]

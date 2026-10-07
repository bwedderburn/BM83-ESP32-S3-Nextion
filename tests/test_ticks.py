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
    ticks_due,
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


def test_nextion_boot_sync_then_tick_sends(clock, monkeypatch):
    """boot_sync() must leave TX pacing on integer ticks (PR #154 review)."""
    from nextion.display import Nextion

    class UART:
        def __init__(self):
            self.written = []
            self.in_waiting = 0

        def write(self, data):
            self.written.append(data)

        def read(self, n):
            return b""

    monkeypatch.setattr(time, "sleep", lambda _s: None)
    uart = UART()
    nx = Nextion(uart)
    nx.boot_sync()
    queued = len(nx.tx_queue)
    assert queued > 0
    nx.tick()                  # raised TypeError when boot_sync reset to 0.0
    assert len(uart.written) == 1
    clock.advance_ms(35)
    nx.tick()
    assert len(uart.written) == min(2, queued)


# ---------------------------------------------------------------------------
# ticks_due (deadline check with an alias horizon)
# ---------------------------------------------------------------------------

def test_ticks_due_none_past_future():
    now = 1000
    assert ticks_due(now, None, 60000) is True
    assert ticks_due(now, now, 60000) is True
    assert ticks_due(now, now - 1, 60000) is True
    assert ticks_due(now, now + 1, 60000) is False
    assert ticks_due(now, now + 60000, 60000) is False


def test_ticks_due_across_wrap():
    now = TICKS_MAX - 5
    deadline = ticks_add(now, 20)          # lands after the wrap
    assert ticks_due(now, deadline, 60000) is False
    assert ticks_due(ticks_add(now, 19), deadline, 60000) is False
    assert ticks_due(ticks_add(now, 20), deadline, 60000) is True


def test_ticks_due_treats_aliased_far_future_as_due():
    # A deadline set ~4 days ago aliases to ~2 days "ahead": beyond any real
    # schedule, so it must fire rather than stall the scheduler.
    now = 5000
    stale = ticks_add(now, -(TICKS_HALFPERIOD + 24 * 3600 * 1000))
    assert ticks_diff(stale, now) > 60000
    assert ticks_due(now, stale, 60000) is True


# ---------------------------------------------------------------------------
# BM83 AVRCP scheduler families on ticks (issue #149 follow-up)
# ---------------------------------------------------------------------------

def _connected_bm83():
    bm, uart = _bm83()
    bm.connected = True
    return bm, uart


def _reg_event_ids(uart):
    # avrcp_register_notification frames: AA, len_hi, len_lo, op, db,
    # AVC payload ... with the event id after the 0x31 PDU header.
    out = []
    for w in uart.writes:
        idx = w.find(bytes([0x31]))
        if idx >= 0:
            out.append(w)
    return out


def test_notif_registrations_stay_staggered_across_wrap(clock):
    """Contract 5: initial register-notifications never go out back-to-back."""
    bm, uart = _connected_bm83()
    bm.schedule_avrcp_notifications(((0.25, 0x01, 0), (0.75, 0x02, 0), (1.25, 0x05, 1)))
    sent_at = []
    for _ in range(400):                    # 2 s of 5 ms loop passes
        before = len(uart.writes)
        bm.tick_notif_regs()
        if len(uart.writes) > before:
            sent_at.append(clock.ms)
        clock.advance_ms(5)
    assert len(sent_at) == 3
    start = TICKS_PERIOD - 20
    assert [t - start for t in sent_at] == [250, 750, 1250]   # crosses the wrap
    gaps = [b - a for a, b in zip(sent_at, sent_at[1:])]
    assert min(gaps) >= bm._notif_reg_min_gap_ms


def test_notif_overdue_queue_still_spaced_by_min_gap(clock):
    bm, uart = _connected_bm83()
    bm.schedule_avrcp_notifications(((0.0, 0x01, 0), (0.0, 0x02, 0), (0.0, 0x05, 1)))
    sent_at = []
    for _ in range(300):
        before = len(uart.writes)
        bm.tick_notif_regs()
        if len(uart.writes) > before:
            sent_at.append(clock.ms)
        clock.advance_ms(5)
    gaps = [b - a for a, b in zip(sent_at, sent_at[1:])]
    assert len(sent_at) == 3
    assert all(g >= 450 for g in gaps)


def test_notif_gap_not_blocked_by_aliased_stale_stamp(clock):
    bm, uart = _connected_bm83()
    bm.schedule_avrcp_notifications(((0.0, 0x01, 0),))
    bm._last_notif_reg_at = ticks_add(ticks_ms(), -(TICKS_HALFPERIOD + 1000))
    bm.tick_notif_regs()
    assert len(uart.writes) == 1


def test_play_status_poll_period_across_wrap(clock):
    bm, uart = _connected_bm83()
    bm.schedule_play_status(0.05)
    polls = []
    for _ in range(700):                    # 3.5 s
        before = len(uart.writes)
        bm.tick_avrcp()
        if len(uart.writes) > before:
            polls.append(clock.ms)
        clock.advance_ms(5)
    start = TICKS_PERIOD - 20
    assert [t - start for t in polls] == [50, 1050, 2050, 3050]


def test_play_status_aliased_stale_deadline_polls_now(clock):
    bm, uart = _connected_bm83()
    bm._next_playstatus_at = ticks_add(ticks_ms(), -(TICKS_HALFPERIOD + 3600 * 1000))
    bm.tick_avrcp()
    assert len(uart.writes) == 1


def test_attrs_quiet_window_holds_across_wrap(clock):
    bm, uart = _connected_bm83()
    bm.defer_attrs(1.0)
    assert bm.schedule_attrs(0.15, force=True) is True   # pulled up to the floor
    clock.advance_ms(999)
    assert bm.tick_avrcp_attrs() is False
    clock.advance_ms(1)
    assert bm.tick_avrcp_attrs() is True
    assert bm._next_attrs_at is None and bm._attrs_not_before is None


def test_attrs_throttle_on_ticks(clock):
    bm, uart = _connected_bm83()
    assert bm.schedule_attrs(0.0) is True
    assert bm.tick_avrcp_attrs() is True
    clock.advance_ms(1499)
    assert bm.schedule_attrs(0.0) is False
    clock.advance_ms(1)
    assert bm.schedule_attrs(0.0) is True


def test_attrs_stale_floor_and_pending_are_replaced(clock):
    bm, uart = _connected_bm83()
    far = ticks_add(ticks_ms(), TICKS_HALFPERIOD - 1000)   # aliased "~3 days ahead"
    bm._attrs_not_before = far
    bm._next_attrs_at = far
    assert bm.schedule_attrs(0.2, force=True) is True
    assert ticks_diff(bm._next_attrs_at, ticks_ms()) == 200
    clock.advance_ms(200)
    assert bm.tick_avrcp_attrs() is True


def test_eq_and_reregister_throttles_across_wrap(clock):
    bm, uart = _bm83()
    assert bm.set_eq(bm.EQ_SEQ[1]) is not None
    assert bm.avrcp_reregister_status_changed() is True
    assert bm.avrcp_reregister_position_changed() is True
    assert bm.avrcp_reregister_track_changed() is True
    clock.advance_ms(249)                   # crosses the wrap
    assert bm.set_eq(bm.EQ_SEQ[2]) is None
    clock.advance_ms(1)
    assert bm.set_eq(bm.EQ_SEQ[2]) is not None
    clock.advance_ms(249)                   # 499 ms since the re-registrations
    assert bm.avrcp_reregister_status_changed() is False
    assert bm.avrcp_reregister_position_changed() is False
    clock.advance_ms(1)
    assert bm.avrcp_reregister_status_changed() is True
    assert bm.avrcp_reregister_position_changed() is True
    assert bm.avrcp_reregister_track_changed() is False
    clock.advance_ms(1500)
    assert bm.avrcp_reregister_track_changed() is True


def test_throttles_not_blocked_by_aliased_stale_stamps(clock):
    bm, uart = _bm83()
    stale = ticks_add(ticks_ms(), -(TICKS_HALFPERIOD + 1000))
    bm._last_eq_cmd_at = stale
    bm._last_status_changed_reg_at = stale
    assert bm.set_eq(bm.EQ_SEQ[1]) is not None
    assert bm.avrcp_reregister_status_changed() is True


def test_nextion_token_dedupe_across_wrap(clock):
    from nextion.display import Nextion

    class UART:
        def __init__(self):
            self.to_read = b""

        @property
        def in_waiting(self):
            return len(self.to_read)

        def read(self, n):
            out, self.to_read = self.to_read[:n], self.to_read[n:]
            return out

        def write(self, data):
            pass

    uart = UART()
    nx = Nextion(uart)
    got = []
    for step in (0, 149, 1):                # the 149 ms step crosses the wrap
        clock.advance_ms(step)
        uart.to_read = b"BT_PLAY\xff\xff\xff"
        tokens, _ = nx.read()
        got.extend(tokens)
    assert got == [b"BT_PLAY", b"BT_PLAY"]   # middle duplicate dropped

"""Required metadata refreshes retain throttle/quiet-window guarantees at tick wrap."""
import pytest

from bm83.bm83 import Bm83
from tests.test_bm83_uart import MockUART
from utils import ticks


@pytest.mark.parametrize("start", [0, ticks.TICKS_PERIOD - 100, ticks.TICKS_PERIOD - 1])
@pytest.mark.parametrize("quiet_ms", [100, 2000])
def test_queued_refresh_keeps_throttle_and_quiet_floor(monkeypatch, start, quiet_ms):
    clock = [start]
    monkeypatch.setattr(ticks, "_hw_ticks_ms", lambda: clock[0] & ticks.TICKS_MAX)
    uart = MockUART()
    bm = Bm83(uart)
    bm.connected = True
    assert bm.GEA_MAX_LEN == 2048
    assert bm.schedule_attrs(0)
    assert bm._next_attrs_at == (start & ticks.TICKS_MAX)  # Tick0 is not "unset".
    assert bm.tick_avrcp_attrs()
    first = bm._last_attrs_req_at
    clock[0] = start + 100
    bm.defer_attrs(quiet_ms / 1000.0)
    assert bm.schedule_attrs(0.25, queue_if_throttled=True)
    due_ms = max(1500, 100 + quiet_ms)
    assert ticks.ticks_diff(bm._next_attrs_at, first) == due_ms
    for elapsed in (200, 500, 1000):
        clock[0] = start + elapsed
        assert not bm.schedule_attrs(0.25, queue_if_throttled=True)
        assert ticks.ticks_diff(bm._next_attrs_at, first) == due_ms
        assert not bm.tick_avrcp_attrs()
    clock[0] = start + due_ms - 1
    assert not bm.tick_avrcp_attrs()
    clock[0] += 1
    assert bm.tick_avrcp_attrs()
    assert len(uart.writes) == 2
    assert not bm.tick_avrcp_attrs()


@pytest.mark.parametrize("start", [0, ticks.TICKS_PERIOD - 100])
def test_default_drop_and_force_keep_floor_and_zero_deadline(monkeypatch, start):
    clock = [start]
    monkeypatch.setattr(ticks, "_hw_ticks_ms", lambda: clock[0] & ticks.TICKS_MAX)
    bm = Bm83(MockUART())
    bm.connected = True
    assert bm.schedule_attrs(0)
    assert bm.tick_avrcp_attrs()
    clock[0] += 100
    assert not bm.schedule_attrs(0.25)
    assert bm._next_attrs_at is None
    bm.defer_attrs(1.0)
    assert bm.schedule_attrs(0, force=True)
    assert ticks.ticks_diff(bm._next_attrs_at, clock[0] & ticks.TICKS_MAX) == 1000

    # A fresh request whose deadline is exactly0 must survive and drain, both
    # at boot tick0 and when adding100ms crosses the hardware counter's wrap.
    clock[0] = start
    fresh = Bm83(MockUART())
    fresh.connected = True
    delay_ms = 0 if start == 0 else 100
    assert fresh.schedule_attrs(delay_ms / 1000.0)
    assert fresh._next_attrs_at == 0
    if delay_ms:
        clock[0] += delay_ms - 1
        assert not fresh.tick_avrcp_attrs()
        clock[0] += 1
    assert fresh.tick_avrcp_attrs()
    assert fresh._next_attrs_at is None


@pytest.mark.parametrize("start", [5000, ticks.TICKS_PERIOD - 1000, ticks.TICKS_PERIOD - 2000])
def test_aliased_pending_request_cannot_bypass_fresh_quiet_floor(monkeypatch, start):
    clock = [start]
    monkeypatch.setattr(ticks, "_hw_ticks_ms", lambda: clock[0] & ticks.TICKS_MAX)
    uart = MockUART()
    bm = Bm83(uart)
    bm.connected = True
    now = clock[0] & ticks.TICKS_MAX
    # A real old deadline can alias far into the future; the scheduler's
    # horizon deliberately treats it as due rather than stalling for days.
    bm._next_attrs_at = ticks.ticks_add(now, -(ticks.TICKS_HALFPERIOD + 3600000))
    assert ticks.ticks_due(now, bm._next_attrs_at, 60000)
    floor = bm.defer_attrs(2.0)
    assert ticks.ticks_diff(floor, now) == 2000
    assert not bm.tick_avrcp_attrs()
    assert uart.writes == []
    clock[0] = start + 1999
    assert not bm.tick_avrcp_attrs()
    assert uart.writes == []
    clock[0] += 1
    assert (clock[0] & ticks.TICKS_MAX) == floor
    assert bm.tick_avrcp_attrs()
    assert len(uart.writes) == 1
    assert bm._next_attrs_at is None
    assert bm._attrs_not_before is None
    assert not bm.tick_avrcp_attrs()

"""Boot status reconciliation never manufactures a BM83 power/link belief."""
from types import SimpleNamespace

import pytest

from bm83.link_probe import StartupLinkProbe


def make_probe(enabled=True, **state):
    clock = SimpleNamespace(now=100.0)
    calls, logs = [], []
    fields = dict(power_on=False, connected=False, _explicit_off=False,
                  _power_state=None, _power_confirm_deadline=0.0, audio_source=None)
    fields.update(state)
    bm = SimpleNamespace(**fields)
    bm.send = lambda op, params: calls.append(("send", op, params))
    bm.avrcp_get_play_status = lambda db: calls.append(("play_status", db))
    probe = StartupLinkProbe(bm, enabled=enabled, clock=lambda: clock.now, log=logs.append)
    return probe, bm, clock, calls, logs


def arm(probe, clock):
    clock.now = 102.5
    assert probe.tick()


def test_status_queries_are_delayed_once_only_and_never_set_power_link_or_audio_source():
    probe, bm, clock, calls, logs = make_probe()
    before = vars(bm).copy()
    assert not probe.tick()
    clock.now = 102.499
    assert not probe.tick()
    arm(probe, clock)
    assert calls == [("send", 0x0D, b"\x00")]
    assert not probe.tick()
    assert probe.note_event(0x1E, bytes((6, 7, 0, 1, 0, 1, 0)))
    assert calls == [("send", 0x0D, b"\x00"), ("play_status", 0)]
    assert vars(bm) == before
    assert logs == ["[BTM] startup link-status probe", "[BTM] existing AVRCP session -> query play status"]
    clock.now = 1000
    assert not probe.tick()
    assert not probe.note_event(0x1E, bytes((6, 7, 0, 1, 0, 1, 0)))
    assert len(calls) == 2


def test_disabled_probe_never_sends_or_logs_even_when_time_passes():
    probe, _bm, clock, calls, logs = make_probe(enabled=False)
    clock.now = 1000
    assert not probe.tick()
    assert not probe.note_event(0x1E, bytes((6, 7, 0, 1, 0, 1, 0)))
    assert calls == logs == []


@pytest.mark.parametrize("state", [
    {"power_on": True}, {"connected": True}, {"_explicit_off": True},
    {"_power_state": "on_press"}, {"_power_state": "on_init"}, {"_power_state": "off_press"},
    {"_power_confirm_deadline": 104.0},
])
def test_known_power_session_or_user_power_operation_suppresses_probe_permanently(state):
    probe, bm, clock, calls, logs = make_probe(**state)
    clock.now = 103
    assert not probe.tick()
    for name in state:
        setattr(bm, name, None if name == "_power_state" else False)
    clock.now = 110
    assert not probe.tick()
    assert calls == logs == []


@pytest.mark.parametrize("name,value", [
    ("power_on", True), ("connected", True), ("_explicit_off", True),
    ("_power_state", "off_press"), ("_power_confirm_deadline", 110.0),
])
def test_power_or_session_change_while_reply_pending_cancels_followup(name, value):
    probe, bm, clock, calls, _logs = make_probe()
    arm(probe, clock)
    setattr(bm, name, value)
    assert not probe.note_event(0x1E, bytes((6, 7, 0, 1, 0, 1, 0)))
    setattr(bm, name, None if name == "_power_state" else False)
    assert not probe.note_event(0x1E, bytes((6, 7, 0, 1, 0, 1, 0)))
    assert calls == [("send", 0x0D, b"\x00")]


@pytest.mark.parametrize("flags", [0, 1, 2, 3, 8, 16, 24, 27])
def test_db0_without_avrcp_never_queries_play_status_even_if_db1_has_avrcp(flags):
    probe, _bm, clock, calls, _logs = make_probe()
    arm(probe, clock)
    assert not probe.note_event(0x1E, bytes((6, flags, 7, 1, 1, 1, 1)))
    assert calls == [("send", 0x0D, b"\x00")]


@pytest.mark.parametrize("flags", [4, 5, 6, 7, 12, 20, 28, 31])
def test_any_db0_profile_combination_with_avrcp_allows_exactly_one_status_query(flags):
    probe, _bm, clock, calls, _logs = make_probe()
    arm(probe, clock)
    assert probe.note_event(0x1E, bytes((6, flags, 0, 0, 0, 0, 0)))
    assert not probe.note_event(0x1E, bytes((6, flags, 0, 0, 0, 0, 0)))
    assert calls == [("send", 0x0D, b"\x00"), ("play_status", 0)]


def test_reported_soft_off_never_authorizes_play_status_even_with_contradictory_flags():
    probe, bm, clock, calls, _logs = make_probe()
    arm(probe, clock)
    assert not probe.note_event(0x1E, bytes((0, 7, 0, 0, 0, 0, 0)))
    assert not bm.power_on and not bm.connected
    assert calls == [("send", 0x0D, b"\x00")]


@pytest.mark.parametrize("params", [b"", b"\x06", bytes(6), bytes(8)])
def test_malformed_reply_is_ignored_without_authorizing_or_consuming_valid_reply(params):
    probe, _bm, clock, calls, _logs = make_probe()
    arm(probe, clock)
    assert not probe.note_event(0x1E, params)
    assert calls == [("send", 0x0D, b"\x00")]
    assert probe.note_event(0x1E, bytes((6, 7, 0, 1, 0, 1, 0)))


@pytest.mark.parametrize("op", [0x00, 0x01, 0x20, 0x1A, 0x5D])
def test_unrelated_event_never_authorizes_or_consumes_requested_status_reply(op):
    probe, _bm, clock, calls, _logs = make_probe()
    arm(probe, clock)
    assert not probe.note_event(op, bytes((6, 7, 0, 1, 0, 1, 0)))
    assert calls == [("send", 0x0D, b"\x00")]
    assert probe.note_event(0x1E, bytes((6, 7, 0, 1, 0, 1, 0)))


@pytest.mark.parametrize("use_tick", [False, True])
def test_missing_or_late_reply_times_out_once_and_cannot_rearm(use_tick):
    probe, _bm, clock, calls, _logs = make_probe()
    arm(probe, clock)
    clock.now += 5
    if use_tick:
        assert not probe.tick()
    assert not probe.note_event(0x1E, bytes((6, 7, 0, 1, 0, 1, 0)))
    clock.now += 100
    assert not probe.tick()
    assert calls == [("send", 0x0D, b"\x00")]


def test_unsolicited_link_status_before_our_query_does_not_trigger_any_request():
    probe, _bm, _clock, calls, logs = make_probe()
    assert not probe.note_event(0x1E, bytes((6, 7, 0, 1, 0, 1, 0)))
    assert calls == logs == []

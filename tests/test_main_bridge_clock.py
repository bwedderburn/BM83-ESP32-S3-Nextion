"""Real main-loop clock ownership using Mac source estimates and fresh samples."""
import time

import pytest

from bm83.bm83 import Bm83
from nextion.display import NX_RUNTIME
from tests import test_main_metadata_retry as harness
from tests.test_bm83_uart import frame_to_bytes
from tests.test_main_metadata_bridge import play_status, run_bridge_main
from tests.test_metadata_bridge import packet
from utils.common import TIME_UNKNOWN, _fmt_ms


def run_clock_main(monkeypatch, script, packets):
    history = []
    base_display = harness._Display

    class RecordingDisplay(base_display):
        def set_text_active_page(self, name, value):
            history.append((time.monotonic(), name, value))
            return super().set_text_active_page(name, value)

    monkeypatch.setattr(harness, "_Display", RecordingDisplay)
    writes, text, snapshots, bridge = run_bridge_main(monkeypatch, script, packets)
    return writes, text, dict(snapshots), bridge, history


def shown(history, at, field):
    values = [value for when, name, value in history if when <= at and name == NX_RUNTIME[field]]
    assert values, "the main loop never wrote the requested Nextion field"
    return values[-1]


def test_mac_clock_uses_real_samples_then_fresh_projection_despite_native_zero_replies(monkeypatch):
    script = [(100.0, (play_status(),)), (101.0, (play_status(),)),
              (102.0, (play_status(),)), (102.2, (play_status(),))]
    _writes, text, snapshots, _bridge, history = run_clock_main(monkeypatch, script, {
        100.0: [packet(position_ms=12000, duration_ms=180000)],
        101.0: [packet(seq=2, position_ms=13000, duration_ms=180000)],
    })
    assert shown(history, 100.0, "time_cur") == _fmt_ms(12000)
    assert shown(history, 101.0, "time_cur") == _fmt_ms(13000)
    assert shown(history, 102.0, "time_cur") == _fmt_ms(14000)
    assert text[NX_RUNTIME["time"]] == _fmt_ms(180000)
    assert snapshots[102.0]["position_ms"] == 13000
    assert snapshots[102.0]["position_age_ms"] == 1000
    assert snapshots[102.0]["clock_advancing"]
    # Rendering and unrelated AVRCP events must not create newer samples.
    assert snapshots[102.2]["position_age_ms"] == 1200


def test_paused_mac_clock_freezes_despite_native_playing_status(monkeypatch):
    script = [(100.0, (play_status(),)), (101.0, (play_status(),)),
              (102.0, (play_status(),)), (103.0, (play_status(),)), (104.0, (play_status(),))]
    _writes, text, snapshots, _bridge, history = run_clock_main(monkeypatch, script, {
        100.0: [packet(position_ms=12000)],
        101.0: [packet(seq=2, position_ms=13000)],
        102.0: [packet(seq=3, state="paused", position_ms=13500)],
    })
    assert shown(history, 102.0, "time_cur") == _fmt_ms(13500)
    assert text[NX_RUNTIME["time_cur"]] == _fmt_ms(13500)
    assert snapshots[104.0]["play_status"] == 2
    assert snapshots[104.0]["position_ms"] == 13500
    assert snapshots[104.0]["position_age_ms"] == 2000
    assert not snapshots[104.0]["clock_advancing"]


def test_playing_label_with_frozen_source_positions_stops_projection(monkeypatch):
    script = [(100.0, ()), (101.0, ()), (102.0, ()), (103.0, ())]
    _writes, text, snapshots, _bridge, _history = run_clock_main(monkeypatch, script, {
        100.0: [packet(position_ms=12000)],
        101.0: [packet(seq=2, position_ms=13000)],
        102.0: [packet(seq=3, position_ms=13000)],
    })
    assert snapshots[101.0]["clock_advancing"]
    assert snapshots[102.0]["play_status"] == 1
    assert not snapshots[102.0]["clock_advancing"]
    assert text[NX_RUNTIME["time_cur"]] == _fmt_ms(13000)


def test_backward_seek_rebases_immediately_and_waits_for_new_motion(monkeypatch):
    script = [(100.0, ()), (101.0, ()), (102.0, ()), (103.0, ()), (104.0, ())]
    _writes, _text, snapshots, _bridge, history = run_clock_main(monkeypatch, script, {
        100.0: [packet(position_ms=12000)],
        101.0: [packet(seq=2, position_ms=13000)],
        102.0: [packet(seq=3, position_ms=1000)],
        104.0: [packet(seq=4, position_ms=3000)],
    })
    assert shown(history, 102.0, "time_cur") == _fmt_ms(1000)
    assert shown(history, 103.0, "time_cur") == _fmt_ms(1000)
    assert not snapshots[102.0]["clock_advancing"]
    assert snapshots[104.0]["clock_advancing"]
    assert shown(history, 104.0, "time_cur") == _fmt_ms(3000)


def test_track_change_clears_old_total_and_motion_even_when_new_position_is_larger(monkeypatch):
    script = [(100.0, ()), (101.0, ()), (102.0, ()), (103.0, ())]
    _writes, text, snapshots, _bridge, history = run_clock_main(monkeypatch, script, {
        100.0: [packet(position_ms=12000, duration_ms=180000)],
        101.0: [packet(seq=2, position_ms=13000, duration_ms=180000)],
        102.0: [packet(seq=3, title="Different song", position_ms=90000, duration_ms=None)],
    })
    assert snapshots[102.0]["title"] == "Different song"
    assert snapshots[102.0]["duration_ms"] is None
    assert not snapshots[102.0]["clock_advancing"]
    assert shown(history, 102.0, "time_cur") == _fmt_ms(90000)
    assert text[NX_RUNTIME["time_cur"]] == _fmt_ms(90000)
    assert text[NX_RUNTIME["time"]] == TIME_UNKNOWN


@pytest.mark.parametrize("position,duration,elapsed,total", [
    (None, None, TIME_UNKNOWN, TIME_UNKNOWN),
    (None, 180000, TIME_UNKNOWN, _fmt_ms(180000)),
    (12000, None, _fmt_ms(12000), TIME_UNKNOWN),
    (0, 180000, _fmt_ms(0), _fmt_ms(180000)),
    (0, None, TIME_UNKNOWN, TIME_UNKNOWN),
])
def test_partial_mac_timing_does_not_invent_zero_or_a_previous_total(
        monkeypatch, position, duration, elapsed, total):
    script = [(100.0, ()), (101.0, (play_status(),))]
    _writes, text, snapshots, _bridge, _history = run_clock_main(monkeypatch, script, {
        100.0: [packet(position_ms=12000, duration_ms=180000)],
        101.0: [packet(seq=2, position_ms=position, duration_ms=duration)],
    })
    assert text[NX_RUNTIME["time_cur"]] == elapsed
    assert text[NX_RUNTIME["time"]] == total
    assert snapshots[101.0]["duration_ms"] == duration
    if position is None or (position == 0 and duration is None):
        assert snapshots[101.0]["position_ms"] is None


def test_source_sample_expires_before_bridge_text_lease_and_never_refreshes_itself(monkeypatch):
    script = [(100.0, ()), (101.0, ()), (102.0, ()), (105.1, ()),
              (106.2, ()), (107.3, ()), (109.0, ())]
    _writes, text, snapshots, _bridge, history = run_clock_main(monkeypatch, script, {
        100.0: [packet(position_ms=12000)],
        101.0: [packet(seq=2, position_ms=13000)],
    })
    assert snapshots[105.1]["position_age_ms"] == 4100
    assert snapshots[106.2]["title"] == "Kind"
    assert snapshots[106.2]["position_ms"] is None
    assert not snapshots[106.2]["clock_advancing"]
    assert shown(history, 106.2, "time_cur") == TIME_UNKNOWN
    assert shown(history, 106.2, "time") == _fmt_ms(180000)
    assert shown(history, 107.3, "time_cur") == TIME_UNKNOWN
    assert snapshots[109.0]["title"] == ""
    assert text[NX_RUNTIME["time_cur"]] == text[NX_RUNTIME["time"]] == TIME_UNKNOWN


def test_projection_never_exceeds_the_source_duration(monkeypatch):
    script = [(100.0, ()), (101.0, ()), (102.0, ()), (103.0, ())]
    _writes, text, snapshots, _bridge, _history = run_clock_main(monkeypatch, script, {
        100.0: [packet(position_ms=178000, duration_ms=180000)],
        101.0: [packet(seq=2, position_ms=179000, duration_ms=180000)],
    })
    assert snapshots[103.0]["position_ms"] == 179000
    assert text[NX_RUNTIME["time_cur"]] == _fmt_ms(180000)


def test_native_track_information_takes_over_clock_and_ignores_later_mac_samples(monkeypatch):
    script = [(100.0, ()), (101.0, ()),
              (102.0, (harness._metadata((1, "Phone song"), (2, "Phone artist")),)),
              (103.0, (play_status(duration_ms=240000, position_ms=45000, state=2),))]
    _writes, text, snapshots, _bridge, _history = run_clock_main(monkeypatch, script, {
        100.0: [packet(position_ms=12000)],
        101.0: [packet(seq=2, position_ms=13000)],
        102.0: [packet(seq=3, position_ms=14000)],
        103.0: [packet(seq=4, position_ms=15000)],
    })
    assert snapshots[103.0]["title"] == "Phone song"
    assert snapshots[103.0]["position_ms"] == 45000
    assert snapshots[103.0]["duration_ms"] == 240000
    assert snapshots[103.0]["play_status"] == 2
    assert text[NX_RUNTIME["time_cur"]] == _fmt_ms(45000)
    assert text[NX_RUNTIME["time"]] == _fmt_ms(240000)


@pytest.mark.parametrize("state", [0x00, 0x0C, 0x11, Bm83.AUDIO_SRC_AUX])
def test_bluetooth_power_link_suspend_and_aux_guards_clear_bridge_clock(monkeypatch, state):
    event = frame_to_bytes(Bm83.EVT_BTM_STATUS, bytes([state]))
    script = [(100.0, ()), (101.0, ()), (102.0, (event,)), (103.0, ()), (104.0, ())]
    _writes, text, snapshots, _bridge, _history = run_clock_main(monkeypatch, script, {
        100.0: [packet(position_ms=12000)],
        101.0: [packet(seq=2, position_ms=13000)],
        103.0: [packet(seq=3, position_ms=15000)],
    })
    assert snapshots[101.0]["clock_advancing"]
    assert snapshots[104.0]["position_ms"] is None
    assert snapshots[104.0]["duration_ms"] is None
    assert not snapshots[104.0]["clock_advancing"]
    assert text[NX_RUNTIME["time_cur"]] == text[NX_RUNTIME["time"]] == TIME_UNKNOWN


def test_mac_avrcp_notifications_do_not_replace_bridge_status_position_or_track_clock(monkeypatch):
    paused = harness._avc_reply(0x31, b"\x01\x02", response=0x0D)
    position = harness._avc_reply(0x31, b"\x05" + bytes(4), response=0x0D)
    track = harness._avc_reply(0x31, b"\x02" + bytes(8), response=0x0D)
    script = [(100.0, ()), (101.0, ()), (102.0, (paused, position, track)), (103.0, ())]
    _writes, text, snapshots, _bridge, _history = run_clock_main(monkeypatch, script, {
        100.0: [packet(position_ms=12000)],
        101.0: [packet(seq=2, position_ms=13000)],
    })
    assert snapshots[103.0]["play_status"] == 1
    assert snapshots[103.0]["position_ms"] == 13000
    assert snapshots[103.0]["position_age_ms"] == 2000
    assert snapshots[103.0]["clock_advancing"]
    assert text[NX_RUNTIME["time_cur"]] == _fmt_ms(15000)


def test_native_nonprimary_metadata_cannot_overwrite_bridge_duration(monkeypatch):
    script = [(100.0, ()), (101.0, ()),
              (102.0, (harness._metadata((7, "999000"), (6, "Rock")),)), (103.0, ())]
    _writes, text, snapshots, _bridge, _history = run_clock_main(monkeypatch, script, {
        100.0: [packet(position_ms=12000, duration_ms=180000)],
        101.0: [packet(seq=2, position_ms=13000, duration_ms=180000)],
    })
    assert snapshots[103.0]["title"] == "Kind"
    assert snapshots[103.0]["duration_ms"] == 180000
    assert text[NX_RUNTIME["time"]] == _fmt_ms(180000)

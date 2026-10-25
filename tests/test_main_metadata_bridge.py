"""Exercise the real UART/UI loop with independent authenticated Mac text."""
import time

import pytest

from bm83.bm83 import Bm83
from nextion.display import NX_RUNTIME
from remote import metadata_bridge as module
from tests.test_main_metadata_retry import _avc_reply, _metadata, _run_main
from tests.test_bm83_uart import frame_to_bytes
from tests.test_metadata_bridge import Socket, TOKEN, packet


def play_status(duration_ms=0, position_ms=0, state=1):
    return _avc_reply(0x30, duration_ms.to_bytes(4, "big") + position_ms.to_bytes(4, "big") + bytes([state]))


def run_bridge_main(monkeypatch, script, packets):
    socket = Socket()
    base_class = module.MetadataBridge
    bridge = base_class(clock=lambda: time.monotonic(), profile={"v": 1, "token": TOKEN},
                        socket=socket, log=lambda _message: None)
    sent_at = set()
    original_poll = bridge.poll

    def scripted_poll(now=None):
        if now not in sent_at:
            sent_at.add(now)
            socket.pending.extend((raw, "192.168.1.4") for raw in packets.get(now, ()))
        original_poll(now)

    bridge.poll = scripted_poll
    monkeypatch.setattr(module, "MetadataBridge", lambda: bridge)
    snapshots = []
    writes, text = _run_main(monkeypatch, script, snapshots)
    return writes, text, snapshots, bridge


def test_mac_text_with_unknown_timing_does_not_create_clock_or_transport_commands(monkeypatch):
    script = [(100.0, (play_status(),)), (101.0, (play_status(),)), (102.0, (play_status(),))]
    writes, text, snapshots, _bridge = run_bridge_main(monkeypatch, script, {
        100.0: [packet(title="Flâneur", artist="Plini", position_ms=None, duration_ms=None)],
    })
    assert text[NX_RUNTIME["title"]] == "Fl neur"
    assert text[NX_RUNTIME["artist"]] == "Plini"
    assert text[NX_RUNTIME["album"]] == "Sunhead - EP"
    source = snapshots[-1][1]
    assert source["title"] == "Flâneur" and source["artist"] == "Plini"
    assert source["position_ms"] is None and source["duration_ms"] is None
    assert not source["clock_advancing"]
    # The independent metadata path never sends play/next/volume/power actions.
    assert not any(frame[3] in (Bm83.OP_MUSIC_CONTROL, Bm83.OP_MMI_ACTION) for _now, frame in writes)


def test_authenticated_network_text_is_sanitized_before_nextion_commands(monkeypatch):
    script = [(100.0, ()), (101.0, ())]
    _writes, text, snapshots, _bridge = run_bridge_main(monkeypatch, script, {
        100.0: [packet(title='Song";page 0', artist="Björk")],
    })
    assert '"' not in text[NX_RUNTIME["title"]]
    assert snapshots[-1][1]["title"] == 'Song";page 0'


def test_fresh_native_metadata_immediately_wins_and_stays_authoritative(monkeypatch):
    script = [(100.0, ()), (101.0, (_metadata((1, "Phone song"), (2, "Phone artist")),)),
              (102.0, ()), (120.0, ())]
    _writes, text, snapshots, _bridge = run_bridge_main(monkeypatch, script, {
        100.0: [packet()],
        101.0: [packet(seq=2, title="Mac overwrites phone")],
        102.0: [packet(seq=3, title="Another Mac update")],
    })
    assert snapshots[0][1]["title"] == "Kind"
    assert snapshots[1][1]["title"] == "Phone song"
    assert snapshots[-1][1]["title"] == "Phone song"
    assert text[NX_RUNTIME["title"]] == "Phone song"
    assert text[NX_RUNTIME["artist"]] == "Phone artist"


def test_bridge_expiry_clears_its_text_without_inventing_disconnection(monkeypatch):
    script = [(100.0, (play_status(),)), (107.9, (play_status(),)), (108.0, (play_status(),))]
    _writes, text, snapshots, _bridge = run_bridge_main(monkeypatch, script, {100.0: [packet()]})
    assert snapshots[1][1]["title"] == "Kind"
    assert snapshots[-1][1]["title"] == ""
    assert text[NX_RUNTIME["title"]] == "—"
    assert snapshots[-1][1]["power_on"] and snapshots[-1][1]["connected"]


def test_stop_packet_clears_mac_text_immediately(monkeypatch):
    script = [(100.0, ()), (101.0, ())]
    _writes, text, snapshots, _bridge = run_bridge_main(monkeypatch, script, {
        100.0: [packet()], 101.0: [packet(seq=2, state="stopped")],
    })
    assert snapshots[0][1]["title"] == "Kind"
    assert snapshots[-1][1]["title"] == ""
    assert text[NX_RUNTIME["title"]] == "—"


@pytest.mark.parametrize("state", [0x00, 0x0C, 0x11, Bm83.AUDIO_SRC_AUX])
def test_bluetooth_off_suspend_disconnect_or_aux_cannot_retain_network_text(monkeypatch, state):
    event = frame_to_bytes(Bm83.EVT_BTM_STATUS, bytes([state]))
    script = [(100.0, ()), (101.0, (event,)), (102.0, ()), (103.0, ())]
    _writes, text, snapshots, _bridge = run_bridge_main(monkeypatch, script, {
        100.0: [packet()], 102.0: [packet(seq=2, title="Should not display")],
    })
    assert snapshots[0][1]["title"] == "Kind"
    assert snapshots[-1][1]["title"] == ""
    assert text[NX_RUNTIME["title"]] == "—"


def test_real_native_track_change_does_not_expose_bridge_during_missing_attribute_gap(monkeypatch):
    changed = _avc_reply(0x31, b"\x02" + bytes(8), response=0x0D)
    script = [(100.0, (_metadata((1, "Phone song"), (2, "Phone artist")),)),
              (101.0, (changed,)), (102.0, ())]
    _writes, text, snapshots, _bridge = run_bridge_main(monkeypatch, script, {
        100.0: [packet()], 101.0: [packet(seq=2)], 102.0: [packet(seq=3)],
    })
    assert all(snapshot["title"] != "Kind" for _now, snapshot in snapshots)
    assert text[NX_RUNTIME["title"]] == "Phone song"


def test_mac_track_notification_clear_is_repaired_from_fresh_bridge_cache(monkeypatch):
    changed = _avc_reply(0x31, b"\x02" + bytes(8), response=0x0D)
    script = [(100.0, ()), (101.0, (changed,)), (102.0, (play_status(),))]
    _writes, text, snapshots, _bridge = run_bridge_main(monkeypatch, script, {100.0: [packet()]})
    assert all(snapshot["title"] == "Kind" for _now, snapshot in snapshots)
    assert text[NX_RUNTIME["title"]] == "Kind"
    assert text[NX_RUNTIME["album"]] == "Sunhead - EP"


def test_new_bluetooth_session_releases_native_priority_but_rejects_old_mac_packet(monkeypatch):
    down = frame_to_bytes(Bm83.EVT_BTM_STATUS, b"\x0c")
    up = frame_to_bytes(Bm83.EVT_BTM_STATUS, b"\x0b")
    script = [(100.0, (_metadata((1, "Phone song"), (2, "Phone artist")),)),
              (101.0, (down,)), (102.0, (up,)), (103.0, ())]
    _writes, text, snapshots, _bridge = run_bridge_main(monkeypatch, script, {
        100.0: [packet()], 102.0: [packet()], 103.0: [packet(seq=2, title="Mac new session")],
    })
    assert snapshots[0][1]["title"] == "Phone song"
    assert snapshots[2][1]["title"] == ""
    assert snapshots[-1][1]["title"] == "Mac new session"
    assert text[NX_RUNTIME["title"]] == "Mac new session"

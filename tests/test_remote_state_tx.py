"""Source lifecycle, pacing and radio back-pressure for CrowPanel updates."""
from remote.espnow_rx import EspNowRemote
from remote.state_tx import StatePublisher


class Clock:
    def __init__(self, value=0):
        self.value = value

    def __call__(self):
        return self.value


class Sink:
    state_tx_enabled = True
    ready = True

    def __init__(self):
        self.frames = []

    def state_tx_ready(self):
        return self.ready

    def send_state_frame(self, frame):
        self.frames.append(frame)
        return True


def publisher():
    clock = Clock()
    sink = Sink()
    state = StatePublisher(sink, clock=clock, session=123)
    state.set_transport(True, True, False)
    state.note_status(1)
    state.note_attributes({1: "Track", 2: "Artist", 3: "Album"})
    state.note_position(12000, 180000)
    return state, sink, clock


def test_radio_snapshots_preserve_source_sample_age():
    state, sink, clock = publisher()
    state.tick()
    clock.value = 4000
    state.tick()
    snapshot = state.snapshot()
    assert snapshot["position_ms"] == 12000
    assert snapshot["position_age_ms"] == 4000
    assert sink.frames


def test_stalled_source_expiry_is_latched_across_tick_wrap():
    state, _sink, clock = publisher()
    clock.value = 6000
    assert state.snapshot()["position_ms"] is None
    clock.value = 20
    assert state.snapshot()["position_ms"] is None


def test_pause_waits_for_real_position_and_seek_rebases_it():
    state, _sink, clock = publisher()
    clock.value = 2000
    state.note_status(2)
    assert state.snapshot()["position_ms"] is None
    state.note_position(14000)
    clock.value = 3500
    assert state.snapshot()["position_ms"] == 14000
    assert state.snapshot()["position_age_ms"] == 1500
    state.note_position(90000)
    assert state.snapshot()["position_ms"] == 90000
    assert state.snapshot()["position_age_ms"] == 0


def test_unknown_duration_zero_position_never_starts_clock():
    state = StatePublisher(Sink(), clock=Clock(), session=1)
    state.set_transport(True, True, False)
    state.note_status(1)
    state.note_position(0, 0)
    assert state.snapshot()["position_ms"] is None
    assert state.snapshot()["duration_ms"] is None


def test_track_change_clears_every_old_field_until_new_data():
    state, _sink, _clock = publisher()
    state.clear_track()
    snapshot = state.snapshot()
    assert snapshot["title"] == snapshot["artist"] == snapshot["album"] == ""
    assert snapshot["position_ms"] is None
    assert snapshot["duration_ms"] is None
    state.note_attributes({1: "New title"})
    assert state.snapshot()["title"] == "New title"
    assert state.snapshot()["artist"] == ""


def test_off_disconnect_aux_and_suspension_do_not_reuse_cached_track():
    for transport in ((False, True, False, False), (True, False, False, False),
                      (True, True, True, False), (True, True, False, True)):
        state, _sink, _clock = publisher()
        state.set_transport(*transport)
        assert state.snapshot()["title"] == ""
        assert state.snapshot()["position_ms"] is None
        state.set_transport(True, True, False)
        assert state.snapshot()["title"] == ""
        assert state.snapshot()["duration_ms"] is None


def test_unicode_text_kept_separate_from_nextion_ascii():
    state, _sink, _clock = publisher()
    state.note_attributes({1: "Björk – Jóga"})
    assert state.snapshot()["title"] == "Björk – Jóga"


def test_one_frame_per_tick_no_burst_and_periodic_loss_repair():
    state, sink, clock = publisher()
    state.note_attributes({1: "T" * 96, 2: "A" * 96, 3: "B" * 96})
    for _ in range(7):
        before = len(sink.frames)
        state.tick()
        assert len(sink.frames) == before + 1
        state.tick()
        assert len(sink.frames) == before + 1
        clock.value += 40
    assert len(sink.frames) == 7
    seq = sink.frames[0][8:10]
    clock.value += 1000
    state.tick()
    assert len(sink.frames) == 8
    assert sink.frames[-1][8:10] != seq
    assert all(len(frame) <= 64 for frame in sink.frames)


def test_changed_source_does_not_bypass_frame_gap():
    state, sink, clock = publisher()
    state.tick()
    for now in (5, 10, 20, 39):
        clock.value = now
        state.note_position(12000 + now)
        state.tick()
        assert len(sink.frames) == 1
    clock.value = 40
    state.tick()
    assert len(sink.frames) == 2


def test_busy_radio_waits_without_sending_and_expired_parts_are_dropped():
    state, sink, clock = publisher()
    state.note_attributes({1: "T" * 96})
    state.tick()
    sink.ready = False
    clock.value = 5000
    state.tick()
    assert len(sink.frames) == 1
    sink.ready = True
    state.tick()
    assert len(sink.frames) == 2
    assert sink.frames[-1][10] == 0
    assert sink.frames[-1][8:10] != sink.frames[0][8:10]


def test_frequent_position_updates_do_not_starve_fragment_completion():
    state, sink, clock = publisher()
    state.note_attributes({1: "T" * 96, 2: "A" * 96, 3: "B" * 96})
    for now in range(0, 1501, 50):
        clock.value = now
        if now % 500 == 0:
            state.note_position(12000 + now)
        sink.ready = now % 150 == 0
        state.tick()
    seq = sink.frames[0][8:10]
    first_snapshot = [frame for frame in sink.frames if frame[8:10] == seq]
    assert [frame[10] for frame in first_snapshot] == list(range(7))


def test_wrap_safe_sample_age_and_pacing():
    clock = Clock((1 << 29) - 20)
    sink = Sink()
    state = StatePublisher(sink, clock=clock, session=1)
    state.set_transport(True, True, False)
    state.note_status(1)
    state.note_position(1000, 100000)
    state.tick()
    clock.value = 60
    assert state.snapshot()["position_age_ms"] == 80
    state.tick()
    assert len(sink.frames) == 1


class Radio:
    send_success = 0
    send_failure = 0

    def __init__(self):
        self.peers = []
        self.sent = []

    def send(self, frame, peer):
        self.sent.append((frame, peer))


class Module:
    def __init__(self):
        self.radio = Radio()

    def ESPNow(self):
        return self.radio

    class Peer:
        def __init__(self, mac):
            self.mac = mac


def test_sender_waits_for_completion_even_when_receiver_buffer_is_empty():
    mod = Module()
    remote = EspNowRemote(peer_mac="44:1B:F6:8A:C1:7C", espnow_module=mod, log=lambda _line: None)
    assert remote.setup()
    assert remote.send_state_frame(b"BMS2one")
    assert not remote.send_state_frame(b"BMS2two")
    assert len(mod.radio.sent) == 1
    mod.radio.send_failure += 1
    assert remote.send_state_frame(b"BMS2two")
    assert len(mod.radio.sent) == 2
    assert len(mod.radio.peers) == 1
    assert mod.radio.sent[0][1].mac == bytes.fromhex("441bf68ac17c")


def test_unconfigured_peer_cannot_broadcast_metadata():
    mod = Module()
    remote = EspNowRemote(peer_mac=None, espnow_module=mod, log=lambda _line: None)
    assert remote.setup()
    assert not remote.state_tx_enabled
    assert not remote.send_state_frame(b"BMS2data")
    assert not mod.radio.sent

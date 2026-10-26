"""BLE state is observed, bounded and shares the audio snapshot TX guard."""
import binascii

import pytest

import nextion
from remote.ble_status import BleStatusPublisher, encode_status
from remote.espnow_rx import EspNowRemote, MAX_RECENT_SEQS, parse_frame
from remote.state_tx import StatePublisher
from tests.test_remote_espnow import (OTHER_MAC_B, REMOTE_MAC_B, FakePacket,
                                     frame, make_remote)
from tests.test_remote_state_tx import Clock, Module


def status(mode=0, flags=11, error=0):
    return dict(mode=mode, intent_enabled=bool(flags & 1), ready=bool(flags & 2),
                connected=bool(flags & 4), advertising=bool(flags & 8), error=error)


class Backend:
    def __init__(self):
        self.value = status()
        self.requests = []
        self.accepted = True
        self.failed_observation = False

    def request_pause(self):
        self.requests.append("pause")
        return self.accepted

    def request_enable(self):
        self.requests.append("enable")
        return self.accepted

    def snapshot_status(self):
        if self.failed_observation:
            raise RuntimeError("observation failed")
        return self.value


class Sink:
    state_tx_enabled = True
    ready = True

    def __init__(self):
        self.frames = []

    def state_tx_ready(self):
        return self.ready

    def send_state_frame(self, data):
        self.frames.append(data)
        return True

    send_ble_status_frame = send_state_frame


def test_golden_bls1_is_exactly_nineteen_bytes_with_independent_crc():
    value = encode_status(status(), 0x12345678, 0x9ABC, 0x01020304)
    assert value.hex() == "424c5331123456789abc000b0102030400211d"
    assert len(value) == 19
    assert binascii.crc_hqx(value[:17], 0xFFFF) == int.from_bytes(value[17:], "big")


def test_status_mode_matrix_rejects_invented_pause_and_inconsistent_success():
    for mode in range(4):
        for flags in range(16):
            for error in range(8):
                valid = ((mode == 0 and flags & 1 and error == 0)
                         or (mode == 1 and not flags & 1 and error == 0)
                         or (mode == 2 and flags == 2 and error == 0)
                         or (mode == 3 and error != 0))
                if valid:
                    value = encode_status(status(mode, flags, error), 1, 1)
                    assert value[10:12] == bytes((mode, flags))
                else:
                    with pytest.raises(ValueError):
                        encode_status(status(mode, flags, error), 1, 1)


@pytest.mark.parametrize("field,value", [("mode", True), ("mode", 4), ("error", -1),
                                         ("error", 8), ("ready", 1), ("connected", None)])
def test_encoder_requires_typed_observations(field, value):
    observed = status()
    observed[field] = value
    with pytest.raises(ValueError):
        encode_status(observed, 1, 1)


def test_requests_queue_backend_intent_and_echo_receipt_even_when_backend_busy():
    clock, sink, backend = Clock(), Sink(), Backend()
    publisher = BleStatusPublisher(sink, backend, clock=clock, session=1)
    assert publisher.request(b"BLE_PAUSE", 42)
    assert backend.requests == ["pause"]
    assert sink.frames == []  # The callback does no BLE radio or status TX work.
    backend.accepted = False
    backend.value = status(3, 7, 7)
    assert not publisher.request(b"BLE_ENABLE", 43)
    assert publisher.tick()
    assert sink.frames[0][12:17] == b"\x00\x00\x00+\x07"
    assert not publisher.request(b"BT_POWER", 44)
    assert not publisher.request(b"BLE_ENABLE", True)
    assert backend.requests == ["pause", "enable"]


def test_status_heartbeat_request_bursts_and_sequence_wrap_stay_bounded():
    clock, sink = Clock(), Sink()
    publisher = BleStatusPublisher(sink, Backend(), clock=clock, session=1)
    publisher._sequence = 0xFFFF
    assert publisher.tick()
    assert sink.frames[0][8:10] == b"\0\0"
    for now in (1, 40, 500, 999):
        clock.value = now
        assert publisher.request(b"BLE_PAUSE", now)
        assert not publisher.tick()
    clock.value = 1000
    assert publisher.tick()
    assert len(sink.frames) == 2
    assert int.from_bytes(sink.frames[1][12:16], "big") == 999


def test_missing_observation_reports_error_not_paused_and_logs_once():
    clock, sink, backend, logs = Clock(), Sink(), Backend(), []
    backend.failed_observation = True
    publisher = BleStatusPublisher(sink, backend, clock=clock, session=1, log=logs.append)
    assert publisher.tick()
    clock.value = 1000
    assert publisher.tick()
    assert len(logs) == 1
    assert all(data[10:12] == b"\3\0" and data[16] == 6 for data in sink.frames)
    backend.failed_observation = False
    clock.value = 2000
    assert publisher.tick()
    assert sink.frames[-1][10:12] == b"\0\x0b"


def test_remote_only_commands_are_paired_deduplicated_and_keep_poll_api():
    remote, radio, _clock, _logs = make_remote()
    assert not ({b"BLE_PAUSE", b"BLE_ENABLE"} & nextion.TOKENS)
    assert parse_frame(frame(7, b"BLE_PAUSE")) == (7, b"BLE_PAUSE")
    radio.queue.extend([FakePacket(OTHER_MAC_B, frame(7, b"BLE_PAUSE")),
                        FakePacket(REMOTE_MAC_B, frame(8, b"BLE_PAUSE")),
                        FakePacket(REMOTE_MAC_B, frame(8, b"BLE_PAUSE")),
                        FakePacket(REMOTE_MAC_B, frame(9, b"BLE_ENABLE"))])
    assert remote.poll() == [b"BLE_PAUSE", b"BLE_ENABLE"]
    assert remote.take_ble_request(b"BLE_PAUSE") == 8
    assert remote.take_ble_request(b"BLE_ENABLE") == 9
    assert remote.take_ble_request(b"BLE_ENABLE") is None


def test_request_context_matches_repeated_tokens_and_remains_bounded():
    remote, _radio, clock, _logs = make_remote()
    for seq in range(1, MAX_RECENT_SEQS + 10):
        assert remote.accept(REMOTE_MAC_B, frame(seq, b"BLE_PAUSE"), clock()) == b"BLE_PAUSE"
    assert len(remote._ble_requests) == MAX_RECENT_SEQS
    assert remote.take_ble_request(b"BLE_ENABLE") is None
    assert [remote.take_ble_request(b"BLE_PAUSE") for _ in range(MAX_RECENT_SEQS)] == list(range(10, 26))


def test_both_frame_types_share_completion_backoff_and_configured_peer():
    module, clock = Module(), Clock()
    remote = EspNowRemote(peer_mac=REMOTE_MAC_B, espnow_module=module,
                          clock=clock, log=lambda _line: None)
    assert remote.setup()
    bls = encode_status(status(), 1, 1)
    assert remote.send_ble_status_frame(bls)
    assert not remote.send_state_frame(b"BMS2pending")
    assert not remote.send_ble_status_frame(bls)
    module.radio.send_success += 1
    assert remote.send_state_frame(b"BMS2next")
    assert not remote.send_ble_status_frame(bls)
    module.radio.send_failure += 1

    def fail(_frame, _peer):
        raise OSError("radio busy")

    module.radio.send = fail
    assert not remote.send_ble_status_frame(bls)
    assert not remote.send_state_frame(b"BMS2backoff")
    clock.value = 4
    assert not remote.state_tx_ready()
    clock.value = 5
    assert remote.state_tx_ready()
    assert not remote.send_ble_status_frame(b"BMS2" + bytes(15))
    assert not remote.send_ble_status_frame(bls + b"x")
    assert not remote.send_state_frame(bls)


def test_shared_scheduler_finishes_bms2_without_interleaving_and_one_frame_per_tick():
    clock, sink, backend = Clock(), Sink(), Backend()
    audio = StatePublisher(sink, clock=clock, session=1)
    audio.set_transport(True, True, False)
    audio.note_attributes({1: "T" * 96, 2: "A" * 96, 3: "B" * 96})
    auxiliary = BleStatusPublisher(sink, backend, clock=clock, session=2)
    assert audio.tick(auxiliary)
    assert sink.frames[-1][:4] == b"BLS1"
    for now in (0, 39):
        clock.value = now
        audio.tick(auxiliary)
        assert len(sink.frames) == 1
    # Make BLE due mid-snapshot. Already-started BMS2 fragments still win.
    for index in range(7):
        clock.value = 40 + index * 200
        before = len(sink.frames)
        assert audio.tick(auxiliary)
        assert len(sink.frames) == before + 1
        assert sink.frames[-1][:4] == b"BMS2"
        audio.tick(auxiliary)
        assert len(sink.frames) == before + 1
    clock.value += 40
    assert audio.tick(auxiliary)
    assert sink.frames[-1][:4] == b"BLS1"
    assert len(sink.frames) == 9


def test_disabled_or_backpressured_radio_does_not_read_ble_observations():
    sink, backend = Sink(), Backend()
    backend.snapshot_status = lambda: pytest.fail("read while radio cannot send")
    publisher = BleStatusPublisher(sink, backend, clock=Clock(), session=1)
    sink.state_tx_enabled = False
    assert not publisher.tick()
    sink.state_tx_enabled, sink.ready = True, False
    assert not publisher.tick()

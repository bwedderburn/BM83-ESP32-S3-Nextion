"""Wire and production dispatcher tests for authenticated-by-peer host intent."""
from copy import deepcopy
from types import SimpleNamespace
from unittest import mock

import pytest

from blehid.host_policy import NativeHostPolicy
from remote.ble_status import BleStatusPublisher, encode_status
from remote.host_policy import (HostPolicyPublisher, decode_command, decode_fragment, encode_command,
                                fragments, list_payload, number, status_payload)
from remote.now_playing import crc16
from tests.test_blehid_host_policy import Adapter, HOST, OTHER, connected, peer
from tests.test_main_mute import CODE
from tests.test_remote_espnow import OTHER_MAC_B, REMOTE_MAC_B, make_remote


class Clock:
    value = 0
    def __call__(self): return self.value


class Backend:
    def __init__(self):
        self.adapter = Adapter()
        self.owner = NativeHostPolicy(self.adapter)
        self.owner.tick()
    def snapshot_host_status(self): return self.owner.snapshot()
    def request_host_policy(self, mode, target=None, timeout_s=60): return self.owner.request(mode, target, timeout_s)
    def request_host_alias(self, target, alias): return self.owner.alias(target, alias)
    def request_pause(self): return self.owner.request("PAUSED")
    def request_enable(self): return self.owner.request("AUTO")


class Sink:
    state_tx_enabled = True
    def __init__(self):
        self.frames = []
        self.last_tx_ticket = 0
        self.receipts = {}
    def send_host_policy_frame(self, frame):
        self.frames.append(frame)
        self.last_tx_ticket += 1
        self.receipts[self.last_tx_ticket] = True
        return True
    def tx_completion(self, ticket): return self.receipts.get(ticket)


def packet(sink):
    decoded = [decode_fragment(frame) for frame in sink.frames]
    assert decoded and all(d is not None for d in decoded)
    first = decoded[0]
    assert len(decoded) == first[4] and [d[3] for d in decoded] == list(range(first[4]))
    assert all(d[:3] == first[:3] and d[4:6] == first[4:6] for d in decoded)
    return first[2], b"".join(d[-1] for d in decoded)


def drain_one(publisher, sink):
    sink.frames = []
    assert publisher.tick()
    count = decode_fragment(sink.frames[0])[4]
    for _ in range(count-1): assert publisher.tick()
    return packet(sink)


def recalc(body): return body+number(crc16(body), 2)


def admit(publisher, sink, client=2, request=0):
    kind, _body = drain_one(publisher, sink)
    assert kind == 1
    challenge = decode_fragment(sink.frames[0])[1]
    command = decode_command(encode_command(publisher.session, client, request, 0, challenge))
    assert not publisher.request_host(command)  # Read-only registration is not policy mutation.
    assert publisher.client == client and publisher.result == 4
    return command


def test_maximum_list_is_seven_strict_fragments_and_status_does_not_change_bls2():
    backend = Backend(); status = backend.owner.snapshot()
    status["peers"] = tuple(peer(("%016x" % (i+1)), alias="A"*24) for i in range(8))
    body = list_payload(status)
    assert len(body) == 278
    frames = fragments(body, 1, 7, 2)
    assert len(frames) == 7 and all(len(f) <= 64 for f in frames)
    assert b"".join(decode_fragment(f)[-1] for f in frames) == body
    assert len(status_payload(status)) == 63
    assert len(encode_status(dict(mode=2, error=0, ready=True, intent_enabled=False,
                                  connected=False, advertising=False), 1, 1)) == 21
    bad = bytearray(frames[0]); bad[14] = 8
    assert decode_fragment(recalc(bytes(bad[:-2]))) is None
    assert decode_fragment(frames[-1]+b"x") is None
    assert decode_fragment(frames[0][:-1]) is None


@pytest.mark.parametrize("payload", [b"\xff", b"name\0", b"name\n", "\u0085".encode(), b"A"*25])
def test_alias_rejects_malformed_utf8_controls_and_unbounded_values(payload):
    with pytest.raises(ValueError): encode_command(1, 2, 1, 4, 1, HOST, payload)


def test_command_rejects_stale_shape_zero_sessions_bad_crc_and_out_of_window_enrollment():
    for controller, client in ((0, 1), (1, 0)):
        with pytest.raises(ValueError): encode_command(controller, client, 1, 1)
    for timeout in (0, 4, 121, 65535):
        with pytest.raises(ValueError): encode_command(1, 2, 1, 3, payload=number(timeout, 2))
    good = encode_command(1, 2, 0xFFFFFFFF, 2, 1, HOST)
    assert decode_command(good)["target"] == HOST
    assert decode_command(good[:-1]+b"\0") is None
    assert decode_command(good+b"\0") is None


def test_policy_queue_is_not_completion_even_for_same_already_connected_target():
    backend, sink, clock = Backend(), Sink(), Clock()
    connected(backend.adapter); backend.owner.tick()
    publisher = HostPolicyPublisher(sink, backend, 1, clock)
    admit(publisher, sink)
    command = decode_command(encode_command(1, 2, 9, 2, 1, HOST))
    assert publisher.request_host(command)
    _, body = drain_one(publisher, sink)
    assert body[1:3] == b"\x01\x00" and body[11:15] == b"\0"*4
    assert not int.from_bytes(body[30:32], "big") & 1
    backend.owner.tick()  # Only enqueue; native still reports older connected operation1.
    clock.value = 1000
    _, body = drain_one(publisher, sink)
    assert int.from_bytes(body[11:15], "big") == 2 and not int.from_bytes(body[30:32], "big") & 1
    backend.adapter.status["operation_id"] = 2
    backend.owner.tick(); clock.value = 2000
    _, body = drain_one(publisher, sink)
    assert body[3:11] == number(2)+number(9) and int.from_bytes(body[30:32], "big") & 1


def test_paired_sender_dispatch_cancels_hold_but_never_touches_audio_or_calls_native_in_callback():
    remote, _radio, clock, _logs = make_remote()
    frame = encode_command(1, 2, 1, 1)
    assert remote.accept(OTHER_MAC_B, frame, clock()) is None
    token = remote.accept(REMOTE_MAC_B, frame, clock())
    assert token == b"BLE_HOST"
    backend, sink = Backend(), Sink()
    publisher = BleStatusPublisher(sink, backend, clock=Clock(), session=1)
    admit(publisher._hosts, sink)
    bm = mock.Mock()
    scope = dict(tokens=[token], remote=remote, ble_status=publisher, bm=bm, ble=mock.Mock(),
                 vol_hold_active="up", vol_repeat_count=5, dprint=lambda *_: None)
    exec(CODE, scope)  # nosec B102 - production local AST, never wire-provided code.
    assert scope["vol_hold_active"] is None and scope["vol_repeat_count"] == 0
    assert bm.mock_calls == [] and backend.adapter.calls == []
    backend.owner.tick()
    assert backend.adapter.calls == [("PAUSED", None, 60)]


def test_saved_peer_selection_supports_circuitpython_next_arity(monkeypatch):
    # CircuitPython has next(iterator), unlike CPython's optional default.
    def circuitpython_next(iterator):
        return next(iterator)

    monkeypatch.setattr("remote.host_policy.next", circuitpython_next, raising=False)
    backend, sink, clock = Backend(), Sink(), Clock()
    publisher = HostPolicyPublisher(sink, backend, 1, clock)
    admit(publisher, sink)
    missing = decode_command(encode_command(1, 2, 1, 2, 1, "0000000000000001"))
    assert not publisher.request_host(missing)
    assert (publisher.result, publisher.error) == (2, 5)
    backend.owner.tick()
    assert backend.adapter.calls == []

    select = decode_command(encode_command(1, 2, 2, 2, 1, OTHER))
    assert publisher.request_host(select)
    backend.owner.tick()
    assert backend.adapter.calls == [("AUTO", OTHER, 60)]


def test_host_action_exception_rejects_current_request_and_accepts_next(monkeypatch):
    backend, sink, clock = Backend(), Sink(), Clock()
    publisher = HostPolicyPublisher(sink, backend, 1, clock)
    admit(publisher, sink)
    select = decode_command(encode_command(1, 2, 1, 2, 1, HOST))
    with monkeypatch.context() as patch:
        patch.setattr(backend, "request_host_policy", mock.Mock(side_effect=TypeError("adapter error")))
        assert not publisher.request_host(select)
    _, body = drain_one(publisher, sink)
    assert body[1:3] == bytes((2, 10)) and body[3:11] == number(2)+number(1)
    backend.owner.tick()
    assert backend.adapter.calls == []

    select = decode_command(encode_command(1, 2, 2, 2, 1, HOST))
    assert publisher.request_host(select)
    backend.owner.tick()
    assert backend.adapter.calls == [("AUTO", HOST, 60)]


def test_replay_session_and_generation_checks_never_mutate_native_or_retarget():
    backend, sink, clock = Backend(), Sink(), Clock()
    publisher = HostPolicyPublisher(sink, backend, 1, clock)
    admit(publisher, sink, request=0xFFFFFFFE)
    select = decode_command(encode_command(1, 2, 0xFFFFFFFF, 2, 1, HOST))
    assert publisher.request_host(select)
    assert not publisher.request_host(select)
    stale_boot = decode_command(encode_command(99, 2, 0, 1))
    assert not publisher.request_host(stale_boot)
    assert publisher.request == 0xFFFFFFFF
    assert publisher.request_host(decode_command(encode_command(1, 2, 0, 1)))  # Wrap is valid.
    backend.owner.tick()
    assert backend.adapter.calls == [("PAUSED", None, 60)]  # Superseded queued Select never executes.
    backend.adapter.status["operation_id"] = 2
    backend.owner.tick()
    assert not publisher.request_host(decode_command(encode_command(1, 2, 1, 2, 999, OTHER)))
    assert publisher.error == 4
    assert len(backend.adapter.calls) == 1


def test_alias_saved_requires_observed_matching_commit_and_legacy_request_supersedes_correlation():
    backend, sink, clock = Backend(), Sink(), Clock()
    publisher = HostPolicyPublisher(sink, backend, 1, clock)
    admit(publisher, sink)
    assert not publisher.request_host(decode_command(encode_command(1, 2, 7, 4, 1, HOST, b"B-Intel")))
    backend.owner.tick()
    _, body = drain_one(publisher, sink)
    assert body[1] == 1
    backend.adapter.status.update(operation_id=2, policy_generation=2, bond_generation=2)
    backend.adapter.peers = [peer(alias="B-Intel", generation=2), peer(OTHER, generation=2)]
    backend.owner.tick()
    _, body = drain_one(publisher, sink)
    assert body[1] == 3 and int.from_bytes(body[11:15], "big") == 2
    publisher.note_legacy_request()
    _, body = drain_one(publisher, sink)
    assert body[3:11] == b"\0"*8  # A badge/old-panel request cannot complete the newer UI's operation.


def test_unknown_capability_reports_explicitly_unsupported_and_no_native_side_effect():
    backend, sink, clock = SimpleNamespace(snapshot_host_status=lambda: {"version": 0, "ready": False}), Sink(), Clock()
    publisher = HostPolicyPublisher(sink, backend, 1, clock)
    assert not publisher.request_host(decode_command(encode_command(1, 2, 1, 1)))
    _, body = drain_one(publisher, sink)
    assert body[0:3] == b"\0\x02\x01" and body[29] == 6


def test_auxiliary_flood_cannot_starve_or_split_production_audio_snapshot():
    from tests.test_remote_state_tx import publisher as media_publisher
    media, sink, clock = media_publisher()
    media.note_attributes({1: "T"*96, 2: "A"*96, 3: "B"*96})
    class Flood:
        def tick(self): sink.frames.append(b"auxiliary"); return True
    flood = Flood()
    for _ in range(100):
        media.tick(flood)
        clock.value += 40
    audio = [i for i, frame in enumerate(sink.frames) if frame.startswith(b"BMS2")]
    assert audio and audio[0] == 10
    # BMS2 fragments stay contiguous and a second snapshot gets its turn.
    assert any(b == a+1 for a, b in zip(audio, audio[1:]))
    assert sum(frame.startswith(b"BMS2") and frame[10] == 0 for frame in sink.frames) >= 2


def test_more_than_eight_panel_reboots_register_without_lifetime_lockout_or_old_replay():
    backend, sink, clock = Backend(), Sink(), Clock()
    publisher = HostPolicyPublisher(sink, backend, 1, clock)
    captured = None
    for client in range(2, 24):
        clock.value += 1100
        registration = admit(publisher, sink, client=client, request=1)
        if captured is None: captured = deepcopy(registration)
        assert len(publisher._retired_clients) <= 8 and len(publisher._challenges) <= 4
    assert publisher.client == 23
    assert not publisher.request_host(captured)  # Eviction does not make an old challenge fresh again.
    unknown_mutation = decode_command(encode_command(1, 24, 2, 1))
    assert not publisher.request_host(unknown_mutation)
    assert publisher.client == 23 and backend.adapter.calls == []
    # Even an old client can return legitimately, using a newly observed one-use challenge.
    clock.value += 1100
    admit(publisher, sink, client=2, request=1)
    assert publisher.client == 2


def test_handshake_retries_are_idempotent_and_do_not_supersede_a_later_policy_request():
    backend, sink, clock = Backend(), Sink(), Clock()
    publisher = HostPolicyPublisher(sink, backend, 1, clock)
    registration = admit(publisher, sink, request=1)
    assert not publisher.request_host(registration)
    assert publisher.result == 4 and publisher.request == 1
    select = decode_command(encode_command(1, 2, 2, 2, 1, HOST))
    assert publisher.request_host(select)
    assert not publisher.request_host(registration)
    assert publisher.result == 1 and publisher.request == 2
    backend.owner.tick()
    assert backend.adapter.calls == [("AUTO", HOST, 60)]


def test_unsent_failed_expired_or_consumed_status_is_never_a_new_client_challenge():
    backend, sink, clock = Backend(), Sink(), Clock()
    publisher = HostPolicyPublisher(sink, backend, 1, clock)
    assert publisher.tick()
    sink.receipts[1] = None  # Enqueued first fragment is not a successful STATUS packet.
    command = decode_command(encode_command(1, 2, 1, 0, 1))
    assert not publisher.request_host(command) and not publisher._established
    sink.receipts[1] = True
    assert publisher.tick()  # Second fragment queued; first successful alone is insufficient.
    sink.receipts[2] = False
    assert not publisher.request_host(command) and not publisher._established
    assert publisher._challenges == []
    # A successful packet whose conservative age exceeds 3 seconds is still rejected.
    sink2, clock2 = Sink(), Clock()
    publisher2 = HostPolicyPublisher(sink2, backend, 1, clock2)
    drain_one(publisher2, sink2)
    clock2.value = 3001
    assert not publisher2.request_host(command) and not publisher2._established
    # A consumed challenge cannot register another client within that same freshness window.
    sink3, clock3 = Sink(), Clock()
    publisher3 = HostPolicyPublisher(sink3, backend, 1, clock3)
    used = admit(publisher3, sink3)
    stolen = dict(used, client_session=3)
    assert not publisher3.request_host(stolen) and publisher3.client == 2


def test_rejected_unknown_mutation_does_not_change_active_policy_correlation():
    backend, sink, clock = Backend(), Sink(), Clock()
    publisher = HostPolicyPublisher(sink, backend, 1, clock)
    admit(publisher, sink)
    assert publisher.request_host(decode_command(encode_command(1, 2, 2, 1)))
    before = publisher.client, publisher.request, publisher.result
    assert not publisher.request_host(decode_command(encode_command(1, 77, 3, 3, payload=number(60, 2))))
    assert (publisher.client, publisher.request, publisher.result) == before
    _, reply = drain_one(publisher, sink)
    assert reply[1:3] == b"\x02\x0b" and reply[3:11] == number(77)+number(3)
    assert (publisher.client, publisher.request, publisher.result) == before
    backend.owner.tick()
    assert backend.adapter.calls == [("PAUSED", None, 60)]


def test_native_tx_callback_failure_cannot_be_relabelled_successful_status_handshake():
    from remote.espnow_rx import EspNowRemote
    from tests.test_remote_state_tx import Module
    backend, clock, module = Backend(), Clock(), Module()
    remote = EspNowRemote(peer_mac="44:1B:F6:8A:C1:7C", espnow_module=module, log=lambda _: None)
    assert remote.setup()
    publisher = HostPolicyPublisher(remote, backend, 1, clock)
    assert publisher.tick()
    first = remote.last_tx_ticket
    assert remote.tx_completion(first) is None
    module.radio.send_success += 1
    assert publisher.tick()
    second = remote.last_tx_ticket
    module.radio.send_failure += 1
    assert not publisher.request_host(decode_command(encode_command(1, 2, 1, 0, 1)))
    assert remote.tx_completion(first) is True and remote.tx_completion(second) is False
    assert not publisher._established and publisher._challenges == []

"""Host characterizations of shared ESP-NOW ownership, completion and recovery.

Lost-callback coverage records current blocking behavior; it is not a claim
that the transport has a timeout or a physical-radio liveness guarantee.
"""

import pytest

from remote.espnow_rx import ERROR_BACKOFF_S, EspNowRemote
from remote.host_policy import fragments


PEER = bytes.fromhex("441bf68ac17c")
SEND_METHODS = {
    "state": "send_state_frame", "ble": "send_ble_status_frame", "host": "send_host_policy_frame",
}


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class Radio:
    """Native-like counters advance only when the test supplies a callback."""

    def __init__(self, module, generation):
        self.module = module
        self.generation = generation
        self.peers = []
        self.attempts = []
        self.sent = []
        self.send_success = 0
        self.send_failure = 0
        self.send_errors = 0
        self.read_error = None
        self.deinit_failures = 0
        self.deinited = False
        self.complete_on_deinit = False

    def __bool__(self):
        return self.read_error is not None

    def read(self):
        if self.read_error is not None:
            raise self.read_error
        return None

    def send(self, frame, peer):
        assert not self.deinited
        self.attempts.append((frame, peer))
        if self.send_errors:
            self.send_errors -= 1
            raise OSError("fixture native send error")
        self.sent.append((frame, peer))

    def deinit(self):
        self.module.events.append(("deinit", self.generation))
        if self.deinit_failures:
            self.deinit_failures -= 1
            raise OSError("fixture deinit error")
        if self.complete_on_deinit:
            self.send_success += 1
        self.deinited = True
        self.module.events.append(("released", self.generation))


class Module:
    def __init__(self):
        self.radios = []
        self.events = []

    def ESPNow(self):
        radio = Radio(self, len(self.radios))
        self.radios.append(radio)
        self.events.append(("constructed", radio.generation))
        return radio

    class Peer:
        def __init__(self, mac):
            self.mac = mac


@pytest.fixture
def transport():
    module, clock = Module(), Clock()
    remote = EspNowRemote(peer_mac=PEER, espnow_module=module, clock=clock, log=lambda _line: None)
    assert remote.setup()
    return remote, module, clock


def send(remote, kind):
    frames = {
        "state": b"BMS2fixture state", "ble": b"BLS2" + bytes(17),
        "host": fragments(b"fixture host observation", 7, 1, 1)[0],
    }
    return getattr(remote, SEND_METHODS[kind])(frames[kind])


@pytest.mark.parametrize("first,blocked", [
    pytest.param("state", ("host",), id="state-to-host"),
    pytest.param("ble", ("host",), id="ble-to-host"),
    pytest.param("host", ("state", "ble", "host"), id="host-to-all"),
])
def test_host_policy_frames_share_one_native_owner_and_outstanding_slot(transport, first, blocked):
    remote, module, _clock = transport
    radio = module.radios[0]
    assert send(remote, first)
    ticket = remote.last_tx_ticket
    for kind in blocked:
        assert not send(remote, kind)
    assert remote.tx_completion(ticket) is None
    assert len(module.radios) == 1 and remote._radio is radio
    assert len(radio.sent) == len(radio.attempts) == 1
    assert len(radio.peers) == 1 and radio.sent[0][1] is radio.peers[0]
    radio.send_success += 1
    assert remote.tx_completion(ticket) is True
    assert send(remote, "host")
    assert len(radio.sent) == 2 and len(module.radios) == 1


def test_repeated_host_send_errors_restart_full_backoff_at_each_exact_boundary(transport):
    remote, module, clock = transport
    radio = module.radios[0]
    radio.send_errors = 2
    for attempts in (1, 2):
        assert not send(remote, "host")
        assert len(radio.attempts) == attempts
        deadline = clock.now + ERROR_BACKOFF_S
        assert remote.last_tx_ticket == remote.tx_frames == 0
        clock.now = deadline - 0.001
        for kind in SEND_METHODS:
            assert not send(remote, kind)
        assert len(radio.attempts) == attempts
        assert len(module.radios) == 1
        clock.now = deadline
    assert send(remote, "host")
    assert len(radio.attempts) == 3 and len(radio.sent) == 1
    assert remote.last_tx_ticket == remote.tx_frames == 1
    assert remote.tx_completion(1) is None


def test_rx_recovery_cancels_real_ticket_despite_late_old_owner_success(transport):
    remote, module, _clock = transport
    old = module.radios[0]
    assert send(remote, "host")
    cancelled = remote.last_tx_ticket
    old_peer = old.peers[0]
    old.complete_on_deinit = True
    old.read_error = ValueError("Invalid buffer")
    assert remote.poll() == ()
    assert old.deinited and old.send_success == 1
    assert remote.tx_completion(cancelled) is False
    fresh = module.radios[1]
    assert len(fresh.peers) == 1 and fresh.peers[0] is not old_peer
    assert send(remote, "ble")
    current = remote.last_tx_ticket
    assert current != cancelled and remote.tx_completion(current) is None
    assert fresh.sent[0][1] is fresh.peers[0]
    fresh.send_success += 1
    assert remote.tx_completion(current) is True
    assert remote.tx_completion(cancelled) is False
    assert module.events == [("constructed", 0), ("deinit", 0), ("released", 0), ("constructed", 1)]


def test_failed_deinit_blocks_tx_and_clears_peer_until_single_owner_recovery(transport):
    remote, module, clock = transport
    old = module.radios[0]
    assert send(remote, "host")
    old_peer = old.peers[0]
    old.deinit_failures = 1
    old.read_error = ValueError("Invalid buffer")
    assert remote.poll() == ()
    assert not remote.state_tx_enabled and remote._tx_peer is None
    assert remote._radio is old and not old.deinited
    deadline = clock.now + ERROR_BACKOFF_S
    clock.now = deadline - 0.001
    assert remote.poll() == ()
    for kind in SEND_METHODS:
        assert not send(remote, kind)
    assert len(module.radios) == 1 and len(old.attempts) == 1
    assert module.events == [("constructed", 0), ("deinit", 0)]
    clock.now = deadline
    assert remote.poll() == ()
    assert old.deinited and remote.enabled and remote.state_tx_enabled
    fresh = module.radios[1]
    assert sum(not radio.deinited for radio in module.radios) == 1
    assert fresh.peers[0] is not old_peer
    assert send(remote, "host")
    assert fresh.sent[0][1] is fresh.peers[0] and len(old.attempts) == 1
    assert module.events == [
        ("constructed", 0), ("deinit", 0), ("deinit", 0), ("released", 0), ("constructed", 1),
    ]


def test_current_behavior_lost_callback_keeps_all_frame_types_blocked_without_timeout(transport):
    """Current behavior, a known gap: a lost completion callback keeps every frame type blocked with no timeout."""
    remote, module, clock = transport
    radio = module.radios[0]
    assert send(remote, "host")
    ticket = remote.last_tx_ticket
    for elapsed in (ERROR_BACKOFF_S, 10 * ERROR_BACKOFF_S, 3600.0):
        clock.now = 100.0 + elapsed
        assert remote.poll() == ()
        assert not remote.state_tx_ready()
        for kind in SEND_METHODS:
            assert not send(remote, kind)
        assert remote.tx_completion(ticket) is None
    assert len(radio.attempts) == len(radio.sent) == remote.tx_frames == 1
    assert len(module.radios) == 1

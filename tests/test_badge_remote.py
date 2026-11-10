"""Authenticated BMW1 receiver, including interop with the real badge client.

All keys are throwaway test constants and every socket is an in-memory fake;
no network listener is opened.
"""
import binascii
import errno
import hashlib
import hmac
import json
from unittest.mock import patch

import pytest

from remote import badge_remote as module
from remote.badge_remote import BadgeRemote, ble_fields, np_from_snapshot
from utils.ticks import TICKS_MAX
from tests.test_badge_bm83_remote import FakeSocket, models, protocol, transport

KEY = bytes(range(32))
KEY_HEX = binascii.hexlify(KEY).decode()
CLIENT_ADDR = ("192.0.2.60", 50000)
PEER = ("192.0.2.50", 8767)


def profile(**changes):
    value = {"v": 1, "key": KEY_HEX, "port": 8767}
    value.update(changes)
    return value


def snapshot(**changes):
    value = {"power_on": True, "connected": True, "aux": False, "play_status": 1,
             "eq_index": 2, "duration_ms": 319000, "position_ms": 80000,
             "position_age_ms": 40, "clock_advancing": True,
             "title": "Grand Order", "artist": "Sithu Aye", "album": "Homebound"}
    value.update(changes)
    return value


def ble_status(mode=0, flags=11, error=0):
    return dict(mode=mode, intent_enabled=bool(flags & 1), ready=bool(flags & 2),
                connected=bool(flags & 4), advertising=bool(flags & 8), error=error)


class ServerSocket:
    """Controller side of an in-memory UDP pair with the badge FakeSocket."""

    def __init__(self, client=None):
        self.client = client
        self.inbox = []
        self.replies = []
        self.timeout = None
        self.bound = None
        self.closed = False
        self.fail_sends = 0
        self.drop_replies = 0

    def settimeout(self, value):
        self.timeout = value

    def bind(self, address):
        self.bound = address

    def recvfrom_into(self, buffer):
        if self.client is not None:
            while self.client.sent:
                wire, peer = self.client.sent.pop(0)
                assert peer == PEER
                self.inbox.append((wire, CLIENT_ADDR))
        if not self.inbox:
            raise OSError(11, "would block")
        wire, address = self.inbox.pop(0)
        size = min(len(wire), len(buffer))
        buffer[:size] = wire[:size]
        return size, address

    def sendto(self, wire, address):
        if self.fail_sends:
            self.fail_sends -= 1
            raise OSError(11, "would block")
        self.replies.append((wire, address))
        if self.drop_replies:
            self.drop_replies -= 1
            return len(wire)
        if self.client is not None:
            assert address == CLIENT_ADDR
            self.client.incoming.append((wire, PEER))
        return len(wire)

    def close(self):
        self.closed = True


class Unit:
    """Cached controller observations, as main.badge_state() returns them."""

    def __init__(self):
        self.np = np_from_snapshot(snapshot(), "Bass", "avrcp")
        self.ble = ble_status()
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.np, self.ble


def make_server(socket=None, logs=None, urandom=None, ticks=None, **changes):
    tick_clock = [0]
    server = BadgeRemote(profile=profile(**changes), socket=socket or ServerSocket(),
                         log=(logs.append if logs is not None else (lambda _m: None)),
                         clock=lambda: 0.0,
                         ticks=ticks if ticks is not None else lambda: tick_clock[0],
                         urandom=urandom or (lambda size: bytes(range(1, size + 1))))
    server.test_tick_clock = tick_clock
    assert server.setup()
    return server


def poll_at(server, state_fn, seconds):
    """Drive injected integer ticks independently of the legacy seconds API."""
    server.test_tick_clock[0] = round(seconds * 1000) & TICKS_MAX
    return server.poll(state_fn, seconds)


class Link:
    """Real badge transport.Remote talking to BadgeRemote through fakes."""

    def __init__(self, logs=None, **changes):
        self.client_socket = FakeSocket()
        with patch.object(transport.socket, "socket", return_value=self.client_socket):
            self.client = transport.Remote(PEER[0], PEER[1], KEY)
        self.server_socket = ServerSocket(self.client_socket)
        self.server = make_server(self.server_socket, logs, **changes)
        self.unit = Unit()
        self.ms = 0
        self.dispatched = []

    def run(self, steps=1, ms=25):
        for _ in range(steps):
            self.client.step(self.ms)
            self.dispatched += list(poll_at(self.server, self.unit, self.ms / 1000.0))
            self.client.step(self.ms)
            self.ms += ms

    def connect(self):
        self.run(3)
        assert self.client.unit == self.server.unit
        assert self.client.client and self.client.seq == 0

    def command(self, token):
        assert self.client.queue_command(token)
        self.run(3)


def request(server, message, key=KEY):
    return protocol.encode(key, message, 1200)


def replies(sock, key=KEY):
    return [protocol.decode(key, wire) for wire, _address in sock.replies]


# --- profile and primitives -------------------------------------------------

def test_profile_validation_never_echoes_secret_material():
    assert module.validate_profile(profile())["key"] == KEY
    assert module.validate_profile(profile(client_ip="192.0.2.60"))["client_ip"] == "192.0.2.60"
    for bad in (dict(v=2), dict(key=KEY_HEX.upper()), dict(key=KEY_HEX[:-2]), dict(port=80),
                dict(port=70000), dict(port=True), dict(client_ip="192.0.2.256"),
                dict(client_ip="192.0.2.01"), dict(allow_bond_erase="yes")):
        with pytest.raises(ValueError) as error:
            module.validate_profile(profile(**bad))
        assert KEY_HEX not in str(error.value)


def test_profile_file_absent_is_inert_and_oversize_is_rejected(tmp_path):
    assert module.load_profile(str(tmp_path / "missing.json")) is None
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile()) + " " * module.MAX_PROFILE_BYTES)
    with pytest.raises(ValueError):
        module.load_profile(str(path))
    path.write_text(json.dumps(profile()))
    assert module.load_profile(str(path))["port"] == 8767


def test_tag_is_standard_truncated_hmac_and_matches_badge_protocol():
    payload = '{"v":1,"type":"hello","nonce":"0011223344556677"}'.encode()
    expected = hmac.new(KEY, payload, hashlib.sha256).hexdigest()[:32].encode()
    assert module.tag(KEY, payload) == expected == protocol.mac(KEY, payload)
    message = {"v": 1, "type": "state", "title": "Sigur Rós \"Ágætis\"\n坂本龍一 🎵\\"}
    wire = module.encode(KEY, message)
    assert protocol.decode(KEY, wire) == message
    assert module.decode(KEY, protocol.encode(KEY, {"v": 1, "x": "\t"}), 256) == {"v": 1, "x": "\t"}


def test_decode_authenticates_before_parsing_and_bounds_requests():
    good = protocol.encode(KEY, {"v": 1, "type": "hello", "nonce": "00" * 8})
    assert module.decode(KEY, good) is not None
    assert module.decode(bytes(32), good) is None
    tampered = good[:-2] + b"9}"
    assert module.decode(KEY, tampered) is None
    assert module.decode(KEY, b"BMW1." + module.tag(KEY, b"not json") + b".not json") is None
    assert module.decode(KEY, b"BMW1." + module.tag(KEY, b'{"v":2}') + b'.{"v":2}') is None
    big = protocol.encode(KEY, {"v": 1, "pad": "x" * 300}, 1200)
    assert module.decode(KEY, big) is None
    assert module.decode(KEY, good[:39]) is None


# --- setup -------------------------------------------------------------------

def test_setup_without_profile_is_inert_and_opens_nothing(tmp_path):
    server = BadgeRemote(profile_path=str(tmp_path / "none.json"), log=lambda _m: None)
    assert not server.setup()
    assert not server.enabled
    assert server._seen_hellos is None
    assert server.poll(Unit(), 1.0) == ()


def test_setup_never_joins_wifi_and_requires_existing_connection():
    class Radio:
        connected = False
        ipv4_address = None

    class Pool:
        def socket(self, *_args):
            raise AssertionError("must not open a socket without Wi-Fi")

    logs = []
    server = BadgeRemote(profile=profile(), radio=Radio(), pool=Pool(), log=logs.append)
    assert not server.setup()
    assert logs == ["[BADGE] no existing Wi-Fi connection; badge remote disabled"]


def test_setup_binds_configured_port_nonblocking_with_nonzero_unit():
    sock = ServerSocket()
    draws = iter([bytes(4), b"\x00\x00\x00\x01", b"\x00\x00\x07", b"\x00\x00\x00\x09"])
    server = make_server(sock, urandom=lambda size: next(draws), port=9000)
    assert sock.bound == ("0.0.0.0", 9000)
    assert sock.timeout == 0
    assert server.unit == "00000001"


def test_bind_failure_closes_socket_and_stays_disabled():
    class Broken(ServerSocket):
        def bind(self, _address):
            raise OSError("port in use")

    sock = Broken()
    server = BadgeRemote(profile=profile(), socket=sock, log=lambda _m: None)
    assert not server.setup()
    assert sock.closed and not server.enabled


def test_invalid_profile_is_reported_without_contents():
    logs = []
    server = BadgeRemote(profile=profile(key="zz"), socket=ServerSocket(), log=logs.append)
    assert not server.setup()
    assert logs == ["[BADGE] invalid private profile; badge remote disabled"]


# --- interop with the real badge client --------------------------------------

def test_badge_client_authenticates_and_renders_receiver_state():
    link = Link()
    link.connect()
    link.run(60)  # STATUS polls once per second of badge time
    state = link.client.playback.state
    assert state["title"] == "Grand Order" and state["artist"] == "Sithu Aye"
    assert state["eq"] == "Bass" and state["src"] == "avrcp"
    assert link.client.ble.state["flags"] == 11
    assert link.dispatched == []
    assert link.unit.calls >= 1


@pytest.mark.parametrize("token", ["BT_PLAY", "BT_NEXT", "BT_PREV", "BT_MUTE", "BT_EQ",
                                   "BT_POWER", "BT_PAIR"])
def test_each_badge_command_dispatches_exactly_once(token):
    link = Link()
    link.connect()
    link.command(token)
    link.run(5)
    assert link.dispatched == [token.encode()]
    assert link.client.feedback == "%s: sent (reply)" % token


def test_volume_hold_dispatches_press_then_release():
    link = Link()
    link.connect()
    link.client.volume("BT_VOLUP")
    link.run(5)
    link.client.release_volume()
    link.run(5)
    assert link.dispatched == [b"BT_VOLUP_P", b"BT_VOLUP_R"]


def test_lost_reply_retry_is_answered_as_duplicate_without_reexecution():
    link = Link()
    link.connect()
    link.server_socket.drop_replies = 1
    assert link.client.queue_command("BT_NEXT")
    link.run(1)
    link.ms += 200  # badge retry interval
    link.run(3)
    assert link.dispatched == [b"BT_NEXT"]
    decoded = replies(link.server_socket)
    assert [m["dup"] for m in decoded if m.get("type") == "state"][-2:] == [False, True]


def test_send_failure_still_dispatches_and_retry_reports_duplicate():
    link = Link()
    link.connect()
    link.server_socket.fail_sends = 1
    assert link.client.queue_command("BT_PLAY")
    link.run(1)
    link.ms += 200
    link.run(3)
    assert link.dispatched == [b"BT_PLAY"]
    assert link.client.feedback == "BT_PLAY: sent (reply)"


def test_state_failure_still_dispatches_recorded_command():
    link = Link()
    link.connect()

    def broken():
        raise RuntimeError("snapshot")

    link.unit = broken
    assert link.client.queue_command("BT_PREV")
    link.run(1)
    assert link.dispatched == [b"BT_PREV"]


def test_receiver_failures_preserve_key_and_replay_identity_within_activation():
    class ReceiveErrorSocket(ServerSocket):
        fail_receive = False

        def recvfrom_into(self, buffer):
            if self.fail_receive:
                self.fail_receive = False
                raise OSError(errno.ECONNRESET, "injected receive failure")
            return super().recvfrom_into(buffer)

    sock = ReceiveErrorSocket()
    server = make_server(sock)
    unit = Unit()
    hello = request(server, {"v": 1, "type": "hello", "nonce": "11" * 8})
    sock.inbox.append((hello, CLIENT_ADDR))
    assert poll_at(server, unit, 0.0) == ()
    welcome = replies(sock)[-1]
    command = request(server, {"v": 1, "type": "cmd", "unit": server.unit,
                               "client": welcome["client"], "seq": 7, "token": "BT_NEXT"})
    sock.inbox.append((command, CLIENT_ADDR))
    assert poll_at(server, unit, 0.1) == [b"BT_NEXT"]

    def replay_identity():
        # Duplicate requests may refresh LRU touches, but not replay identity.
        clients = tuple((entry[0], entry[1], entry[3], entry[4], entry[5])
                        for entry in server._clients)
        return (server.unit, server._ble_session, server._next_client,
                server._hello_count, bytes(server._seen_hellos), clients)

    original_key = bytes(server._profile["key"])
    original_identity = replay_identity()

    def assert_identity():
        assert server._profile["key"] == original_key == KEY
        assert replay_identity() == original_identity
        assert server.enabled and server._socket is sock and not sock.closed

    reply_count = len(sock.replies)
    sock.fail_receive = True
    assert poll_at(server, unit, 0.2) == ()
    assert not sock.fail_receive and len(sock.replies) == reply_count
    assert_identity()

    forged = request(server, {"v": 1, "type": "hello", "nonce": "22" * 8},
                     key=bytes(reversed(KEY)))
    sock.inbox.append((forged, CLIENT_ADDR))
    assert poll_at(server, unit, 0.3) == ()
    assert len(sock.replies) == reply_count
    assert_identity()

    state_calls = []

    def broken_state():
        state_calls.append(True)
        raise RuntimeError("injected snapshot failure")

    sock.inbox.append((command, CLIENT_ADDR))
    assert poll_at(server, broken_state, 0.4) == ()
    assert state_calls == [True] and len(sock.replies) == reply_count
    assert_identity()

    sock.inbox.append((command, CLIENT_ADDR))
    sock.fail_sends = 1
    assert poll_at(server, unit, 0.5) == ()
    assert sock.fail_sends == 0 and len(sock.replies) == reply_count
    assert_identity()

    sock.inbox.extend([(hello, CLIENT_ADDR), (command, CLIENT_ADDR)])
    assert poll_at(server, unit, 0.6) == ()
    recovered_welcome, recovered_state = replies(sock)[-2:]
    assert recovered_welcome == welcome
    assert recovered_state["type"] == "state" and recovered_state["dup"] is True
    assert (recovered_state["unit"], recovered_state["client"], recovered_state["seq"]) == (
        welcome["unit"], welcome["client"], 7)
    assert_identity()


def test_wrong_key_client_gets_no_reply_and_never_authenticates():
    link = Link()
    link.client.key = bytes(32)
    link.run(30, ms=100)
    assert link.client.unit is None
    assert link.server_socket.replies == []
    assert link.dispatched == []


def test_receiver_restart_forces_rehello_and_command_is_not_silently_replayed():
    link = Link()
    link.connect()
    old_unit = link.server.unit
    link.server = make_server(link.server_socket, urandom=lambda size: bytes([9] * size))
    assert link.server.unit != old_unit
    assert link.client.queue_command("BT_NEXT")
    link.run(1)
    assert link.client.unit is None
    assert link.client.feedback == "BT_NEXT: unconfirmed after unit/client restart"
    link.run(60, ms=50)
    assert link.client.unit == link.server.unit
    assert link.dispatched == []


def test_bond_erase_is_refused_by_default_and_marked_denied():
    logs = []
    link = Link(logs)
    link.connect()
    link.command("BT_EBIND")
    assert link.dispatched == []
    last = [m for m in replies(link.server_socket) if m.get("type") == "state"][-1]
    assert last["denied"] is True and last["dup"] is False
    assert "[BADGE] BT_EBIND refused (bond erase is local-only)" in logs


def test_refused_bond_erase_retry_after_lost_reply_is_still_denied():
    link = Link()
    link.connect()
    link.server_socket.drop_replies = 1
    assert link.client.queue_command("BT_EBIND")
    link.run(1)
    link.ms += 200  # badge retry interval
    link.run(3)
    assert link.dispatched == []
    states = [m for m in replies(link.server_socket) if m.get("type") == "state"]
    assert [(m["dup"], m.get("denied")) for m in states[-2:]] == [(False, True), (True, True)]
    assert link.client.feedback == "Erase bonds: refused by audio unit"


def test_duplicate_of_accepted_command_is_not_marked_denied():
    link = Link()
    link.connect()
    link.server_socket.drop_replies = 1
    assert link.client.queue_command("BT_NEXT")
    link.run(1)
    link.ms += 200
    link.run(3)
    assert all("denied" not in m for m in replies(link.server_socket))


def test_bond_erase_requires_explicit_private_opt_in():
    link = Link(allow_bond_erase=True)
    link.connect()
    link.command("BT_EBIND")
    assert link.dispatched == [b"BT_EBIND"]
    assert all("denied" not in m for m in replies(link.server_socket))


@pytest.mark.parametrize("allow_bond_erase", [False, True])
@pytest.mark.parametrize("drop_reply", [False, True])
def test_network_retry_is_refused_without_dispatch_and_status_stays_available(
        allow_bond_erase, drop_reply):
    logs = []
    link = Link(logs, allow_bond_erase=allow_bond_erase)
    link.connect()
    unit = link.server.unit
    link.server_socket.drop_replies = int(drop_reply)
    assert link.client.queue_command("NET_RETRY")
    link.run(1)
    link.ms += 200
    link.run(3)
    assert link.dispatched == []
    states = [m for m in replies(link.server_socket) if m.get("type") == "state"]
    assert states and all(m.get("denied") is True for m in states)
    assert states[-1]["dup"] is drop_reply
    assert logs.count(
        "[BADGE] NET_RETRY refused (receiver retry unavailable; use local maintenance)") == 1
    link.command("STATUS")
    state = replies(link.server_socket)[-1]
    assert state["unit"] == unit and state["type"] == "state"
    assert "denied" not in state and state["np"]["title"] == "Grand Order"
    assert link.dispatched == []


def test_ble_pause_confirms_only_from_post_dispatch_observation():
    link = Link()
    link.connect()
    link.run(60)
    assert link.client.queue_command("BLE_PAUSE")
    link.run(1)
    assert link.dispatched == [b"BLE_PAUSE"]
    command_reply = [m for m in replies(link.server_socket) if m.get("type") == "state"][-1]
    assert command_reply["ble"] is None
    assert link.client.ble.result == "Waiting"
    origin = link.server.take_ble_request(b"BLE_PAUSE")
    assert origin == (link.client.client, link.client.seq)
    link.server.note_ble_request(origin)
    link.unit.ble = ble_status(mode=2, flags=2)
    link.run(60)
    assert link.client.ble.result == "Confirmed"


def test_ble_duplicate_with_lost_first_reply_waits_for_dispatch_observation():
    link = Link()
    link.connect()
    link.run(60)
    assert link.client.queue_command("BLE_PAUSE")
    link.client.step(link.ms)
    wire, peer = link.client_socket.sent[-1]
    link.client_socket.sent.append((wire, peer))
    link.server_socket.drop_replies = 1
    dispatched = poll_at(link.server, link.unit, link.ms / 1000.0)
    assert dispatched == [b"BLE_PAUSE"]
    command_replies = replies(link.server_socket)[-2:]
    assert [message["dup"] for message in command_replies] == [False, True]
    assert all(message["ble"] is None for message in command_replies)
    link.client.step(link.ms)
    assert link.client.ble.result == "Waiting"
    link.server.note_ble_request(link.server.take_ble_request(b"BLE_PAUSE"))
    link.unit.ble = ble_status(mode=2, flags=2)
    link.ms += 25
    link.run(60)
    assert link.client.ble.result == "Confirmed"


def test_status_from_another_client_in_ble_command_poll_suppresses_old_echo():
    sock = ServerSocket()
    server = make_server(sock)
    for index in (1, 2):
        sock.inbox.append((request(server, {"v": 1, "type": "hello",
                                            "nonce": "%016x" % index}), CLIENT_ADDR))
    poll_at(server, Unit(), 0.0)
    clients = [message["client"] for message in replies(sock)]
    for client, token in zip(clients, ("BLE_PAUSE", "STATUS")):
        sock.inbox.append((request(server, {"v": 1, "type": "cmd", "unit": server.unit,
                                            "client": client, "seq": 1, "token": token}), CLIENT_ADDR))
    assert poll_at(server, Unit(), 1.0) == [b"BLE_PAUSE"]
    assert all(message["ble"] is None for message in replies(sock)[-2:])


def test_ble_request_superseded_by_another_remote_is_reported():
    link = Link()
    link.connect()
    link.run(60)
    assert link.client.queue_command("BLE_ENABLE")
    link.run(1)
    link.server.note_ble_request(None)
    link.run(60)
    assert link.client.ble.result == "Unconfirmed (superseded)"


def test_ble_request_context_expires_after_its_loop_pass():
    link = Link()
    link.connect()
    assert link.client.queue_command("BLE_PAUSE")
    link.run(1)
    link.run(1)
    assert link.server.take_ble_request(b"BLE_PAUSE") is None


def test_ble_observation_failure_is_reported_as_error_mode():
    link = Link()
    link.connect()
    link.unit.ble = {}
    link.run(60)
    assert link.client.ble.state["mode"] == 3 and link.client.ble.state["error"] == 6


def test_ble_disabled_reports_null_ble():
    link = Link()
    link.unit.ble = None
    link.connect()
    link.run(60)
    assert link.client.ble.state is None
    assert link.client.playback.state is not None


# --- request filtering --------------------------------------------------------

def test_unauthenticated_malformed_and_oversize_input_is_dropped_silently():
    sock = ServerSocket()
    server = make_server(sock)
    hello = {"v": 1, "type": "hello", "nonce": "00" * 8}
    sock.inbox += [(request(server, hello, bytes(32)), CLIENT_ADDR),
                   (b"BMW1." + b"0" * 32 + b"." + b"{}" * 10, CLIENT_ADDR),
                   (b"x" * 20, CLIENT_ADDR),
                   (protocol.encode(KEY, {"v": 1, "pad": "x" * 300}, 1200), CLIENT_ADDR),
                   (request(server, {"v": 1, "type": "hello", "nonce": "short"}), CLIENT_ADDR),
                   (request(server, {"v": 1, "type": "cmd", "client": 1, "seq": 1,
                                     "unit": server.unit, "token": "FORMAT"}), CLIENT_ADDR)]
    for step in range(3):
        assert poll_at(server, Unit(), step * 0.05) == ()
    assert sock.replies == []
    assert server._stats[1] == 6


def test_client_ip_lock_drops_other_senders():
    sock = ServerSocket()
    server = make_server(sock, client_ip="192.0.2.61")
    hello = {"v": 1, "type": "hello", "nonce": "00" * 8}
    sock.inbox.append((request(server, hello), CLIENT_ADDR))
    sock.inbox.append((request(server, hello), ("192.0.2.61", 50001)))
    poll_at(server, Unit(), 0.0)
    assert [address for _wire, address in sock.replies] == [("192.0.2.61", 50001)]


def test_stale_and_zero_sequences_are_ignored():
    sock = ServerSocket()
    server = make_server(sock)
    sock.inbox.append((request(server, {"v": 1, "type": "hello", "nonce": "11" * 8}), CLIENT_ADDR))
    poll_at(server, Unit(), 0.0)
    client = replies(sock)[0]["client"]

    def cmd(seq, token="BT_NEXT"):
        return (request(server, {"v": 1, "type": "cmd", "unit": server.unit, "client": client,
                                 "seq": seq, "token": token}), CLIENT_ADDR)

    sock.inbox += [cmd(5), cmd(4)]
    assert poll_at(server, Unit(), 1.0) == [b"BT_NEXT"]
    sock.inbox += [cmd(0), cmd(5)]
    assert poll_at(server, Unit(), 2.0) == ()
    assert [m.get("dup") for m in replies(sock)[1:]] == [False, True]


def test_poll_is_rate_limited_and_bounded_per_pass():
    sock = ServerSocket()
    server = make_server(sock)
    for index in range(5):
        sock.inbox.append((request(server, {"v": 1, "type": "hello",
                                            "nonce": "%016x" % index}), CLIENT_ADDR))
    poll_at(server, Unit(), 0.0)
    assert len(sock.replies) == 2
    poll_at(server, Unit(), 0.01)
    assert len(sock.replies) == 2
    poll_at(server, Unit(), 0.03)
    assert len(sock.replies) == 4


def test_client_table_is_bounded_with_least_recent_eviction():
    sock = ServerSocket()
    server = make_server(sock)
    now = 0.0
    for index in range(module.MAX_CLIENTS + 1):
        sock.inbox.append((request(server, {"v": 1, "type": "hello",
                                            "nonce": "%016x" % index}), CLIENT_ADDR))
        poll_at(server, Unit(), now)
        now += 0.05
    clients = [m["client"] for m in replies(sock)]
    assert len(server._clients) == module.MAX_CLIENTS
    sock.inbox.append((request(server, {"v": 1, "type": "cmd", "unit": server.unit,
                                        "client": clients[0], "seq": 1, "token": "STATUS"}),
                       CLIENT_ADDR))
    poll_at(server, Unit(), now)
    assert replies(sock)[-1] == {"v": 1, "type": "rehello", "client": clients[0], "seq": 1}


def test_hello_retries_reuse_client_and_keep_its_sequence_watermark():
    sock = ServerSocket()
    server = make_server(sock)
    hello = request(server, {"v": 1, "type": "hello", "nonce": "11" * 8})
    sock.inbox.append((hello, CLIENT_ADDR))
    poll_at(server, Unit(), 0.0)
    client = replies(sock)[-1]["client"]
    command = request(server, {"v": 1, "type": "cmd", "unit": server.unit,
                               "client": client, "seq": 5, "token": "BT_PLAY"})
    sock.inbox.append((command, CLIENT_ADDR))
    assert poll_at(server, Unit(), 1.0) == [b"BT_PLAY"]
    for step in range(6):
        sock.inbox.append((hello, CLIENT_ADDR))
        poll_at(server, Unit(), 2.0 + step)
        assert replies(sock)[-1]["client"] == client
    assert len(server._clients) == 1
    sock.inbox.append((command, CLIENT_ADDR))
    assert poll_at(server, Unit(), 9.0) == ()
    assert replies(sock)[-1]["dup"] is True


def test_evicted_hello_replay_cannot_evict_live_clients_again():
    sock = ServerSocket()
    server = make_server(sock)
    hellos = [request(server, {"v": 1, "type": "hello", "nonce": "%016x" % index})
              for index in range(module.MAX_CLIENTS + 1)]
    for index, hello in enumerate(hellos):
        sock.inbox.append((hello, CLIENT_ADDR))
        poll_at(server, Unit(), float(index))
    clients = [entry[0] for entry in server._clients]
    count = len(sock.replies)
    for index in range(6):
        sock.inbox.append((hellos[0], CLIENT_ADDR))
        poll_at(server, Unit(), 10.0 + index)
    assert len(sock.replies) == count
    assert [entry[0] for entry in server._clients] == clients


def test_full_nonce_ledger_refuses_new_handshakes_but_keeps_retry_and_volume_release():
    sock = ServerSocket()
    server = make_server(sock)
    assert module.MAX_HANDSHAKES == 64
    assert len(server._seen_hellos) == 512
    hellos = [request(server, {"v": 1, "type": "hello", "nonce": "%016x" % index})
              for index in range(module.MAX_HANDSHAKES + 1)]
    for index, hello in enumerate(hellos[:-1]):
        sock.inbox.append((hello, CLIENT_ADDR))
        poll_at(server, Unit(), float(index))
    assert server._hello_count == module.MAX_HANDSHAKES
    clients = [entry[0] for entry in server._clients]
    client = clients[-1]

    def command(seq, token):
        return request(server, {"v": 1, "type": "cmd", "unit": server.unit,
                                "client": client, "seq": seq, "token": token})

    sock.inbox.append((command(1, "BT_VOLUP_P"), CLIENT_ADDR))
    assert poll_at(server, Unit(), 100.0) == [b"BT_VOLUP_P"]
    reply_count = len(sock.replies)
    # Both a brand-new nonce at capacity and the oldest retired nonce fail shut.
    sock.inbox.extend([(hellos[-1], CLIENT_ADDR), (hellos[0], CLIENT_ADDR)])
    assert poll_at(server, Unit(), 101.0) == ()
    assert len(sock.replies) == reply_count
    assert [entry[0] for entry in server._clients] == clients
    # Retrying the current HELLO still returns its original client and watermark.
    sock.inbox.append((hellos[-2], CLIENT_ADDR))
    poll_at(server, Unit(), 102.0)
    assert replies(sock)[-1]["client"] == client
    assert server._client(client)[1] == 1
    sock.inbox.append((command(2, "BT_VOLUP_R"), CLIENT_ADDR))
    assert poll_at(server, Unit(), 103.0) == [b"BT_VOLUP_R"]
    sock.inbox.append((command(1, "BT_VOLUP_P"), CLIENT_ADDR))
    assert poll_at(server, Unit(), 104.0) == ()
    # Calling the already-open setup path must not reset replay state.
    assert server.setup()
    assert server._hello_count == module.MAX_HANDSHAKES
    assert server._client(client)[1] == 2


@pytest.mark.parametrize("start", [0, (1 << 29) - 10, 1000])
def test_integer_tick_poll_gate_ignores_coarse_monotonic_and_handles_wrap(start):
    ticks = [start]
    sock = ServerSocket()
    server = make_server(sock, ticks=lambda: ticks[0])
    for index in range(6):
        sock.inbox.append((request(server, {"v": 1, "type": "hello",
                                            "nonce": "%016x" % index}), CLIENT_ADDR))
    # Single-precision monotonic may have one value across many 20ms windows.
    coarse_seconds = 6 * 24 * 60 * 60.0
    server.poll(Unit(), coarse_seconds)
    assert len(sock.replies) == 2
    ticks[0] = (start + 19) & ((1 << 29) - 1)
    server.poll(Unit(), coarse_seconds)
    assert len(sock.replies) == 2
    ticks[0] = (start + 20) & ((1 << 29) - 1)
    server.poll(Unit(), coarse_seconds)
    assert len(sock.replies) == 4
    ticks[0] = (start + (1 << 28) + 40) & ((1 << 29) - 1)
    server.poll(Unit(), coarse_seconds)
    assert len(sock.replies) == 6


def test_default_poll_gate_uses_hardware_ticks_despite_legacy_now_argument():
    ticks = [100]
    sock = ServerSocket()
    with patch.object(module, "ticks_ms", side_effect=lambda: ticks[0]):
        server = BadgeRemote(profile=profile(), socket=sock, log=lambda _m: None)
    assert server.setup()
    for index in range(4):
        sock.inbox.append((request(server, {"v": 1, "type": "hello",
                                            "nonce": "%016x" % index}), CLIENT_ADDR))
    server.poll(Unit(), 500000.0)
    ticks[0] += 20
    server.poll(Unit(), 500000.0)
    assert len(sock.replies) == 4


def test_logs_never_contain_key_or_peer_address():
    logs = []
    link = Link(logs)
    link.connect()
    link.command("BT_NEXT")
    link.command("BT_EBIND")
    link.server._tick_stats(1000.0)
    text = "\n".join(logs)
    assert KEY_HEX not in text and CLIENT_ADDR[0] not in text
    assert any(line.startswith("[BADGE] rx ok=") for line in logs)


# --- state mapping and size bound ----------------------------------------------

def test_np_mapping_reports_unknown_values_honestly():
    value = np_from_snapshot(snapshot(play_status=None, eq_index=None, duration_ms=None,
                                      position_ms=None, position_age_ms=12,
                                      title=b"Bj\xc3\xb6rk", artist=None, album=None),
                             "Flat", "mac")
    assert value["play_status"] == 255 and value["eq_index"] == 0
    assert value["position_age_ms"] is None and value["duration_ms"] is None
    assert value["title"] == "Björk" and value["artist"] == "" and value["src"] == "mac"
    assert models.valid_np(value)
    assert np_from_snapshot(snapshot(play_status=7), "Flat", "avrcp")["play_status"] == 255
    assert np_from_snapshot(snapshot(play_status=True), "Flat")["play_status"] == 255
    assert np_from_snapshot(snapshot(title="", artist=""), "Flat", "mac")["src"] == ""
    assert np_from_snapshot(snapshot(), "Flat", "guess")["src"] == ""
    assert np_from_snapshot(snapshot(), "Flat")["src"] == ""
    assert np_from_snapshot(snapshot(position_ms=0x1_0000_0000), "Flat")["position_ms"] is None


def test_worst_case_state_reply_fits_badge_limit_and_validates():
    nasty = "\"\\\x01🎵坂本龍一 Ágætis byrjun " * 20
    value = np_from_snapshot(snapshot(title=nasty, artist=nasty, album=nasty,
                                      duration_ms=0xFFFFFFFE, position_ms=0xFFFFFFFE,
                                      position_age_ms=0xFFFFFFFE, eq_index=255, play_status=255),
                             "E" * 80, "avrcp")
    assert models.valid_np(value)
    for name in ("title", "artist", "album"):
        assert len(value[name]) <= 96
        assert len(module.json_text(value[name]).encode()) <= module.TEXT_JSON_BYTES
    message = {"v": 1, "type": "state", "unit": "ffffffff", "client": 0xFFFFFFFF,
               "seq": 0xFFFFFFFF, "dup": False, "np": value,
               "ble": {"session": 0xFFFFFFFF, "sequence": 0xFFFFFFFF, "mode": 3, "flags": 15,
                       "error": 7, "req_client": 0xFFFFFFFF, "req_seq": 0xFFFFFFFF},
               "denied": True}
    wire = module.encode(KEY, message)
    assert len(wire) <= 1200
    assert protocol.decode(KEY, wire)["np"] == value


def test_ble_fields_accepts_only_consistent_observations():
    assert ble_fields(ble_status()) == (0, 11, 0)
    assert ble_fields(ble_status(2, 2)) == (2, 2, 0)
    assert ble_fields(ble_status(3, 0, 6)) == (3, 0, 6)
    for bad in (ble_status(0, 2), ble_status(2, 3), ble_status(3, 2, 0), ble_status(1, 3),
                dict(ble_status(), ready=1), None):
        with pytest.raises(ValueError):
            ble_fields(bad)


# --- main-loop placement --------------------------------------------------------

def test_main_services_badge_after_wifi_and_before_shared_dispatch():
    import ast
    from tests.test_main_mute import TREE

    main = next(node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name == "main")

    def calls(node, owner, attr=None):
        return [call.lineno for call in ast.walk(node) if isinstance(call, ast.Call) and (
            (attr is None and isinstance(call.func, ast.Name) and call.func.id == owner)
            or (attr is not None and isinstance(call.func, ast.Attribute) and call.func.attr == attr
                and isinstance(call.func.value, ast.Name) and call.func.value.id == owner))]

    assert calls(main, "start_artwork_wifi")[0] < calls(main, "badge_remote", "setup")[0]
    loop = next(node for node in main.body if isinstance(node, ast.While))
    dispatch = next(node for node in ast.walk(loop) if isinstance(node, ast.For)
                    and isinstance(node.target, ast.Name) and node.target.id == "tok")
    (badge_poll,) = calls(loop, "badge_remote", "poll")
    assert calls(loop, "remote_poll")[0] < badge_poll < dispatch.lineno
    # Replies report cached observations only; they never drive the BM83 UART.
    state = next(node for node in ast.walk(main) if isinstance(node, ast.FunctionDef)
                 and node.name == "badge_state")
    assert not [node for node in ast.walk(state) if isinstance(node, ast.Name) and node.id == "bm"]

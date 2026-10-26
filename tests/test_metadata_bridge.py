"""Bounded UDP metadata reception without radios, credentials, or hardware."""
import json
from types import SimpleNamespace

import pytest

from remote import metadata_bridge as module


TOKEN = "a1" * 32
SESSION = "b2" * 16
OTHER_SESSION = "c3" * 16


def packet(**changes):
    value = {"v": 1, "token": TOKEN, "session": SESSION, "seq": 1,
             "state": "playing", "title": "Kind", "artist": "Plini", "album": "Sunhead - EP",
             "duration_ms": 180000, "position_ms": 12000}
    value.update(changes)
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


class Socket:
    def __init__(self):
        self.pending = []
        self.reads = 0
        self.timeout = None
        self.bound = None
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def bind(self, address):
        self.bound = address

    def recvfrom_into(self, buffer):
        self.reads += 1
        if not self.pending:
            raise OSError(11, "would block")
        value = self.pending.pop(0)
        if isinstance(value, Exception):
            raise value
        raw, host = value
        size = min(len(raw), len(buffer))
        buffer[:size] = raw[:size]
        return size, (host, 54321)

    def close(self):
        self.closed = True


def receiver(**profile_changes):
    clock = SimpleNamespace(now=100.0)
    sock = Socket()
    profile = {"v": 1, "token": TOKEN, "port": 8766}
    profile.update(profile_changes)
    logs = []
    bridge = module.MetadataBridge(clock=lambda: clock.now, log=logs.append,
                                   profile=profile, socket=sock)
    bridge._test_clock = clock
    assert bridge.setup()
    assert sock.timeout == 0
    assert sock.bound == ("0.0.0.0", 8766)
    return bridge, sock, clock, logs


def send(bridge, sock, raw=None, host="192.168.1.4"):
    sock.pending.append((packet() if raw is None else raw, host))
    # Each observation is a distinct receive window; explicit throttle tests
    # below exercise closer calls without moving a real host clock.
    bridge._test_clock.now += 0.1
    bridge.poll()


def test_valid_snapshot_preserves_unicode_and_source_timing_without_extrapolation():
    bridge, sock, clock, _logs = receiver()
    send(bridge, sock, packet(title="Flâneur", artist="Björk", position_ms=12000))
    clock.now += 3
    assert bridge.snapshot() == {"title": "Flâneur", "artist": "Björk", "album": "Sunhead - EP",
                                 "state": "playing", "duration_ms": 180000, "position_ms": 12000}


@pytest.mark.parametrize("changes", [
    {"v": 2}, {"v": True}, {"token": "wrong"}, {"token": 123},
    {"session": "not-hex"}, {"session": ""}, {"session": 1},
    {"seq": -1}, {"seq": True}, {"seq": 1.0}, {"seq": "2"},
    {"state": "buffering"}, {"state": None}, {"state": []},
    {"title": 123}, {"artist": None}, {"album": []},
    {"title": "x" * 257}, {"title": "é" * 129}, {"artist": "bad\x00artist"},
    {"album": "line\nbreak"}, {"title": "\x1b[2J"},
    {"duration_ms": -1}, {"position_ms": -1}, {"position_ms": True},
    {"duration_ms": 1.5}, {"duration_ms": module.MAX_TIME_MS + 1},
    {"position_ms": module.MAX_TIME_MS + 1},
])
def test_bad_packets_do_not_replace_fresh_metadata_or_consume_sequence(changes):
    bridge, sock, clock, _logs = receiver()
    send(bridge, sock)
    before = dict(bridge.snapshot())
    clock.now += 2
    send(bridge, sock, packet(**dict({"seq": 2}, **changes)))
    assert bridge.snapshot() == before
    # A malformed packet carrying a higher sequence must not block the next
    # valid source observation with that same sequence.
    send(bridge, sock, packet(seq=2, title="New track"))
    assert bridge.snapshot()["title"] == "New track"


@pytest.mark.parametrize("raw", [b"", b"{", b"[]", b"null", b"\xff\xfe", b" " * 1401,
                                 b"{" + b" " * 10000])
def test_non_packets_and_oversize_datagrams_are_ignored(raw):
    bridge, sock, _clock, _logs = receiver()
    send(bridge, sock, raw)
    assert bridge.snapshot() is None
    send(bridge, sock)
    assert bridge.snapshot()["title"] == "Kind"


def test_utf8_byte_limit_accepts_exact_boundary_and_optional_times():
    bridge, sock, _clock, _logs = receiver()
    send(bridge, sock, packet(title="é" * 128, duration_ms=None, position_ms=None))
    assert bridge.snapshot()["title"] == "é" * 128
    assert bridge.snapshot()["duration_ms"] is None
    assert bridge.snapshot()["position_ms"] is None


def test_poll_is_bounded_even_when_datagrams_keep_arriving():
    bridge, sock, _clock, _logs = receiver()
    sock.pending.extend((packet(seq=seq, title="Track %d" % seq), "192.168.1.4") for seq in range(1, 10))
    bridge.poll()
    assert sock.reads == 2
    assert len(sock.pending) == 7
    assert bridge.snapshot()["title"] == "Track 2"


def test_socket_poll_throttles_would_block_checks_and_burst_processing():
    bridge, sock, clock, _logs = receiver()
    clock.now = 0
    sock.pending.extend((packet(seq=seq, title="Track %d" % seq), "192.168.1.4") for seq in range(1, 10))
    bridge.poll()
    assert sock.reads == 2
    clock.now = 0.049
    bridge.poll()
    assert sock.reads == 2
    assert bridge.snapshot()["title"] == "Track 2"
    clock.now = 0.051
    bridge.poll()
    assert sock.reads == 4
    assert bridge.snapshot()["title"] == "Track 4"


def test_clock_rollback_does_not_stall_socket_polling():
    bridge, sock, clock, _logs = receiver()
    send(bridge, sock)
    clock.now = 1.0
    sock.pending.append((packet(seq=2, title="Fresh after wrap"), "192.168.1.4"))
    bridge.poll()
    assert bridge.snapshot()["title"] == "Fresh after wrap"


def test_duplicate_and_old_sequences_do_not_replace_data_or_extend_expiry():
    bridge, sock, clock, _logs = receiver()
    send(bridge, sock, packet(seq=10))
    clock.now += 7
    send(bridge, sock, packet(seq=10, title="Replay"))
    send(bridge, sock, packet(seq=9, title="Older"))
    assert bridge.snapshot()["title"] == "Kind"
    clock.now += 1
    assert bridge.snapshot() is None
    send(bridge, sock, packet(seq=11, title="Fresh"))
    assert bridge.snapshot()["title"] == "Fresh"


def test_sender_restart_accepts_new_session_and_rejects_retired_session():
    bridge, sock, _clock, _logs = receiver()
    send(bridge, sock, packet(seq=100))
    send(bridge, sock, packet(session=OTHER_SESSION, seq=0, title="Restarted"))
    assert bridge.snapshot()["title"] == "Restarted"
    send(bridge, sock, packet(seq=101, title="Delayed old session"))
    assert bridge.snapshot()["title"] == "Restarted"


def test_session_replay_memory_is_bounded():
    bridge, sock, _clock, _logs = receiver()
    for session in range(30):
        send(bridge, sock, packet(session="%032x" % session))
    assert len(bridge._retired) == module.MAX_RETIRED_SESSIONS


def test_reset_discards_cache_but_cannot_replay_a_pre_disconnect_packet():
    bridge, sock, _clock, _logs = receiver()
    send(bridge, sock, packet(seq=10))
    bridge.reset()
    assert bridge.snapshot() is None
    send(bridge, sock, packet(seq=10))
    assert bridge.snapshot() is None
    send(bridge, sock, packet(seq=11))
    assert bridge.snapshot()["title"] == "Kind"


@pytest.mark.parametrize("changes", [{"state": "stopped"}, {"title": "", "artist": ""},
                                     {"title": "  ", "artist": " "}])
def test_source_stop_or_empty_track_immediately_clears_old_track(changes):
    bridge, sock, _clock, _logs = receiver()
    send(bridge, sock)
    send(bridge, sock, packet(**dict({"seq": 2}, **changes)))
    assert bridge.snapshot() is None


def test_paused_source_retains_text_with_fresh_keepalives():
    bridge, sock, clock, _logs = receiver()
    send(bridge, sock, packet(state="paused"))
    clock.now += 7
    assert bridge.snapshot()["state"] == "paused"
    send(bridge, sock, packet(seq=2, state="paused"))
    clock.now += 7
    assert bridge.snapshot()["title"] == "Kind"


def test_invalid_packets_cannot_refresh_ttl_and_expired_text_cannot_resurrect_on_clock_wrap():
    bridge, sock, clock, _logs = receiver()
    send(bridge, sock)
    clock.now += 7
    send(bridge, sock, packet(seq=2, token="wrong"))
    clock.now += 1
    assert bridge.snapshot() is None
    clock.now = 101
    assert bridge.snapshot() is None


def test_clock_rollback_invalidates_snapshot():
    bridge, sock, clock, _logs = receiver()
    send(bridge, sock)
    clock.now -= 1
    assert bridge.snapshot() is None


def test_configured_source_ip_filter_does_not_advance_replay_sequence():
    bridge, sock, _clock, _logs = receiver(host_ip="192.168.1.4")
    send(bridge, sock, packet(seq=10), host="192.168.1.5")
    assert bridge.snapshot() is None
    send(bridge, sock, packet(seq=10), host="192.168.1.4")
    assert bridge.snapshot()["title"] == "Kind"


def test_socket_receive_failure_preserves_uart_independent_operation_and_recovers():
    bridge, sock, clock, _logs = receiver()
    send(bridge, sock)
    sock.pending.append(OSError("radio disconnected"))
    clock.now += 1
    bridge.poll()
    assert bridge.snapshot()["title"] == "Kind"
    clock.now += 8
    assert bridge.snapshot() is None
    send(bridge, sock, packet(seq=2, title="Reconnected"))
    assert bridge.snapshot()["title"] == "Reconnected"


@pytest.mark.parametrize("changes", [{"v": 2}, {"v": True}, {"token": "short"},
                                     {"token": "z" * 64}, {"port": True}, {"port": 80},
                                     {"port": 65536}, {"host_ip": "192.168.1.999"},
                                     {"host_ip": "192.168.01.4"}, {"host_ip": 4}])
def test_invalid_private_profile_never_enables_socket_or_leaks_values(changes):
    profile = {"v": 1, "token": TOKEN, "port": 8766}
    profile.update(changes)
    sock, logs = Socket(), []
    bridge = module.MetadataBridge(profile=profile, socket=sock, log=logs.append)
    assert not bridge.setup()
    assert sock.bound is None
    assert TOKEN not in str(logs)
    bridge.poll()
    assert bridge.snapshot() is None


def test_missing_profile_is_quiet_and_does_not_import_wifi(tmp_path):
    logs = []
    bridge = module.MetadataBridge(profile_path=str(tmp_path / "missing"), log=logs.append)
    assert not bridge.setup()
    assert logs == []
    bridge.poll()
    assert bridge.snapshot() is None


@pytest.mark.parametrize("raw", [b"{", b" " * 513])
def test_invalid_or_oversized_profile_disables_bridge(tmp_path, raw):
    path = tmp_path / "profile"
    path.write_bytes(raw)
    bridge = module.MetadataBridge(profile_path=str(path), log=lambda _message: None)
    assert not bridge.setup()


def test_profile_file_is_read_at_setup_and_default_port_is_supported(tmp_path):
    path = tmp_path / "profile"
    path.write_text(json.dumps({"v": 1, "token": TOKEN}))
    sock = Socket()
    bridge = module.MetadataBridge(profile_path=str(path), socket=sock, log=lambda _message: None)
    assert bridge.setup()
    assert sock.bound == ("0.0.0.0", 8766)


@pytest.mark.parametrize("connected,ipv4", [(False, "192.168.1.9"), (True, None)])
def test_setup_requires_existing_wifi_and_never_connects_or_creates_socket(connected, ipv4):
    class Radio:
        ipv4_address = ipv4

        def connect(self, *_args, **_kwargs):
            raise AssertionError("metadata bridge must never join Wi-Fi")

    radio = Radio()
    radio.connected = connected
    bridge = module.MetadataBridge(profile={"v": 1, "token": TOKEN}, radio=radio,
                                   pool=object(), log=lambda _message: None)
    assert not bridge.setup()


def test_socket_setup_failure_closes_socket_and_preserves_disabled_fallback():
    class BrokenSocket(Socket):
        def bind(self, _address):
            raise OSError("port in use")

    sock = BrokenSocket()
    bridge = module.MetadataBridge(profile={"v": 1, "token": TOKEN}, socket=sock, log=lambda _message: None)
    assert not bridge.setup()
    assert sock.closed
    bridge.poll()
    assert bridge.snapshot() is None

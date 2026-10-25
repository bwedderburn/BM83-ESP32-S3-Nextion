"""Host tests for the Mac sender; no media controls or live network required."""
import errno
import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "tools/mac_metadata_bridge/bridge.py"
SPEC = importlib.util.spec_from_file_location("mac_metadata_sender", PATH)
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


def config():
    return {"v": 1, "host": "192.0.2.10", "port": 8766, "token": "a" * 64,
            "target_output": "BM83", "interval": 2}


def raw_snapshot(**changes):
    data = {"has_item": True, "output_name": "BM83", "title": "The Song", "artist": "The Artist",
            "album": "The Album", "duration": 300, "elapsed": 20, "rate": 1, "timestamp": 1000}
    data.update(changes)
    return data


def test_snapshot_preserves_track_and_projects_playing_clock():
    result = bridge.normalize_snapshot(raw_snapshot(), now=1002)
    assert result == {"state": "playing", "title": "The Song", "artist": "The Artist", "album": "The Album",
                      "duration_ms": 300000, "position_ms": 22000}


def test_paused_clock_does_not_advance():
    result = bridge.normalize_snapshot(raw_snapshot(rate=0), now=2000)
    assert result["state"] == "paused"
    assert result["position_ms"] == 20000


@pytest.mark.parametrize("output", ["MacBook Pro Speakers", "BM83 Other", "", None])
def test_route_gate_requires_exact_default_output(output):
    result = bridge.normalize_snapshot(raw_snapshot(output_name=output), now=1002)
    assert result["state"] == "stopped"
    assert result["title"] == result["artist"] == result["album"] == ""
    assert result["duration_ms"] is None


def test_route_match_is_case_insensitive():
    assert bridge.normalize_snapshot(raw_snapshot(output_name="bm83"), now=1000)["state"] == "playing"


@pytest.mark.parametrize("snapshot", [{}, None, {"error": "unavailable"}, raw_snapshot(title=""),
                                      raw_snapshot(has_item=False)])
def test_missing_metadata_explicitly_clears(snapshot):
    assert bridge.normalize_snapshot(snapshot)["state"] == "stopped"


def test_time_values_reject_nonfinite_and_clamp_to_duration():
    assert bridge.normalize_snapshot(raw_snapshot(duration=float("nan")), now=1002)["duration_ms"] is None
    assert bridge.normalize_snapshot(raw_snapshot(duration=30, elapsed=100), now=1002)["position_ms"] == 30000
    assert bridge.milliseconds(10 ** 1000) is None
    assert bridge.milliseconds(1e300) == bridge.MAX_MILLISECONDS
    assert bridge.milliseconds(True) is None
    assert bridge.milliseconds(-1) is None


def test_future_timestamp_does_not_rewind_clock():
    assert bridge.normalize_snapshot(raw_snapshot(timestamp=2000), now=1000)["position_ms"] == 20000


def test_text_truncation_preserves_utf8_and_removes_controls():
    text = bridge.clean_text("\n" + "é" * 400 + "\x00\x01")
    assert len(text.encode("utf-8")) == 256
    assert text == "é" * 128
    assert bridge.clean_text("Line\nTwo\tThree\x01") == "Line Two Three"
    assert bridge.clean_text("\ud800") == "?"


def test_json_escaped_text_still_fits_datagram():
    metadata = bridge.normalize_snapshot(raw_snapshot(title='"' * 256, artist='\\' * 256, album='"' * 256), now=1000)
    encoded = bridge.encode_packet(metadata, "a" * 128, "0123456789abcdef", 123)
    decoded = json.loads(encoded)
    assert len(encoded) <= 1400
    assert decoded["token"] == "a" * 128
    assert decoded["v"] == 1
    assert decoded["seq"] == 123


def test_private_profile_loads_without_returning_unknown_fields(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config()))
    path.chmod(0o600)
    loaded = bridge.load_config(path)
    assert loaded["target_output"] == "BM83"
    assert loaded["host"] == "192.0.2.10"
    assert "v" not in loaded


def test_world_readable_profile_rejected_without_token_in_error(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config()))
    path.chmod(0o644)
    with pytest.raises(bridge.BridgeError, match="private") as error:
        bridge.load_config(path)
    assert config()["token"] not in str(error.value)


@pytest.mark.parametrize("changes", [{"host": "bad"}, {"host": "255.255.255.255"}, {"host": 123},
                                     {"host": "224.0.0.1"}, {"port": True}, {"port": 70000},
                                     {"token": "short"}, {"token": "a" * 16}, {"token": "z" * 64},
                                     {"target_output": ""}, {"interval": float("inf")}])
def test_invalid_profile_rejected(tmp_path, changes):
    path = tmp_path / "config.json"
    data = config()
    data.update(changes)
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    with pytest.raises(bridge.BridgeError):
        bridge.load_config(path)


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    def sendto(self, data, target):
        self.sent.append((json.loads(data), target))

    def close(self):
        self.closed = True


def test_sender_uses_same_session_monotonic_sequence_and_clears_route_change():
    transport = FakeSocket()
    sender = bridge.Sender(config(), transport)
    sender.send(raw_snapshot(), now=1000)
    sender.send(raw_snapshot(output_name="Built-in Output"), now=1002)
    first, second = [data for data, _ in transport.sent]
    assert first["session"] == second["session"]
    assert len(first["session"]) == 16
    assert [first["seq"], second["seq"]] == [1, 2]
    assert second["state"] == "stopped"
    assert second["title"] == ""
    assert transport.sent[0][1] == ("192.0.2.10", 8766)
    sender.close()
    assert transport.closed


def test_sender_rollover_starts_fresh_session():
    transport = FakeSocket()
    sender = bridge.Sender(config(), transport)
    session = sender.session
    sender.sequence = 2147483647
    sender.send({}, now=1000)
    assert sender.session != session
    assert sender.sequence == 1


def test_network_errors_are_rate_limited_and_redacted():
    messages = []
    diagnostic = bridge.NetworkDiagnostics(log=messages.append)
    error = OSError(errno.EHOSTUNREACH, "private token and receiver address must not be printed")
    diagnostic.failed(error, now=0)
    diagnostic.failed(error, now=2)
    diagnostic.failed(error, now=29)
    assert len(messages) == 1
    assert f"errno={errno.EHOSTUNREACH}" in messages[0] and "EHOSTUNREACH" in messages[0]
    assert "private token" not in messages[0]
    diagnostic.failed(error, now=30)
    assert len(messages) == 2
    assert "consecutive=4" in messages[1]


def test_network_recovery_is_reported_once():
    messages = []
    diagnostic = bridge.NetworkDiagnostics(log=messages.append)
    diagnostic.failed(OSError(65, "hidden"), now=0)
    diagnostic.recovered()
    diagnostic.recovered()
    assert len(messages) == 2
    assert messages[1] == "UDP sending recovered after 1 failed attempts"
    diagnostic.failed(OSError(65, "hidden"), now=1)
    assert len(messages) == 3


def test_changed_network_error_is_reported_immediately():
    messages = []
    diagnostic = bridge.NetworkDiagnostics(log=messages.append)
    diagnostic.failed(OSError(65, "hidden"), now=0)
    diagnostic.failed(OSError(1, "hidden"), now=2)
    assert len(messages) == 2
    assert "EPERM" in messages[-1]


def test_failed_socket_refresh_preserves_session_and_sequence(monkeypatch):
    first, replacement = FakeSocket(), FakeSocket()
    sockets = iter([first, replacement])
    monkeypatch.setattr(bridge.socket, "socket", lambda *args: next(sockets))
    sender = bridge.Sender(config())
    sender.send(raw_snapshot(), now=1000)
    session = sender.session
    assert sender.refresh_transport()
    assert first.closed
    assert sender.transport is replacement
    sender.send(raw_snapshot(), now=1002)
    assert replacement.sent[0][0]["session"] == session
    assert replacement.sent[0][0]["seq"] == 2


def test_socket_creation_failure_keeps_existing_socket(monkeypatch):
    original = FakeSocket()
    sender = bridge.Sender(config(), original)
    sender.owns_transport = True

    def fail_socket(*args):
        raise OSError(24, "file descriptor limit")

    monkeypatch.setattr(bridge.socket, "socket", fail_socket)
    assert not sender.refresh_transport()
    assert not original.closed
    assert sender.transport is original

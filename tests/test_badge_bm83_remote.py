"""Offline contract tests for the optional Universe badge BM83 client.

Load helpers directly: importing the badge entrypoint would start its runtime.
The socket is always replaced, and no artwork fetch or device files are used.
"""

import errno
import hashlib
import hmac
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP = next((path for path in (
    ROOT / "addons/universe-badge/apps/bm83_remote",
    ROOT / "badge/apps/bm83_remote",
) if path.is_dir()), None)
if APP is None:
    raise RuntimeError("Cannot locate the badge BM83 client")


def load_helper(name):
    spec = importlib.util.spec_from_file_location("badge_test_" + name, APP / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


with patch.dict(sys.modules, {"fetch": None}):
    protocol = load_helper("protocol")
    with patch.dict(sys.modules, {"protocol": protocol}):
        models = load_helper("models")
        with patch.dict(sys.modules, {"models": models}):
            transport = load_helper("transport")
    artwork = load_helper("artwork")

KEY = bytes(range(32))
PEER = ("192.0.2.50", 8767)


def snapshot(**changes):
    value = {
        "power_on": True, "connected": True, "aux": False,
        "clock_advancing": True, "play_status": 1, "eq_index": 0,
        "duration_ms": 10000, "position_ms": 1000, "position_age_ms": 100,
        "title": "Song", "artist": "Artist", "album": "Album", "eq": "Flat",
    }
    value.update(changes)
    return value


def ble_state(**changes):
    value = {"session": 1, "sequence": 1, "mode": 0, "flags": 15,
             "error": 0, "req_client": None, "req_seq": None}
    value.update(changes)
    return value


class FakeSocket:
    def __init__(self):
        self.incoming = []
        self.sent = []
        self.closed = False

    def setblocking(self, blocking):
        if blocking:
            raise AssertionError("Client socket must remain nonblocking")

    def sendto(self, wire, peer):
        self.sent.append((wire, peer))
        return len(wire)

    def recvfrom(self, size):
        if not self.incoming:
            raise OSError(errno.EAGAIN, "fake socket has no reply")
        wire, peer = self.incoming.pop(0)
        return wire[:size], peer

    def close(self):
        self.closed = True


class ProtocolTests(unittest.TestCase):
    def test_hmac_matches_standard_library_reference(self):
        payload = b'{"v":1,"type":"hello","nonce":"0123456789abcdef"}'
        expected = hmac.new(KEY, payload, hashlib.sha256).digest()[:16].hex().encode()
        self.assertEqual(protocol.mac(KEY, payload), expected)

    def test_unicode_and_control_character_round_trip(self):
        value = {"v": 1, "text": 'Möbius\n"quoted"\\\t\x00',
                 "nested": [True, False, None, 42]}
        self.assertEqual(protocol.decode(KEY, protocol.encode(KEY, value)), value)

    def test_modified_payload_and_tag_are_rejected(self):
        wire = protocol.encode(KEY, {"v": 1, "type": "hello"})
        self.assertIsNone(protocol.decode(KEY, wire[:-1] + b"!"))
        self.assertIsNone(protocol.decode(KEY, wire[:5] + b"0" * 32 + wire[37:]))

    def test_bad_envelopes_and_authenticated_json_are_rejected(self):
        for payload in (b"{", b"[]", b'{"v":true}', b'{"v":2}', b"\xff"):
            with self.subTest(payload=payload):
                wire = b"BMW1." + protocol.mac(KEY, payload) + b"." + payload
                self.assertIsNone(protocol.decode(KEY, wire))
        for wire in (b"", b"other." + bytes(40), b"BMW1." + bytes(1200)):
            self.assertIsNone(protocol.decode(KEY, wire))

    def test_packet_and_key_limits(self):
        with self.assertRaises(ValueError):
            protocol.encode(KEY, {"v": 1, "text": "x" * 300})
        for maximum in (True, 39, 1201):
            with self.subTest(maximum=maximum), self.assertRaises(ValueError):
                protocol.encode(KEY, {"v": 1}, maximum)
        for key in ("00", "G" * 64, "A" * 64):
            with self.subTest(key=key), self.assertRaises(ValueError):
                protocol.key_bytes(key)

    def test_configuration_checks_types_without_reading_secrets(self):
        config = SimpleNamespace(BM83_HOST=PEER[0], BM83_KEY=KEY.hex())
        self.assertEqual(protocol.configuration(config), (PEER[0], PEER[1], KEY))
        for changes in ({"BM83_HOST": "host.invalid"}, {"BM83_PORT": True},
                        {"BM83_PORT": 0}, {"BM83_PORT": 65536}):
            values = vars(config).copy()
            values.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                protocol.configuration(SimpleNamespace(**values))


class ModelTests(unittest.TestCase):
    def test_missing_position_fields_are_rejected_without_crashing(self):
        for name in ("duration_ms", "position_ms", "position_age_ms"):
            state = snapshot()
            del state[name]
            with self.subTest(name=name):
                self.assertFalse(models.valid_np(state))
                playback = models.Playback()
                self.assertFalse(playback.accept(state, 100))
                self.assertIsNone(playback.state)

    def test_unknown_position_fields_may_explicitly_be_null(self):
        playback = models.Playback()
        self.assertTrue(playback.accept(snapshot(duration_ms=None, position_ms=None,
                                                 position_age_ms=None), 0))
        self.assertIsNone(playback.position(1))

    def test_invalid_playback_field_types_are_rejected(self):
        for changes in ({"position_ms": True}, {"position_age_ms": -1},
                        {"play_status": 99}, {"title": "x" * 97},
                        {"power_on": 1}, {"eq_index": False}):
            with self.subTest(changes=changes):
                self.assertFalse(models.valid_np(snapshot(**changes)))

    def test_advancing_clock_is_bounded_by_age_and_duration(self):
        playback = models.Playback()
        playback.accept(snapshot(), 1000)
        self.assertEqual(playback.position(2000), 2100)
        self.assertIsNone(playback.position(6001))
        self.assertFalse(playback.fresh(7000))
        playback.accept(snapshot(position_ms=9900), 8000)
        self.assertEqual(playback.position(8200), 10000)
        playback.accept(snapshot(clock_advancing=False), 9000)
        self.assertEqual(playback.position(10000), 1000)

    def test_paused_clock_stays_fixed_and_track_change_resets_it(self):
        playback = models.Playback()
        playback.accept(snapshot(play_status=2), 0)
        playback.accept(snapshot(play_status=2, position_ms=1500), 1000)
        self.assertEqual(playback.position(1500), 1000)
        playback.accept(snapshot(play_status=2, title="New song", position_ms=200), 2000)
        self.assertEqual(playback.position(2200), 200)

    def test_ble_confirmation_requires_new_matching_request(self):
        control = models.BleControl()
        control.accept(ble_state(), 0)
        self.assertTrue(control.begin(True, 7, 9, 10))
        control.accept(ble_state(mode=2, flags=2, req_client=7, req_seq=9), 20)
        control.tick(20)
        self.assertEqual(control.result, "Waiting")
        control.accept(ble_state(sequence=2, mode=2, flags=2, req_client=7, req_seq=9), 30)
        control.tick(30)
        self.assertEqual(control.result, "Confirmed")

    def test_ble_stale_status_and_superseded_request_do_not_confirm(self):
        control = models.BleControl()
        control.accept(ble_state(), 0)
        self.assertFalse(control.begin(True, 7, 9, 3000))
        self.assertTrue(control.begin(True, 7, 9, 1))
        control.accept(ble_state(sequence=2, mode=2, flags=2, req_client=8, req_seq=9), 2)
        control.tick(2)
        self.assertEqual(control.result, "Unconfirmed (superseded)")


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.socket = FakeSocket()
        self.socket_patch = patch.object(transport.socket, "socket", return_value=self.socket)
        self.socket_patch.start()
        self.addCleanup(self.socket_patch.stop)
        self.remote = transport.Remote(PEER[0], PEER[1], KEY)

    def reply(self, value, peer=PEER):
        self.socket.incoming.append((protocol.encode(KEY, value, 1200), peer))

    def connect(self):
        self.remote.step(0)
        self.reply({"v": 1, "type": "welcome", "nonce": self.remote.nonce,
                    "unit": "01020304", "client": 7})
        self.remote.step(1)
        self.assertEqual(self.remote.client, 7)

    def state_reply(self, **changes):
        value = {"v": 1, "type": "state", "unit": "01020304", "client": 7,
                 "seq": self.remote.seq, "dup": False, "np": snapshot()}
        value.update(changes)
        return value

    def test_welcome_requires_configured_peer_and_matching_nonce(self):
        self.remote.step(0)
        welcome = {"v": 1, "type": "welcome", "nonce": self.remote.nonce,
                   "unit": "01020304", "client": 7}
        self.reply(welcome, ("192.0.2.99", 8767))
        self.remote.step(1)
        self.assertIsNone(self.remote.client)
        welcome["nonce"] = "wrong"
        self.reply(welcome)
        self.remote.step(2)
        self.assertIsNone(self.remote.client)

    def test_authenticated_welcome_establishes_session(self):
        self.connect()
        self.assertIsNone(self.remote.pending)
        self.assertEqual(self.remote.unit, "01020304")
        self.assertEqual(self.remote.feedback, "Audio unit authenticated")

    def test_retry_uses_same_wire_and_timed_out_command_is_not_replayed(self):
        self.connect()
        self.remote.queue_command("BT_PLAY")
        self.remote.step(2)
        original = self.socket.sent[-1]
        for now in (152, 302, 452, 602):
            self.remote.step(now)
        self.assertIsNone(self.remote.pending)
        self.assertEqual(self.socket.sent[1:], [original] * 4)
        self.assertEqual(self.remote.seq, 1)
        self.assertIn("no reply", self.remote.feedback)

    def test_mismatched_response_does_not_clear_pending_command(self):
        self.connect()
        self.remote.queue_command("BT_PLAY")
        self.remote.step(2)
        for changes in ({"client": 8}, {"seq": 2}, {"unit": "05060708"}):
            self.reply(self.state_reply(**changes))
            self.remote.step(3)
            self.assertIsNotNone(self.remote.pending)
        self.reply(self.state_reply())
        self.remote.step(4)
        self.assertIsNone(self.remote.pending)
        self.assertEqual(self.remote.feedback, "BT_PLAY: sent (reply)")

    def test_restart_does_not_replay_non_idempotent_command(self):
        self.connect()
        self.remote.queue_command("BT_PLAY")
        self.remote.step(2)
        self.reply({"v": 1, "type": "rehello", "client": 7, "seq": 1})
        self.remote.step(3)
        self.assertFalse(self.remote.queue)
        self.assertIn("unconfirmed", self.remote.feedback)
        messages = [protocol.decode(KEY, wire) for wire, _ in self.socket.sent]
        self.assertEqual(sum(m.get("token") == "BT_PLAY" for m in messages), 1)
        self.assertEqual(messages[-1]["type"], "hello")

    def test_release_precedes_other_commands_and_retries_when_stalled(self):
        self.connect()
        self.remote.volume("BT_VOLUP")
        self.remote.release_volume()
        self.remote.queue_command("BT_PLAY")
        self.remote.step(2)
        self.assertEqual(self.remote.pending["token"], "BT_VOLUP_P")
        self.reply(self.state_reply())
        self.remote.step(3)
        self.assertEqual(self.remote.pending["token"], "BT_VOLUP_R")
        release = self.socket.sent[-1]
        for now in (153, 303, 453, 603, 1603):
            self.remote.step(now)
        self.assertTrue(self.remote.pending["stalled"])
        self.assertEqual(self.socket.sent[-1], release)
        self.assertEqual(self.remote.queue, ["BT_PLAY"])

    def test_input_queue_is_bounded_and_rejects_unknown_commands(self):
        for _ in range(8):
            self.assertTrue(self.remote.queue_command("BT_PLAY"))
        self.assertFalse(self.remote.queue_command("BT_PLAY"))
        self.assertTrue(self.remote.queue_command("BT_VOLUP_R"))
        self.assertEqual(self.remote.release_due, ["BT_VOLUP_R"])
        with self.assertRaises(ValueError):
            self.remote.queue_command("not-a-command")


class ArtworkTests(unittest.TestCase):
    def test_https_allowlist_rejects_userinfo_deceptive_hosts_and_schemes(self):
        for url in ("https://musicbrainz.org/search", "https://ia801.archive.org/cover.jpg",
                    "https://cdn-images.dzcdn.net/images/cover/test.jpg"):
            self.assertTrue(artwork._allowed_url(url), url)
        for url in ("http://musicbrainz.org/search", "https://musicbrainz.org.evil.test/x",
                    "https://user@musicbrainz.org/x", "https://musicbrainz.org:443/x",
                    "https://evil.test/x", "https://musicbrainz.org/\n"):
            self.assertFalse(artwork._allowed_url(url), url)

    def test_baseline_jpeg_dimensions_and_size_limits(self):
        jpeg = b"\xff\xd8\xff\xc0\x00\x08\x08\x00\x10\x00\x20\x01\xff\xd9"
        self.assertEqual(artwork._jpeg_dimensions(jpeg), (32, 16, True))
        oversized = jpeg[:9] + b"\x01\x41" + jpeg[11:]
        with self.assertRaises(ValueError):
            artwork._jpeg_dimensions(oversized)

    def test_progressive_and_truncated_jpegs_are_rejected(self):
        jpeg = b"\xff\xd8\xff\xc2\x00\x08\x08\x00\x10\x00\x20\x01\xff\xd9"
        for data in (jpeg, jpeg[:-2], b"not a jpeg"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                artwork._jpeg_dimensions(data)

    def test_artwork_match_requires_exact_identity_and_unique_result(self):
        group = {"id": "12345678-1234-1234-1234-123456789abc", "score": 100,
                 "title": "Album", "artist-credit": [{"name": "Artist", "artist": {"name": "Artist"}}]}
        data = {"count": 1, "release-groups": [group]}
        self.assertEqual(artwork._match_group(data, "Artist", "Album"), group["id"])
        self.assertIsNone(artwork._match_group(data, "Different artist", "Album"))
        second = dict(group, id="87654321-1234-1234-1234-123456789abc")
        self.assertIsNone(artwork._match_group({"count": 2, "release-groups": [group, second]}, "Artist", "Album"))


if __name__ == "__main__":
    unittest.main()

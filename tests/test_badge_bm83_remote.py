"""Offline contract tests for the optional Universe badge BM83 client.

Load helpers directly: importing the badge entrypoint would start its runtime.
The socket is always replaced, and no artwork fetch or device files are used.
"""

import ast
import errno
import hashlib
import hmac
import importlib.util
import inspect
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

    def test_display_text_maps_latin_accents_without_shifting_letters(self):
        self.assertEqual(models.display_text("François, niño"), "Francois, nino")
        self.assertEqual(models.display_text("àáâãäå ç èéêë ìíîï ñ òóôõöø ùúûü ýÿ"),
                         "aaaaaa c eeee iiii n oooooo uuuu yy")
        self.assertEqual(models.display_text("ÀÁÂÃÄÅ Ç ÈÉÊË ÌÍÎÏ Ñ ÒÓÔÕÖØ ÙÚÛÜ ÝŸ"),
                         "AAAAAA C EEEE IIII N OOOOOO UUUU YY")

    def test_display_text_folds_icelandic_and_ligatures_legibly(self):
        self.assertEqual(models.display_text("Sigur R\u00f3s \u2013 \u00c1g\u00e6tis byrjun"),
                         "Sigur Ros - Agaetis byrjun")
        self.assertEqual(models.display_text("\u00de\u00f6gn \u00d0\u00f0 \u00c6 \u0153 Stra\u00dfe"),
                         "Thogn Dd AE oe Strasse")
        self.assertEqual(models.display_text("\u5742\u672c \U0001f389"), "?? ?")

    def test_accent_folding_does_not_rely_on_unicode_case_methods(self):
        # MicroPython's str.lower()/upper()/isupper() leave non-ASCII letters unchanged.
        tree = ast.parse(inspect.getsource(models.display_text))
        methods = {node.func.attr for node in ast.walk(tree)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertFalse(methods & {"lower", "upper", "isupper", "islower", "casefold"})

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

    def test_source_label_shows_only_a_proven_text_origin(self):
        self.assertTrue(models.valid_np(snapshot()))
        self.assertEqual(models.source_label(snapshot()), "")
        self.assertEqual(models.source_label(None), "")
        for src, label in (("avrcp", "via AVRCP"), ("mac", "via Mac Wi-Fi"), ("", ""),
                           ("AVRCP", ""), ("bt", ""), (None, ""), (1, ""), (["mac"], "")):
            with self.subTest(src=src):
                value = snapshot(src=src)
                self.assertTrue(models.valid_np(value))
                self.assertEqual(models.source_label(value), label)

    def test_null_ble_is_ignored_without_clearing_fresh_status(self):
        control = models.BleControl()
        control.accept(ble_state(), 0)
        control.accept(None, 10)
        self.assertEqual(control.state, ble_state())
        self.assertEqual(control.received, 0)


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
        message = protocol.decode(KEY, original[0])
        self.assertEqual(message["token"], "BT_PLAY")
        self.assertNotIn("command", message)
        self.assertEqual(self.remote.pending["command"], "BT_PLAY")
        for now in (152, 302, 452, 602):
            self.remote.step(now)
        self.assertIsNone(self.remote.pending)
        self.assertEqual(self.socket.sent[1:], [original] * 4)
        self.assertEqual(self.remote.seq, 1)
        self.assertIn("no reply", self.remote.feedback)

    def test_release_retry_interval_is_wrap_safe(self):
        self.connect()
        sent = 0xfffffff0
        self.remote.pending = {"wire": b"release", "command": "BT_VOLUP_R",
                               "attempts": 1, "sent": sent}
        self.remote.step(0x85)
        self.assertEqual(len(self.socket.sent), 1)
        self.remote.step(0x86)
        self.assertEqual(len(self.socket.sent), 2)

    def test_stalled_release_and_poll_intervals_are_wrap_safe(self):
        self.connect()
        sent = 0xfffffff0
        self.remote.pending = {"wire": b"release", "command": "BT_VOLUP_R",
                               "attempts": 4, "sent": sent, "stalled": True}
        self.remote.step(0x3d7)
        self.assertEqual(len(self.socket.sent), 1)
        self.remote.step(0x3d8)
        self.assertEqual(len(self.socket.sent), 2)

        self.remote.pending = None
        self.remote.last_poll = 0xffffff00
        self.remote.step(0x2e7)
        self.assertEqual(len(self.socket.sent), 2)
        self.remote.step(0x2e8)
        self.assertEqual(len(self.socket.sent), 3)
        self.assertEqual(self.remote.pending["command"], "STATUS")

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

    def test_denied_reply_reports_refusal_instead_of_delivery(self):
        self.connect()
        self.remote.queue_command("BT_EBIND")
        self.remote.step(2)
        self.reply(self.state_reply(denied=True))
        self.remote.step(3)
        self.assertIsNone(self.remote.pending)
        self.assertEqual(self.remote.feedback, "Erase bonds: refused by audio unit")
        for denied in (1, "true", False, None):
            with self.subTest(denied=denied):
                self.remote.queue_command("BT_EBIND")
                self.remote.step(4)
                self.reply(self.state_reply(denied=denied))
                self.remote.step(5)
                self.assertIsNone(self.remote.pending)
                self.assertEqual(self.remote.feedback, "BT_EBIND: sent (reply)")

    def test_status_reply_clears_link_errors_but_keeps_command_outcomes(self):
        self.connect()
        self.remote.queue_command("STATUS")
        for now in (2, 152, 302, 452, 602):
            self.remote.step(now)
        self.assertEqual(self.remote.feedback, "STATUS: no reply")
        for stale, expected in (
                ("STATUS: no reply", "Audio unit responding"),
                ("UDP receive error: 104", "Audio unit responding"),
                ("UDP unavailable: 113", "Audio unit responding"),
                ("BT_NEXT: no reply", "BT_NEXT: no reply"),
                ("Erase bonds: refused by audio unit", "Erase bonds: refused by audio unit")):
            with self.subTest(stale=stale):
                self.remote.feedback = stale
                self.remote.queue_command("STATUS")
                self.remote.step(700)
                self.reply(self.state_reply())
                self.remote.step(701)
                self.assertIsNone(self.remote.pending)
                self.assertEqual(self.remote.feedback, expected)

    def test_legacy_net_retry_outcomes_read_as_receiver_retry_unavailable(self):
        for reply in ({"denied": True}, {"dup": True, "denied": True}, {"dup": True}):
            with self.subTest(reply=reply):
                self.setUp()
                self.connect()
                self.remote.queue_command("NET_RETRY")
                self.remote.step(2)
                self.reply(self.state_reply(**reply))
                self.remote.step(3)
                self.assertIsNone(self.remote.pending)
                self.assertEqual(self.remote.feedback, "Receiver retry unavailable")
        self.setUp()
        self.connect()
        self.remote.queue_command("NET_RETRY")
        self.remote.step(2)
        self.reply({"v": 1, "type": "rehello", "client": self.remote.client,
                    "seq": self.remote.seq})
        self.remote.step(3)
        self.assertEqual(self.remote.feedback, "Receiver retry unavailable")

    def sent_tokens(self):
        return [protocol.decode(KEY, wire).get("token") for wire, _ in self.socket.sent]

    def test_press_during_handshake_is_sent_after_welcome(self):
        self.remote.step(0)
        self.assertTrue(self.remote.queue_command("BT_PLAY"))
        self.assertEqual(self.remote.feedback, "BT_PLAY: waiting for audio unit")
        self.reply({"v": 1, "type": "welcome", "nonce": self.remote.nonce,
                    "unit": "01020304", "client": 7})
        self.remote.step(1)
        self.remote.step(2)
        self.assertEqual(self.remote.pending["command"], "BT_PLAY")

    def test_presses_are_dropped_when_the_unit_never_answers(self):
        self.remote.step(0)
        self.remote.queue_command("BT_POWER")
        self.remote.queue_command("BT_VOLUP_P")
        for now in (150, 300, 450, 600):
            self.remote.step(now)
        self.assertIsNone(self.remote.pending)
        self.assertEqual(self.remote.queue, [])
        self.assertEqual(self.remote.volume_queue, [])
        self.assertEqual(self.remote.feedback, "Audio unit: no reply - 2 not sent")
        self.remote.step(1600)
        self.reply({"v": 1, "type": "welcome", "nonce": self.remote.nonce,
                    "unit": "01020304", "client": 7})
        self.remote.step(1601)
        self.remote.step(2601)
        self.assertNotIn("BT_POWER", self.sent_tokens())
        self.assertNotIn("BT_VOLUP_P", self.sent_tokens())
        self.assertEqual(self.remote.pending["command"], "STATUS")

    def test_late_welcome_cannot_rescue_expired_presses_even_without_retries(self):
        for start in (0, 0xffffff00):
            with self.subTest(start=start):
                self.socket.sent.clear()
                self.socket.incoming.clear()
                self.remote = transport.Remote(PEER[0], PEER[1], KEY)
                self.remote.last_poll = (start - 1000) & 0xffffffff
                self.remote.step(start)
                self.remote.queue_command("BT_POWER")
                self.remote.volume("BT_VOLUP")
                self.reply({"v": 1, "type": "welcome", "nonce": self.remote.nonce,
                            "unit": "01020304", "client": 7})
                # A delayed frame crosses the whole hello budget in one step.
                self.remote.step((start + 600) & 0xffffffff)
                self.assertIsNone(self.remote.client)
                self.assertIsNone(self.remote.pending)
                self.assertFalse(self.remote.queue)
                self.assertFalse(self.remote.volume_queue)
                self.assertIsNone(self.remote.held_volume)
                self.assertEqual(self.remote.feedback, "Audio unit: no reply - 2 not sent")
                self.remote.release_volume()
                self.remote.step((start + 1600) & 0xffffffff)
                self.reply({"v": 1, "type": "welcome", "nonce": self.remote.nonce,
                            "unit": "01020304", "client": 8})
                self.remote.step((start + 1601) & 0xffffffff)
                self.assertEqual(self.remote.client, 8)
                self.assertFalse(any(self.sent_tokens()))

    def test_welcome_before_elapsed_deadline_can_deliver_a_fresh_press(self):
        self.remote.step(0)
        self.remote.queue_command("BT_PLAY")
        self.reply({"v": 1, "type": "welcome", "nonce": self.remote.nonce,
                    "unit": "01020304", "client": 7})
        self.remote.step(599)
        self.assertEqual(self.remote.pending["command"], "BT_PLAY")

    def test_handshake_timeout_clears_unsent_held_volume_without_a_stop(self):
        self.remote.step(0)
        self.remote.volume("BT_VOLUP")
        for now in (150, 300, 450, 600):
            self.remote.step(now)
        self.assertIsNone(self.remote.held_volume)
        self.remote.release_volume()
        self.assertFalse(self.remote.volume_queue)

    def test_offline_steps_drop_unsent_input_without_any_network_io(self):
        self.connect()
        self.remote.queue_command("BT_PLAY")
        self.remote.volume("BT_VOLUP")
        with patch.object(self.socket, "recvfrom", side_effect=AssertionError("offline receive")):
            self.remote.step(2, connected=False)
        self.assertEqual(self.sent_tokens(), [None])
        self.assertFalse(self.remote.queue)
        self.assertFalse(self.remote.volume_queue)
        self.assertIsNone(self.remote.held_volume)
        self.remote.release_volume()
        self.remote.step(1002)
        self.assertEqual(self.sent_tokens(), [None, "STATUS"])

    def test_offline_steps_service_in_flight_command_timeout(self):
        self.connect()
        self.remote.queue_command("BT_PLAY")
        self.remote.step(2)
        for now in (152, 302, 452, 602):
            self.remote.step(now, connected=False)
        self.assertIsNone(self.remote.pending)
        self.assertEqual(self.sent_tokens(), [None, "BT_PLAY"])
        self.remote.step(603)
        self.assertEqual(self.sent_tokens(), [None, "BT_PLAY"])

    def test_wifi_loss_keeps_sent_press_release_but_drops_same_button_repress(self):
        self.connect()
        self.remote.volume("BT_VOLUP")
        self.remote.step(2)
        self.remote.release_volume()
        self.remote.volume("BT_VOLUP")
        self.remote.step(3, connected=False)
        self.assertIsNone(self.remote.held_volume)
        self.assertEqual(self.remote.volume_queue,
                         [{"command": "BT_VOLUP", "pressed": True, "released": True}])
        self.remote.release_volume()
        self.reply(self.state_reply())
        self.remote.step(4)
        self.assertEqual(self.remote.pending["command"], "BT_VOLUP_R")
        self.reply(self.state_reply())
        self.remote.step(5)
        self.assertEqual(self.sent_tokens(), [None, "BT_VOLUP_P", "BT_VOLUP_R"])

    def test_wifi_loss_keeps_release_wire_and_sends_it_only_after_reconnect(self):
        self.connect()
        self.remote.volume("BT_VOLDN")
        self.remote.step(2)
        self.remote.release_volume()
        self.reply(self.state_reply())
        self.remote.step(3)
        release = self.socket.sent[-1]
        for now in (153, 303, 453, 603, 1603):
            self.remote.step(now, connected=False)
        self.assertEqual(self.socket.sent[-1], release)
        self.assertEqual(len(self.socket.sent), 3)
        self.assertTrue(self.remote.pending["stalled"])
        self.remote.step(1604)
        self.assertEqual(self.socket.sent[-1], release)
        self.assertEqual(len(self.socket.sent), 4)

    def load_ble_status(self):
        self.remote.queue_command("STATUS")
        self.remote.step(2)
        self.reply(self.state_reply(ble=ble_state()))
        self.remote.step(3)
        self.assertTrue(self.remote.ble.available(3))

    def test_null_ble_command_reply_waits_for_later_status_confirmation(self):
        self.connect()
        self.load_ble_status()
        self.remote.queue_command("BLE_PAUSE")
        self.remote.step(4)
        seq = self.remote.seq
        self.reply(self.state_reply(ble=None))
        self.remote.step(5)
        self.assertIsNone(self.remote.pending)
        self.assertEqual(self.remote.feedback, "BLE_PAUSE: sent (reply)")
        self.assertEqual(self.remote.ble.state, ble_state())
        self.assertEqual(self.remote.ble.result, "Waiting")
        self.remote.queue_command("STATUS")
        self.remote.step(6)
        self.reply(self.state_reply(ble=ble_state(sequence=2, mode=2, flags=2,
                                                  req_client=7, req_seq=seq)))
        self.remote.step(7)
        self.assertEqual(self.remote.ble.result, "Confirmed")

    def test_denied_ble_request_stops_waiting(self):
        self.connect()
        self.load_ble_status()
        self.remote.queue_command("BLE_PAUSE")
        self.remote.step(4)
        self.assertEqual(self.remote.ble.result, "Waiting")
        self.reply(self.state_reply(ble=None, denied=True))
        self.remote.step(5)
        self.assertEqual(self.remote.feedback, "BLE_PAUSE: refused by audio unit")
        self.assertEqual(self.remote.ble.result, "Refused")

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
        self.assertEqual(self.remote.pending["command"], "BT_VOLUP_P")
        self.reply(self.state_reply())
        self.remote.step(3)
        self.assertEqual(self.remote.pending["command"], "BT_VOLUP_R")
        release = self.socket.sent[-1]
        for now in (153, 303, 453, 603, 1603):
            self.remote.step(now)
        self.assertTrue(self.remote.pending["stalled"])
        self.assertEqual(self.socket.sent[-1], release)
        self.assertEqual(self.remote.queue, ["BT_PLAY"])

    def test_release_of_in_flight_press_precedes_same_button_repress(self):
        self.connect()
        self.remote.volume("BT_VOLUP")
        self.remote.step(2)
        self.remote.release_volume()
        self.remote.volume("BT_VOLUP")
        self.reply(self.state_reply())
        self.remote.step(3)
        self.assertEqual(self.remote.pending["command"], "BT_VOLUP_R")
        self.reply(self.state_reply())
        self.remote.step(4)
        self.assertEqual(self.remote.pending["command"], "BT_VOLUP_P")
        commands = [protocol.decode(KEY, wire).get("token") for wire, _ in self.socket.sent[1:]]
        self.assertEqual(commands, ["BT_VOLUP_P", "BT_VOLUP_R", "BT_VOLUP_P"])
        self.assertEqual(self.remote.held_volume, "BT_VOLUP")

    def test_complete_rapid_taps_each_keep_their_own_release(self):
        self.connect()
        for _ in range(2):
            self.remote.volume("BT_VOLUP")
            self.remote.release_volume()
        self.remote.step(2)
        for now in (3, 4, 5, 6):
            self.reply(self.state_reply())
            self.remote.step(now)
        commands = [protocol.decode(KEY, wire).get("token") for wire, _ in self.socket.sent[1:]]
        self.assertEqual(commands, ["BT_VOLUP_P", "BT_VOLUP_R", "BT_VOLUP_P", "BT_VOLUP_R"])
        self.assertFalse(self.remote.volume_queue)
        self.assertIsNone(self.remote.pending)

    def test_release_requeued_after_restart_precedes_new_gesture(self):
        self.connect()
        self.remote.volume("BT_VOLUP")
        self.remote.release_volume()
        self.remote.volume("BT_VOLDN")
        self.remote.step(2)
        self.reply(self.state_reply())
        self.remote.step(3)
        self.assertEqual(self.remote.pending["command"], "BT_VOLUP_R")
        self.reply({"v": 1, "type": "rehello", "client": 7, "seq": self.remote.seq})
        self.remote.step(4)
        self.reply({"v": 1, "type": "welcome", "nonce": self.remote.nonce,
                    "unit": "01020304", "client": 8})
        self.remote.step(5)
        self.assertEqual(self.remote.pending["command"], "BT_VOLUP_R")
        self.assertEqual(protocol.decode(KEY, self.socket.sent[-1][0])["token"], "BT_VOLUP_R")

    def test_volume_gesture_queue_is_bounded_but_keeps_stop_requests(self):
        for _ in range(8):
            self.assertTrue(self.remote.queue_command("BT_VOLUP_P"))
        self.assertFalse(self.remote.queue_command("BT_VOLUP_P"))
        for _ in range(8):
            self.assertTrue(self.remote.queue_command("BT_VOLUP_R"))
        self.assertEqual(len(self.remote.volume_queue), 8)
        self.assertTrue(all(gesture["released"] for gesture in self.remote.volume_queue))
        for _ in range(100):
            self.remote.queue_command("BT_VOLDN_R")
        self.assertEqual(len(self.remote.volume_queue), 9)

    def close_with_delayed_replies(self, now):
        clock = [now]

        def sleep(milliseconds):
            clock[0] += milliseconds
            pending = self.remote.pending
            if pending and pending["command"] and clock[0] - pending["sent"] >= 100:
                self.reply(self.state_reply())

        self.remote.close(now, sleep)

    def test_close_drops_eight_unsent_taps_without_starting_a_press(self):
        self.connect()
        for _ in range(8):
            self.remote.volume("BT_VOLUP")
            self.remote.release_volume()
        self.close_with_delayed_replies(2)
        commands = [protocol.decode(KEY, wire).get("token") for wire, _ in self.socket.sent[1:]]
        self.assertEqual(commands, [])
        self.assertFalse(self.remote.volume_queue)
        self.assertTrue(self.socket.closed)

    def test_close_finishes_only_the_in_flight_gesture(self):
        self.connect()
        self.remote.volume("BT_VOLUP")
        self.remote.step(2)
        self.remote.release_volume()
        for _ in range(7):
            self.remote.volume("BT_VOLUP")
            self.remote.release_volume()
        self.close_with_delayed_replies(3)
        commands = [protocol.decode(KEY, wire).get("token") for wire, _ in self.socket.sent[1:]]
        self.assertEqual(commands, ["BT_VOLUP_P", "BT_VOLUP_R"])
        self.assertIsNone(self.remote.pending)
        self.assertFalse(self.remote.volume_queue)
        self.assertTrue(self.socket.closed)

    def test_close_preserves_a_standalone_stop_request(self):
        self.connect()
        self.remote.queue_command("BT_VOLDN_R")
        self.close_with_delayed_replies(2)
        commands = [protocol.decode(KEY, wire).get("token") for wire, _ in self.socket.sent[1:]]
        self.assertEqual(commands, ["BT_VOLDN_R"])
        self.assertIsNone(self.remote.pending)
        self.assertTrue(self.socket.closed)

    def test_close_keeps_stalled_release_wire_and_drops_unsent_taps(self):
        self.connect()
        self.remote.queue_command("BT_VOLUP_R")
        self.remote.step(2)
        wire = self.remote.pending["wire"]
        for now in (152, 302, 452, 602):
            self.remote.step(now)
        self.assertTrue(self.remote.pending["stalled"])
        for _ in range(8):
            self.remote.volume("BT_VOLUP")
            self.remote.release_volume()
        with patch("builtins.print") as warning:
            self.remote.close(602, lambda milliseconds: None)
        self.assertTrue(self.remote.pending["stalled"])
        self.assertEqual(self.remote.pending["wire"], wire)
        self.assertTrue(all(sent == wire for sent, _ in self.socket.sent[1:]))
        self.assertFalse(self.remote.volume_queue)
        self.assertTrue(self.socket.closed)
        warning.assert_called_once()

    def test_input_queue_is_bounded_and_rejects_unknown_commands(self):
        for _ in range(8):
            self.assertTrue(self.remote.queue_command("BT_PLAY"))
        self.assertFalse(self.remote.queue_command("BT_PLAY"))
        self.assertTrue(self.remote.queue_command("BT_VOLUP_R"))
        self.assertEqual(self.remote.volume_queue,
                         [{"command": "BT_VOLUP", "pressed": True, "released": True}])
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

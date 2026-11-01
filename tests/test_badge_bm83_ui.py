"""Offline checks of badge input and Wi-Fi pacing without starting the app."""

import ast
import errno
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
APP = next((path for path in (
    ROOT / "addons/universe-badge/apps/bm83_remote",
    ROOT / "badge/apps/bm83_remote",
) if path.is_dir()), None)
if APP is None:
    raise RuntimeError("Cannot locate the badge BM83 client")

BUTTONS = {"BUTTON_" + name: name.lower()
           for name in ("UP", "DOWN", "LEFT", "RIGHT", "MENU", "BACK", "SELECT")}


def load_helper(name):
    spec = importlib.util.spec_from_file_location("badge_ui_test_" + name, APP / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


protocol = load_helper("protocol")
with patch.dict(sys.modules, {"protocol": protocol}):
    models = load_helper("models")
    with patch.dict(sys.modules, {"models": models}):
        transport = load_helper("transport")


def method_class(names=("_wifi", "input"), **globals_):
    """Compile only selected methods, excluding imports, setup and run(update)."""
    tree = ast.parse((APP / "__init__.py").read_text())
    original = next(node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == "BM83Remote")
    helpers = [node for node in tree.body
               if isinstance(node, ast.FunctionDef) and node.name in ("fit_text", "wrap_text")]
    methods = [node for node in original.body
               if isinstance(node, ast.FunctionDef) and node.name in names]
    minimal_class = ast.ClassDef(name="BM83Remote", bases=[], keywords=[], body=methods, decorator_list=[])
    isolated = ast.fix_missing_locations(ast.Module(body=helpers + [minimal_class], type_ignores=[]))
    namespace = dict(BUTTONS)
    namespace.update(globals_)
    exec(compile(isolated, str(APP / "__init__.py"), "exec"), namespace)
    return namespace["BM83Remote"]


class WifiPacingTests(unittest.TestCase):
    def app(self, wifi):
        app = method_class(wifi=wifi)()
        app.config_error = False
        app.wifi_ready = False
        app.next_wifi = 0
        app.wifi_error = ""
        return app

    def test_false_connection_result_waits_until_retry_deadline(self):
        wifi = SimpleNamespace(connect=Mock(return_value=False),
                               status=Mock(return_value=(-1, "Connecting")))
        app = self.app(wifi)
        self.assertFalse(app._wifi(100))
        for now in (101, 500, 1099):
            self.assertFalse(app._wifi(now))
        self.assertEqual(wifi.connect.call_count, 1)
        self.assertEqual(app.next_wifi, 1100)
        self.assertFalse(app._wifi(1100))
        self.assertEqual(wifi.connect.call_count, 2)

    def test_connection_exception_waits_until_its_retry_deadline(self):
        wifi = SimpleNamespace(connect=Mock(side_effect=OSError("Offline")))
        app = self.app(wifi)
        self.assertFalse(app._wifi(100))
        for now in (101, 1000, 2099):
            self.assertFalse(app._wifi(now))
        self.assertEqual(wifi.connect.call_count, 1)
        self.assertEqual(app.next_wifi, 2100)
        self.assertEqual(app.wifi_error, "Offline")
        self.assertFalse(app._wifi(2100))
        self.assertEqual(wifi.connect.call_count, 2)

    def test_success_returns_cached_readiness_until_refresh_deadline(self):
        wifi = SimpleNamespace(connect=Mock(side_effect=(True, False)),
                               status=Mock(return_value=(-1, "Connecting")))
        app = self.app(wifi)
        self.assertTrue(app._wifi(100))
        self.assertTrue(app._wifi(5099))
        self.assertEqual(wifi.connect.call_count, 1)
        self.assertFalse(app._wifi(5100))
        self.assertEqual(wifi.connect.call_count, 2)

    def test_false_result_retry_survives_tick_wrap_and_fires_at_deadline(self):
        wifi = SimpleNamespace(connect=Mock(return_value=False),
                               status=Mock(return_value=(-1, "Connecting")))
        app = self.app(wifi)
        self.assertFalse(app._wifi(0xffffff00))
        self.assertEqual(app.next_wifi, 744)
        for now in (0xffffff01, 0xffffffff, 0, 743):
            self.assertFalse(app._wifi(now))
        self.assertEqual(wifi.connect.call_count, 1)
        self.assertFalse(app._wifi(744))
        self.assertEqual(wifi.connect.call_count, 2)

    def test_exception_retry_survives_tick_wrap_and_fires_at_deadline(self):
        wifi = SimpleNamespace(connect=Mock(side_effect=OSError("Offline")))
        app = self.app(wifi)
        self.assertFalse(app._wifi(0xffffff00))
        self.assertEqual(app.next_wifi, 1744)
        for now in (0xffffff01, 0xffffffff, 0, 1743):
            self.assertFalse(app._wifi(now))
        self.assertEqual(wifi.connect.call_count, 1)
        self.assertFalse(app._wifi(1744))
        self.assertEqual(wifi.connect.call_count, 2)

    def test_zero_deadline_is_reserved_for_startup_not_a_retry_loop(self):
        for delay, result in ((1000, False), (2000, OSError("Offline"))):
            with self.subTest(delay=delay):
                connect = Mock(side_effect=result) if isinstance(result, Exception) else Mock(return_value=result)
                wifi = SimpleNamespace(connect=connect, status=Mock(return_value=(-1, "Connecting")))
                app = self.app(wifi)
                self.assertFalse(app._wifi(0x100000000 - delay))
                self.assertEqual(app.next_wifi, 1)
                for now in (0xffffffff, 0):
                    self.assertFalse(app._wifi(now))
                self.assertEqual(connect.call_count, 1)
                self.assertFalse(app._wifi(1))
                self.assertEqual(connect.call_count, 2)

    def test_startup_is_immediate_near_wrap_then_success_is_cached(self):
        wifi = SimpleNamespace(connect=Mock(side_effect=(True, False)),
                               status=Mock(return_value=(-1, "Connecting")))
        app = self.app(wifi)
        self.assertTrue(app._wifi(0xfffffffe))
        self.assertEqual(wifi.connect.call_count, 1)
        self.assertEqual(app.next_wifi, 4998)
        self.assertTrue(app._wifi(0))
        self.assertTrue(app._wifi(4997))
        self.assertEqual(wifi.connect.call_count, 1)
        self.assertFalse(app._wifi(4998))
        self.assertEqual(wifi.connect.call_count, 2)

    def test_missing_configuration_or_wifi_never_connects(self):
        wifi = SimpleNamespace(connect=Mock())
        app = self.app(wifi)
        app.config_error = True
        self.assertFalse(app._wifi(100))
        wifi.connect.assert_not_called()
        self.assertFalse(self.app(None)._wifi(100))


class FakeBadge:
    def __init__(self):
        self.presses = set()
        self.releases = set()

    def pressed(self, button):
        return button in self.presses

    def released(self, button):
        return button in self.releases

    def frame(self, pressed=(), released=()):
        self.presses = set(pressed)
        self.releases = set(released)


class VolumeInputTests(unittest.TestCase):
    def test_old_button_release_does_not_stop_the_new_direction(self):
        for first, second in (("up", "down"), ("down", "up")):
            with self.subTest(first=first, second=second):
                badge = FakeBadge()
                remote = SimpleNamespace(volume=Mock(), release_volume=Mock())
                app = method_class(badge=badge)()
                app.remote = remote
                app.page = "now"
                app.hold_action = None
                badge.frame(pressed=(first,))
                app.input(0)
                self.assertEqual(app.hold_action, first)
                badge.frame(pressed=(second,))
                app.input(1)
                self.assertEqual(app.hold_action, second)
                badge.frame(released=(first,))
                app.input(2)
                remote.release_volume.assert_not_called()
                self.assertEqual(app.hold_action, second)
                badge.frame(released=(second,))
                app.input(3)
                remote.release_volume.assert_called_once_with()
                self.assertIsNone(app.hold_action)

    def test_unrelated_release_and_release_without_remote_are_safe(self):
        badge = FakeBadge()
        app = method_class(badge=badge)()
        app.remote = None
        app.page = "now"
        app.hold_action = "up"
        badge.frame(released=("down",))
        app.input(0)
        self.assertEqual(app.hold_action, "up")
        badge.frame(released=("up",))
        app.input(1)
        self.assertIsNone(app.hold_action)


class FakeScreen:
    def __init__(self):
        self.pen = None
        self.texts = []

    def measure_text(self, text, size=1):
        return len(text) * 6 * size, 12 * size

    def text(self, text, x, y, size=1):
        self.texts.append((text, x, y, self.pen))

    def shape(self, value):
        pass

    def blit(self, *args):
        pass


def draw_now(fresh=True, artwork_message="No cover", **changes):
    screen = FakeScreen()
    pens = {name: name for name in ("PANEL", "WHITE", "MUTED", "ACCENT", "GREEN", "RED")}
    app = method_class(
        names=("_draw_now",), screen=screen, display_text=models.display_text,
        clock_text=models.clock_text, source_label=models.source_label,
        shape=SimpleNamespace(rounded_rectangle=lambda *args: args),
        color=SimpleNamespace(rgb=lambda *args: args), rect=lambda *args: args, **pens)()
    value = {
        "power_on": True, "connected": True, "aux": False,
        "clock_advancing": True, "play_status": 1, "eq_index": 0,
        "duration_ms": 10000, "position_ms": 1000, "position_age_ms": 100,
        "title": "Song", "artist": "Artist", "album": "Album", "eq": "Flat",
    }
    value.update(changes)
    app.playback = models.Playback()
    assert app.playback.accept(value, 0)
    app.artwork = SimpleNamespace(image=None, message=artwork_message)
    app.feedback = "Audio unit authenticated"
    app._draw_now(10 if fresh else 7000)
    return screen.texts


class SourceLabelDrawTests(unittest.TestCase):
    def draw(self, **changes):
        return draw_now(**changes)

    def test_proven_source_is_drawn_muted_below_eq(self):
        for src, label in (("avrcp", "via AVRCP"), ("mac", "via Mac Wi-Fi")):
            with self.subTest(src=src):
                self.assertIn((label, 137, 155, "MUTED"), self.draw(src=src))

    def test_unknown_or_missing_source_draws_nothing(self):
        for changes in ({}, {"src": ""}, {"src": "bt"}, {"src": None}, {"src": 1}):
            with self.subTest(changes=changes):
                texts = [text for text, *_ in self.draw(**changes)]
                self.assertIn("Song", texts)
                self.assertFalse([text for text in texts if text.startswith("via ")])


class NowPageTextTests(unittest.TestCase):
    def test_every_avrcp_play_status_has_a_named_label(self):
        for status, label in ((0, "Stopped"), (1, "Playing"), (2, "Paused"), (3, "Seeking"),
                              (4, "Seeking"), (255, "Playback status unknown")):
            with self.subTest(status=status):
                texts = [(text, x, y) for text, x, y, _ in draw_now(play_status=status)]
                self.assertIn((label, 137, 117), texts)

    def test_long_artwork_message_wraps_inside_the_cover_panel(self):
        for message, logo_y, rows in (
                ("No cover", 82, [118]),
                ("Artwork: bounded fetch support required", 82, [118, 130, 142]),
                ("Artwork: bounded fetch support required for covers", 70, [106, 118, 130, 142])):
            with self.subTest(message=message):
                texts = draw_now(artwork_message=message)
                lines = [(text, y) for text, x, y, pen in texts if x == 18 and pen == "MUTED"]
                self.assertEqual(" ".join(text for text, _ in lines), message)
                self.assertEqual([y for _, y in lines], rows)
                self.assertTrue(all(len(text) * 6 <= 100 for text, _ in lines))
                self.assertIn(("BM83", 43, logo_y, "ACCENT"), texts)

    def test_stale_snapshot_text_is_not_truncated(self):
        texts = [text for text, x, *_ in draw_now(fresh=False) if x == 137]
        self.assertEqual(texts[0], "Waiting for audio unit")
        self.assertEqual(" ".join(texts[1:]), "No fresh playback snapshot")


class MissingNetworkSupportTests(unittest.TestCase):
    def app(self, config_error):
        app = method_class(names=("_start_network", "_control"), Remote=None)()
        app.config_error = config_error
        app.remote = None
        app.feedback = "Waiting for audio unit"
        app.unit_status = "Not connected"
        return app

    def test_missing_socket_is_reported_separately_from_missing_secrets(self):
        app = self.app(False)
        app._start_network()
        self.assertEqual(app.unit_status, "No UDP socket")
        self.assertEqual(app.feedback, "Wi-Fi/UDP unavailable: no socket support")
        app._control("BT_PLAY", 0)
        self.assertEqual(app.feedback, "Wi-Fi/UDP unavailable - command not sent")

    def test_missing_secrets_still_ask_for_configuration(self):
        app = self.app(True)
        app._start_network()
        self.assertEqual(app.unit_status, "Not connected")
        app._control("BT_PLAY", 0)
        self.assertEqual(app.feedback, "Configure Wi-Fi and BM83 secrets first")



class HeaderStatusTests(unittest.TestCase):
    def app(self, connected, remote, remote_class=None):
        app = method_class(names=("step",), Remote=remote_class)()
        app.input = lambda now: None
        app._wifi = lambda now: connected
        app.sample_mode = False
        app.config_error = False
        app.wifi_error = "Wrong password"
        app.remote = remote
        app.playback = models.Playback()
        app.ble = None
        app.feedback = "Waiting for audio unit"
        app.unit_status = "Not connected"
        app.last_art_key = None
        app.hold_action = None
        app.artwork = SimpleNamespace(step=lambda now, connected: None)
        return app

    def remote(self, unit):
        return SimpleNamespace(step=Mock(), unit=unit, playback=models.Playback(),
                               ble=models.BleControl(), held_volume=None,
                               feedback="Audio unit authenticated")

    def test_header_statuses_are_short_and_wifi_detail_moves_to_feedback(self):
        for connected, unit, status, feedback in (
                (True, "01020304", "Authenticated", "Audio unit authenticated"),
                (True, None, "Awaiting unit", "Audio unit authenticated"),
                (False, "01020304", "Wi-Fi offline", "Wi-Fi: Wrong password")):
            with self.subTest(status=status):
                app = self.app(connected, self.remote(unit))
                app.step(0)
                self.assertEqual(app.unit_status, status)
                self.assertEqual(app.feedback, feedback)
                self.assertLessEqual(len(status), 14)

    def test_wifi_offline_without_remote_keeps_setup_feedback(self):
        app = self.app(False, None)
        app.feedback = "Wi-Fi/UDP unavailable: no socket support"
        app.step(0)
        self.assertEqual(app.unit_status, "Wi-Fi offline")
        self.assertEqual(app.feedback, "Wi-Fi/UDP unavailable: no socket support")

    def test_wifi_return_restores_missing_socket_or_failed_setup_header(self):
        for remote_class, status, feedback in (
                (None, "No UDP socket", "Wi-Fi/UDP unavailable: no socket support"),
                (Mock(), "UDP failed", "UDP setup failed: unavailable")):
            with self.subTest(status=status):
                app = self.app(False, None, remote_class)
                app.feedback = feedback
                app.step(0)
                self.assertEqual(app.unit_status, "Wi-Fi offline")
                app._wifi = lambda now: True
                app.step(1000)
                self.assertEqual(app.unit_status, status)
                self.assertEqual(app.feedback, feedback)

    def test_offline_frame_services_remote_and_clears_dropped_input_marker(self):
        remote = self.remote("01020304")
        app = self.app(False, remote)
        app.hold_action = "up"
        app.step(1000)
        remote.step.assert_called_once_with(1000, connected=False)
        self.assertIsNone(app.hold_action)

    def test_offline_frame_keeps_marker_for_a_sent_volume_press(self):
        remote = self.remote("01020304")
        remote.held_volume = "BT_VOLUP"
        app = self.app(False, remote)
        app.hold_action = "up"
        app.step(1000)
        self.assertEqual(app.hold_action, "up")


class OfflineInputTests(unittest.TestCase):
    def test_controls_pressed_during_outage_are_not_sent_after_wifi_returns(self):
        badge = FakeBadge()
        udp = SimpleNamespace(setblocking=Mock(), sendto=Mock(),
                              recvfrom=Mock(side_effect=OSError(errno.EAGAIN, "no reply")))
        with patch.object(transport.socket, "socket", return_value=udp):
            remote = transport.Remote("192.0.2.50", 8767, bytes(range(32)))
        remote.unit, remote.client = "01020304", 7
        app = method_class(names=("step", "input", "_control"), badge=badge,
                           Remote=transport.Remote)()
        app.remote, app.page, app.hold_action = remote, "now", None
        app.sample_mode, app.config_error = False, False
        app._wifi = lambda now: False
        app.wifi_error = "Connecting"
        app.playback, app.ble = remote.playback, remote.ble
        app.last_art_key = None
        app.artwork = SimpleNamespace(step=Mock())
        badge.frame(pressed=("select", "up"))
        app.step(2)
        self.assertFalse(remote.queue)
        self.assertFalse(remote.volume_queue)
        self.assertIsNone(remote.held_volume)
        self.assertIsNone(app.hold_action)
        udp.sendto.assert_not_called()
        udp.recvfrom.assert_not_called()
        badge.frame(released=("up",))
        app._wifi = lambda now: True
        app.step(3)
        sent = [protocol.decode(remote.key, call.args[0])["token"]
                for call in udp.sendto.call_args_list]
        self.assertEqual(sent, ["STATUS"])

class LocalRetryTests(unittest.TestCase):
    def constant(self):
        tree = ast.parse((APP / "__init__.py").read_text())
        return next(ast.literal_eval(node.value) for node in tree.body
                    if isinstance(node, ast.Assign)
                    and getattr(node.targets[0], "id", None) == "LOCAL_RETRY_FEEDBACK")

    def test_app_source_never_names_the_receiver_retry_token(self):
        self.assertNotIn("NET_RETRY", (APP / "__init__.py").read_text())

    def test_settings_retry_is_badge_local_and_queues_nothing(self):
        message = self.constant()
        self.assertLessEqual(len(message), 40)
        badge = FakeBadge()
        app = method_class(names=("input", "_settings", "_control"), badge=badge,
                           clamp_setting_index=models.clamp_setting_index,
                           LOCAL_RETRY_FEEDBACK=message)()
        app.remote = SimpleNamespace(queue_command=Mock(), volume=Mock(), release_volume=Mock(),
                                     feedback="Audio unit authenticated")
        app.ble = models.BleControl()
        app.artwork = SimpleNamespace(retry=Mock())
        app.page, app.setting_index, app.hold_action = "settings", 0, None
        app.erase_confirm, app.wifi_ready, app.next_wifi = False, True, 0
        app.config_error, app.feedback = False, "Audio unit authenticated"
        labels = [label for label, _ in app._settings(0)]
        self.assertEqual(labels[4], "Badge Wi-Fi / artwork retry")
        self.assertNotIn("NET_RETRY", [command for _, command in app._settings(0)])
        for now in range(4):
            badge.frame(pressed=("down",))
            app.input(now)
        self.assertEqual(app.setting_index, 4)
        badge.frame(pressed=("select",))
        app.input(10)
        app.remote.queue_command.assert_not_called()
        app.artwork.retry.assert_called_once_with(10)
        self.assertFalse(app.wifi_ready)
        self.assertEqual(app.next_wifi, 10)
        self.assertEqual(app.feedback, message)
        self.assertEqual(app.remote.feedback, message)

    def test_local_retry_without_remote_still_retries_badge_side(self):
        badge = FakeBadge()
        app = method_class(names=("input", "_settings"), badge=badge,
                           clamp_setting_index=models.clamp_setting_index,
                           LOCAL_RETRY_FEEDBACK=self.constant())()
        app.remote, app.ble = None, models.BleControl()
        app.artwork = SimpleNamespace(retry=Mock())
        app.page, app.setting_index, app.hold_action = "settings", 4, None
        app.erase_confirm, app.wifi_ready, app.next_wifi = False, True, 0
        badge.frame(pressed=("select",))
        app.input(7)
        app.artwork.retry.assert_called_once_with(7)
        self.assertEqual(app.feedback, self.constant())


if __name__ == "__main__":
    unittest.main()

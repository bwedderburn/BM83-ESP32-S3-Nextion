"""Offline checks of badge input and Wi-Fi pacing without starting the app."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
APP = next((path for path in (
    ROOT / "addons/universe-badge/apps/bm83_remote",
    ROOT / "badge/apps/bm83_remote",
) if path.is_dir()), None)
if APP is None:
    raise RuntimeError("Cannot locate the badge BM83 client")

BUTTONS = {"BUTTON_" + name: name.lower()
           for name in ("UP", "DOWN", "LEFT", "RIGHT", "MENU", "BACK", "SELECT")}


def method_class(**globals_):
    """Compile only selected methods, excluding imports, setup and run(update)."""
    tree = ast.parse((APP / "__init__.py").read_text())
    original = next(node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == "BM83Remote")
    methods = [node for node in original.body
               if isinstance(node, ast.FunctionDef) and node.name in ("_wifi", "input")]
    minimal_class = ast.ClassDef(name="BM83Remote", bases=[], keywords=[], body=methods, decorator_list=[])
    isolated = ast.fix_missing_locations(ast.Module(body=[minimal_class], type_ignores=[]))
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


if __name__ == "__main__":
    unittest.main()

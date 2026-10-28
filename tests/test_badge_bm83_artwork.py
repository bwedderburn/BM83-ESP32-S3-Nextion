"""Offline resource-lifecycle tests for badge artwork's bounded fetch adapter."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
APP = next(path for path in (
    ROOT / "addons/universe-badge/apps/bm83_remote",
    ROOT / "badge/apps/bm83_remote",
) if path.is_dir())
SPEC = importlib.util.spec_from_file_location("badge_artwork_bounds", APP / "artwork.py")
artwork = importlib.util.module_from_spec(SPEC)
with patch.dict(sys.modules, {"fetch": None}):
    SPEC.loader.exec_module(artwork)


class FakeCore:
    instances = []

    def __init__(self, host, use_tls, max_bytes, timeout):
        self.host = host
        self.use_tls = use_tls
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.body = b""
        self.done = False
        self.updates = 0
        self.resets = 0
        self.actions = []
        self.http_status = 200
        self.http_response_headers = {}
        self.__class__.instances.append(self)

    def fetch(self, path, headers):
        self.path, self.headers = path, headers

    def update(self):
        self.updates += 1
        if not self.actions:
            return
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        self.body = action
        self.done = True

    def reset(self):
        self.resets += 1
        self.done = False


class ArtworkBoundsTests(unittest.TestCase):
    def setUp(self):
        FakeCore.instances = []
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.destination = Path(self.directory.name) / "cover.tmp"
        self.fetch_patch = patch.object(artwork, "fetch", SimpleNamespace(AsyncFetch=FakeCore))
        self.fetch_patch.start()
        self.addCleanup(self.fetch_patch.stop)

    def request(self, limit=16):
        return artwork.BoundedRequest("https://musicbrainz.org/path?q=1", {},
                                      str(self.destination), limit)

    def active_lookup(self, stage="mb", limit=None):
        app = artwork.Artwork(self.directory.name)
        app.key = "test"
        app._request_url("https://musicbrainz.org/path", stage,
                         artwork.MAX_JSON if limit is None else limit, 0)
        return app, FakeCore.instances[-1]

    def test_unbounded_only_fetch_api_is_never_dispatched(self):
        unbounded_url = Mock(side_effect=AssertionError("unbounded fetch must not start"))
        with patch.object(artwork, "fetch", SimpleNamespace(url=unbounded_url)):
            app = artwork.Artwork(self.directory.name)
            app.key = "test"
            app._request_url("https://musicbrainz.org/path", "mb", artwork.MAX_JSON, 0)
        unbounded_url.assert_not_called()
        self.assertIsNone(app.request)
        self.assertIsNone(app.temp)
        self.assertEqual(app.stage, "")
        self.assertIn("bounded fetch", app.message)

    def test_constructor_without_size_controls_is_rejected_before_fetch(self):
        class LegacyCore:
            calls = 0

            def __init__(self, host, use_tls):
                LegacyCore.calls += 1

        with patch.object(artwork, "fetch", SimpleNamespace(AsyncFetch=LegacyCore)):
            with self.assertRaisesRegex(ValueError, "bounded fetch"):
                self.request()
        self.assertEqual(LegacyCore.calls, 0)
        self.assertFalse(self.destination.exists())

    def test_missing_reset_api_is_rejected_without_dispatch(self):
        core = SimpleNamespace(fetch=Mock(), update=Mock())
        factory = Mock(return_value=core)
        with patch.object(artwork, "fetch", SimpleNamespace(AsyncFetch=factory)):
            with self.assertRaisesRegex(ValueError, "bounded fetch"):
                self.request()
        core.fetch.assert_not_called()
        core.update.assert_not_called()

    def test_stage_limit_and_inactivity_timeout_are_set_before_io(self):
        for stage, limit in (("mb", artwork.MAX_JSON), ("caa", artwork.MAX_JPEG)):
            with self.subTest(stage=stage):
                app, core = self.active_lookup(stage, limit)
                self.assertEqual(core.max_bytes, limit)
                self.assertEqual(core.timeout, artwork.FETCH_TIMEOUT_SECONDS)
                self.assertTrue(core.use_tls)
                self.assertEqual(core.updates, 0)
                self.assertFalse(Path(app.temp).exists())
                app.cancel()
                self.assertEqual(core.resets, 1)

    def test_setup_failure_resets_before_propagating(self):
        class FailingSetupCore(FakeCore):
            def fetch(self, path, headers):
                raise ValueError("setup failed")

        with patch.object(artwork, "fetch", SimpleNamespace(AsyncFetch=FailingSetupCore)):
            with self.assertRaisesRegex(ValueError, "setup failed"):
                self.request()
        self.assertEqual(FailingSetupCore.instances[-1].resets, 1)
        self.assertEqual(FailingSetupCore.instances[-1].updates, 0)

    def test_finished_response_writes_once_and_truthiness_does_not_repump(self):
        request = self.request()
        core = FakeCore.instances[-1]
        core.actions = [b"cover"]
        self.assertFalse(request.done)
        self.assertTrue(bool(request))
        self.assertTrue(request.done)
        self.assertTrue(bool(request))
        self.assertEqual(self.destination.read_bytes(), b"cover")
        self.assertEqual(core.updates, 1)
        self.assertEqual(core.resets, 1)

    def test_error_is_stable_and_resets_the_active_operation(self):
        request = self.request()
        core = FakeCore.instances[-1]
        error = OSError("network failed")
        core.actions = [error]
        self.assertFalse(bool(request))
        self.assertFalse(bool(request))
        self.assertTrue(request.done)
        self.assertIs(request.error, error)
        self.assertEqual(core.updates, 1)
        self.assertEqual(core.resets, 1)
        self.assertFalse(self.destination.exists())

    def test_completed_overlimit_body_is_not_written(self):
        request = self.request(limit=4)
        core = FakeCore.instances[-1]
        core.actions = [b"oversized"]
        self.assertFalse(bool(request))
        self.assertIsInstance(request.error, ValueError)
        self.assertEqual(core.resets, 1)
        self.assertFalse(self.destination.exists())

    def test_reset_failure_is_latched_as_error_without_repumping(self):
        request = self.request()
        core = FakeCore.instances[-1]
        core.actions = [b"cover"]
        with patch.object(core, "reset", side_effect=OSError("reset failed")):
            self.assertFalse(bool(request))
            self.assertFalse(bool(request))
        self.assertIsInstance(request.error, OSError)
        self.assertEqual(core.updates, 1)

    def test_unfinished_overlimit_error_cancels_without_abandoned_transfer(self):
        app, core = self.active_lookup("caa", artwork.MAX_JPEG)
        core.actions = [ValueError("Response exceeds max_bytes")]
        app.step(1, True)
        self.assertIsNone(app.request)
        self.assertEqual(app.stage, "")
        self.assertFalse(hasattr(app, "abandoned"))
        self.assertGreaterEqual(core.resets, 1)
        self.assertFalse((Path(self.directory.name) / "test.tmp").exists())
        app._request_url("https://musicbrainz.org/new", "mb", artwork.MAX_JSON, 2)
        self.assertIsNotNone(app.request)
        self.assertEqual(len(FakeCore.instances), 2)

    def test_total_deadline_stops_an_unfinished_operation(self):
        app, core = self.active_lookup()
        app.step(1, True)
        self.assertEqual(core.updates, 1)
        app.step(45001, True)
        self.assertEqual(app.message, "Artwork lookup timed out")
        self.assertIsNone(app.request)
        self.assertEqual(app.stage, "")
        self.assertEqual(core.resets, 1)
        app.step(100000, True)
        self.assertEqual(core.updates, 1)

    def test_explicit_cancel_never_pumps_the_request_again(self):
        request = self.request()
        core = FakeCore.instances[-1]
        request.cancel()
        self.assertFalse(bool(request))
        self.assertTrue(request.done)
        self.assertEqual(core.updates, 0)
        self.assertEqual(core.resets, 1)

    def test_total_deadline_survives_tick_wrap(self):
        app, core = self.active_lookup()
        app.started = 0xfffffff0
        app.step((app.started + 45001) & 0xffffffff, True)
        self.assertEqual(app.message, "Artwork lookup timed out")
        self.assertIsNone(app.request)
        self.assertEqual(core.updates, 0)
        self.assertEqual(core.resets, 1)

    def test_musicbrainz_wait_preserves_gap_across_tick_wrap(self):
        app = artwork.Artwork(self.directory.name)
        app.key, app.artist, app.album = "test", "Artist", "Album"
        app.started = app.last_mb_at = 0xfffffff0
        app._begin_mb((app.started + 500) & 0xffffffff, False)
        self.assertEqual(app.stage, "mb-wait")
        app.step((app.started + 1000) & 0xffffffff, True)
        self.assertEqual(app.stage, "mb-wait")
        self.assertEqual(FakeCore.instances, [])
        app.step((app.started + artwork.HTTP_GAP_MS) & 0xffffffff, True)
        self.assertEqual(app.stage, "mb")
        self.assertIsNotNone(app.request)
        self.assertEqual(len(FakeCore.instances), 1)

    def test_musicbrainz_wait_obeys_total_deadline_after_tick_wrap(self):
        app = artwork.Artwork(self.directory.name)
        app.started = app.last_mb_at = 0xfffffff0
        app.stage, app.wait_fallback = "mb-wait", False
        app.step((app.started + 45001) & 0xffffffff, True)
        self.assertEqual(app.message, "Artwork lookup timed out")
        self.assertEqual(app.stage, "")
        self.assertEqual(FakeCore.instances, [])

    def test_musicbrainz_wait_stops_when_disconnected(self):
        app = artwork.Artwork(self.directory.name)
        app.stage, app.wait_fallback = "mb-wait", False
        app.step(1, False)
        self.assertEqual(app.message, "Artwork needs internet")
        self.assertEqual(app.stage, "")
        self.assertEqual(FakeCore.instances, [])

    def test_redirect_status_and_headers_survive_socket_reset(self):
        request = self.request()
        core = FakeCore.instances[-1]
        core.http_status = 302
        core.http_response_headers = {"Location": "https://archive.org/cover.jpg"}
        core.actions = [ValueError("HTTP 302")]
        self.assertFalse(bool(request))
        self.assertEqual(artwork._redirect_url(request), "https://archive.org/cover.jpg")
        self.assertEqual(core.resets, 1)

    def test_valid_cached_artwork_does_not_require_fetch_support(self):
        app = artwork.Artwork(self.directory.name)
        key = app._cache_key("Artist", "Album")
        cached = Path(app._path(key, ".jpg"))
        cached.write_bytes(b"cached image")
        decoded = object()
        url = Mock(side_effect=AssertionError("cached art must not fetch"))
        with patch.object(artwork, "fetch", SimpleNamespace(url=url)):
            with patch.object(app, "_decode", return_value=decoded):
                app.start("Artist", "Album", 0)
        self.assertIs(app.image, decoded)
        self.assertEqual(app.path, str(cached))
        self.assertEqual(app.message, "")
        url.assert_not_called()

    def test_invalid_metadata_clears_identity_so_retry_cannot_restore_old_cover(self):
        for artist, album in (("", "Album"), ("Artist", ""), (None, "Album"),
                              ("Artist", 5), ("x" * 97, "Album"), ("Artist", "x" * 97)):
            with self.subTest(artist=artist, album=album):
                FakeCore.instances = []
                app = artwork.Artwork(self.directory.name)
                app.start("Previous artist", "Previous album", 0)
                previous = FakeCore.instances[-1]
                app.image, app.path = object(), "previous.jpg"
                app.start(artist, album, 1)
                app.retry(2)
                self.assertIsNone(app.key)
                self.assertEqual(app.artist, "")
                self.assertEqual(app.album, "")
                self.assertIsNone(app.image)
                self.assertIsNone(app.path)
                self.assertIsNone(app.request)
                self.assertEqual(app.stage, "")
                self.assertEqual(len(FakeCore.instances), 1)
                self.assertEqual(previous.resets, 1)

    def test_interrupted_lookup_resumes_same_identity_exactly_once(self):
        app = artwork.Artwork(self.directory.name)
        app.start("Artist", "Album", 0)
        original_key = app.key
        previous = FakeCore.instances[-1]
        app.step(100, False)
        self.assertTrue(app._resume_after_connect)
        self.assertIsNone(app.request)
        self.assertEqual(previous.resets, 1)
        app.step(1000, False)
        self.assertEqual(len(FakeCore.instances), 1)
        app.step(2000, True)
        self.assertFalse(app._resume_after_connect)
        self.assertEqual((app.artist, app.album, app.key), ("Artist", "Album", original_key))
        self.assertEqual(app.started, 2000)
        self.assertIsNotNone(app.request)
        self.assertEqual(len(FakeCore.instances), 2)
        resumed = FakeCore.instances[-1]
        app.step(2001, True)
        app.step(2002, True)
        self.assertEqual(len(FakeCore.instances), 2)
        self.assertEqual(resumed.updates, 2)

    def test_long_outage_resumes_with_a_fresh_lookup_budget(self):
        app = artwork.Artwork(self.directory.name)
        app.start("Artist", "Album", 0)
        app.step(100, False)
        app.step(100000, True)
        resumed = FakeCore.instances[-1]
        app.step(100001, True)
        self.assertEqual(app.started, 100000)
        self.assertEqual(app.stage, "mb")
        self.assertEqual(resumed.updates, 1)
        self.assertEqual(resumed.resets, 0)

    def test_explicit_cancel_and_close_prevent_connectivity_resume(self):
        for action in ("cancel", "close"):
            with self.subTest(action=action):
                FakeCore.instances = []
                app = artwork.Artwork(self.directory.name)
                app.start("Artist", "Album", 0)
                app.step(100, False)
                getattr(app, action)()
                app.step(2000, True)
                self.assertFalse(app._resume_after_connect)
                self.assertIsNone(app.request)
                self.assertEqual(len(FakeCore.instances), 1)

    def test_invalid_metadata_clears_an_interrupted_lookup_resume(self):
        app = artwork.Artwork(self.directory.name)
        app.start("Artist", "Album", 0)
        app.step(100, False)
        app.start("", "", 200)
        app.step(2000, True)
        self.assertFalse(app._resume_after_connect)
        self.assertEqual((app.artist, app.album), ("", ""))
        self.assertIsNone(app.request)
        self.assertEqual(len(FakeCore.instances), 1)

    def test_completed_cached_cover_is_not_refetched_after_connectivity_change(self):
        app = artwork.Artwork(self.directory.name)
        key = app._cache_key("Artist", "Album")
        Path(app._path(key, ".jpg")).write_bytes(b"cached image")
        decoded = object()
        with patch.object(app, "_decode", return_value=decoded):
            app.start("Artist", "Album", 0)
        app.step(100, False)
        app.step(2000, True)
        self.assertIs(app.image, decoded)
        self.assertFalse(app._resume_after_connect)
        self.assertEqual(FakeCore.instances, [])

    def test_unsupported_fetch_is_stable_across_reconnects(self):
        unbounded_url = Mock(side_effect=AssertionError("unbounded fetch must not start"))
        with patch.object(artwork, "fetch", SimpleNamespace(url=unbounded_url)):
            app = artwork.Artwork(self.directory.name)
            app.start("Artist", "Album", 0)
            original_message = app.message
            for now, connected in ((100, False), (2000, True), (2100, True),
                                   (3000, False), (4000, True)):
                app.step(now, connected)
        self.assertFalse(app._resume_after_connect)
        self.assertIsNone(app.request)
        self.assertEqual(app.message, original_message)
        self.assertIn("bounded fetch", app.message)
        unbounded_url.assert_not_called()

    def test_non_connectivity_failure_does_not_arm_reconnect_resume(self):
        app = artwork.Artwork(self.directory.name)
        app.start("Artist", "Album", 0)
        FakeCore.instances[-1].actions = [OSError("request failed")]
        app.step(1, True)
        for now, connected in ((2, True), (100, False), (2000, True)):
            app.step(now, connected)
        self.assertFalse(app._resume_after_connect)
        self.assertIsNone(app.request)
        self.assertEqual(len(FakeCore.instances), 1)


if __name__ == "__main__":
    unittest.main()

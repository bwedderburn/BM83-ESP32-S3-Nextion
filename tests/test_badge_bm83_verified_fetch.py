"""Host-only verified TLS adapter tests: every socket and TLS context is fake."""

import base64
import errno
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import re
import sys
import unittest
from unittest.mock import Mock, mock_open, patch

ROOT = Path(__file__).resolve().parents[1]
APP = next(path for path in (
    ROOT / "addons/universe-badge/apps/bm83_remote",
    ROOT / "badge/apps/bm83_remote",
) if path.is_dir())


class FakeBase:
    insecure_connections = 0

    def __init__(self, host, use_tls, max_bytes, timeout):
        self._host, self._port, self._use_tls = host, 443, use_tls
        self._addr_info = self._sock = self.operation = None
        self.max_bytes, self.timeout = max_bytes, timeout
        self.done, self.body = False, b""

    def _connect(self):
        FakeBase.insecure_connections += 1
        raise AssertionError("The insecure base _connect must never execute")

    def fetch(self, path, headers):
        self.path, self.headers = path, headers

    def update(self):
        if self.operation is None:
            self.operation = self._connect()
        try:
            next(self.operation)
            return
        except StopIteration:
            pass
        if self._sock.write(b"GET / HTTP/1.1\r\n\r\n"):
            self.done, self.body = True, b"ok"

    def reset(self):
        self.operation = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        self.done = False


class FakeRawSocket:
    def __init__(self, events, connect_error=None):
        self.events, self.connect_error = events, connect_error
        self.closed = False

    def setblocking(self, value):
        self.events.append(("blocking", value))
        if value is not False:
            raise AssertionError("blocking I/O requested")

    def connect(self, address):
        self.events.append(("connect", address))
        if self.connect_error:
            raise self.connect_error
        raise OSError(errno.EINPROGRESS, "pending")

    def close(self):
        self.closed = True
        self.events.append(("close_raw",))


class FakeSocketModule:
    SOCK_STREAM = 1

    def __init__(self, events):
        self.events, self.sockets = events, []
        self.connect_error = None

    def getaddrinfo(self, host, port, *args):
        self.events.append(("dns", host, port))
        return [(2, 1, 6, "", ("192.0.2.1", port))]

    def socket(self, *args):
        self.events.append(("socket",))
        raw = FakeRawSocket(self.events, self.connect_error)
        self.sockets.append(raw)
        return raw


class FakeTLS:
    CERT_NONE = 0
    CERT_REQUIRED = 2
    PROTOCOL_TLS_CLIENT = 16

    def __init__(self, events):
        self.events, self.contexts, self.wrapped = events, [], []
        self.load_error = self.wrap_error = None
        self.bad_certificate = self.bad_hostname = False
        self.handshake_pending = False
        self.ignore_verify_assignment = False

    def SSLContext(self, protocol):
        owner = self

        class Context:
            def __init__(self):
                self.mode = 0
                self.cadata = []

            @property
            def verify_mode(self):
                return self.mode

            @verify_mode.setter
            def verify_mode(self, value):
                owner.events.append(("verify_mode", value))
                if not owner.ignore_verify_assignment:
                    self.mode = value

            def load_verify_locations(self, der):
                owner.events.append(("load_ca",))
                if owner.load_error:
                    raise owner.load_error
                self.cadata.append(der)

            def wrap_socket(self, raw, **kwargs):
                owner.events.append(("wrap", kwargs))
                if owner.wrap_error:
                    raise owner.wrap_error
                if self.mode != owner.CERT_REQUIRED or not self.cadata:
                    raise AssertionError("unverified TLS attempted")
                wrapped = Wrapped(raw, kwargs["server_hostname"])
                owner.wrapped.append(wrapped)
                return wrapped

        class Wrapped:
            def __init__(self, raw, hostname):
                self.raw, self.hostname = raw, hostname
                self.closed, self.http_bytes = False, 0
                self.handshakes = 0

            def setblocking(self, value):
                self.raw.setblocking(value)

            def write(self, data):
                self.handshakes += 1
                if owner.bad_certificate:
                    raise OSError("certificate verification failed")
                if owner.bad_hostname and self.hostname != "musicbrainz.org":
                    raise OSError("hostname verification failed")
                if owner.handshake_pending and self.handshakes == 1:
                    return None
                self.http_bytes += len(data)
                return len(data)

            def close(self):
                self.closed = True
                self.raw.close()

        self.events.append(("context", protocol))
        context = Context()
        self.contexts.append(context)
        return context


class VerifiedFetchTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.sockets, self.tls = FakeSocketModule(self.events), FakeTLS(self.events)
        spec = importlib.util.spec_from_file_location(
            "badge_verified_fetch_test", APP / "verified_fetch.py")
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
                "fetch": SimpleNamespace(AsyncFetch=FakeBase),
                "socket": self.sockets, "tls": self.tls}):
            spec.loader.exec_module(self.module)
        self.module.time = SimpleNamespace(gmtime=lambda: (2026, 11, 1, 0, 0, 0, 0, 0))
        self.module.APP_TRUST = str(APP / "artwork_trust")
        FakeBase.insecure_connections = 0

    def request(self, host="musicbrainz.org"):
        core = self.module.create(host, use_tls=True, max_bytes=32768, timeout=10)
        core.fetch("/path", headers={})
        return core

    def assert_no_network(self):
        self.assertFalse(any(event[0] in ("dns", "socket", "connect", "wrap")
                             for event in self.events), self.events)
        self.assertEqual(FakeBase.insecure_connections, 0)

    def test_cached_required_context_uses_exact_project_ca_before_dns(self):
        first, second = self.request(), self.request("coverartarchive.org")
        self.assertEqual(len(self.tls.contexts), 1)
        pem = (APP / "artwork_trust/cacert.pem").read_bytes()
        expected = [base64.b64decode(value) for value in re.findall(
            rb"-----BEGIN CERTIFICATE-----\s*(.*?)\s*-----END CERTIFICATE-----",
            pem, re.DOTALL)]
        self.assertEqual(self.tls.contexts[0].cadata, expected)
        self.assertEqual(self.tls.contexts[0].verify_mode, self.tls.CERT_REQUIRED)
        self.assert_no_network()
        first.update()
        second.update()
        self.assertEqual(len(self.tls.contexts), 1)
        wraps = [event[1] for event in self.events if event[0] == "wrap"]
        self.assertEqual([item["server_hostname"] for item in wraps],
                         ["musicbrainz.org", "coverartarchive.org"])
        self.assertTrue(all(item["do_handshake_on_connect"] is False for item in wraps))
        self.assertTrue(all(event[1] is False for event in self.events
                            if event[0] == "blocking"))
        self.assertEqual(FakeBase.insecure_connections, 0)

    def test_nonblocking_handshake_yields_without_http_then_completes(self):
        self.tls.handshake_pending = True
        core = self.request()
        core.update()
        self.assertEqual(self.tls.wrapped[0].handshakes, 0)
        core.update()
        self.assertFalse(core.done)
        self.assertEqual(self.tls.wrapped[0].http_bytes, 0)
        core.update()
        self.assertTrue(core.done)
        core.reset()
        self.assertTrue(self.tls.wrapped[0].closed)
        self.assertIsNone(core._sock)

    def test_untrusted_certificate_or_wrong_hostname_sends_no_http(self):
        for reason in ("bad_certificate", "bad_hostname"):
            with self.subTest(reason=reason):
                setattr(self.tls, reason, True)
                core = self.request("coverartarchive.org")
                core.update()
                with self.assertRaisesRegex(OSError, "verification failed"):
                    core.update()
                self.assertEqual(self.tls.wrapped[-1].http_bytes, 0)
                core.reset()
                self.assertTrue(self.tls.wrapped[-1].closed)
                setattr(self.tls, reason, False)
        self.assertEqual(FakeBase.insecure_connections, 0)

    def test_invalid_clock_fails_before_context_dns_and_after_cached_creation(self):
        for clock in ((2021, 1, 1), (2100, 1, 1)):
            with self.subTest(clock=clock):
                self.module.time.gmtime = lambda: clock
                with self.assertRaisesRegex(ValueError, "valid UTC clock"):
                    self.request()
                self.assert_no_network()
        self.assertEqual(len(self.tls.contexts), 0)
        self.module.time.gmtime = lambda: (2026, 11, 1)
        core = self.request()
        self.module.time.gmtime = lambda: (2021, 1, 1)
        with self.assertRaisesRegex(ValueError, "valid UTC clock"):
            core.update()
        with self.assertRaisesRegex(ValueError, "valid UTC clock"):
            core.fetch("/other", {})
        self.assert_no_network()

    def test_missing_required_api_or_ignored_mode_fails_closed(self):
        for tls in (None, SimpleNamespace(CERT_REQUIRED=2),
                    SimpleNamespace(CERT_REQUIRED=2, SSLContext=lambda arg: object(),
                                    PROTOCOL_TLS_CLIENT=16)):
            with self.subTest(tls=tls), patch.object(self.module, "tls", tls):
                with self.assertRaises(ValueError):
                    self.request()
                self.assert_no_network()
        self.tls.ignore_verify_assignment = True
        with self.assertRaisesRegex(ValueError, "verification disabled"):
            self.request()
        self.assertIsNone(self.module._Context)
        self.assert_no_network()

    def test_ca_parse_or_unsupported_positional_api_fails_closed_and_is_not_cached(self):
        for error in (ValueError("invalid CA"), TypeError("unsupported cadata")):
            with self.subTest(error=error):
                self.tls.load_error = error
                with self.assertRaises(type(error)):
                    self.request()
                self.assertIsNone(self.module._Context)
                self.assert_no_network()
        self.tls.load_error = None
        self.request()
        self.assertEqual(len(self.tls.contexts), 3)

    def test_bad_ca_bundle_is_rejected_before_tls_or_network(self):
        with patch("builtins.open", mock_open(read_data=b"bad")):
            with self.assertRaisesRegex(ValueError, "CA bundle rejected"):
                self.request()
        self.assert_no_network()
        self.assertIsNone(self.module._Context)

    def test_truncated_bad_count_length_and_trailing_store_are_rejected(self):
        valid = (APP / "artwork_trust/roots.der-store").read_bytes()
        cases = (valid[:6], b"BMCA1\x00\x75" + valid[7:],
                 valid[:7] + b"\x20\x01" + valid[9:], valid[:-1], valid + b"x")
        for data in cases:
            with self.subTest(size=len(data)):
                with patch("builtins.open", mock_open(read_data=data)):
                    with self.assertRaises(ValueError):
                        self.request()
                self.assertIsNone(self.module._Context)
                self.assert_no_network()

    def test_connect_and_wrap_api_errors_close_raw_socket_and_clear_dns(self):
        for error in (OSError(errno.ECONNREFUSED, "refused"),
                      TypeError("SNI unsupported")):
            with self.subTest(error=error):
                core = self.request()
                if isinstance(error, OSError):
                    self.sockets.connect_error = error
                else:
                    self.tls.wrap_error = error
                with self.assertRaises(type(error)):
                    core.update()
                self.assertTrue(self.sockets.sockets[-1].closed)
                self.assertIsNone(core._sock)
                self.assertIsNone(core._addr_info)
                self.sockets.connect_error = self.tls.wrap_error = None
        self.assertEqual(FakeBase.insecure_connections, 0)

    def test_cancel_then_reuse_and_app_exit_release_cached_context(self):
        core = self.request()
        core.update()
        core.reset()
        core.reset()
        self.assertTrue(self.tls.wrapped[0].closed)
        self.assertEqual(len(self.tls.contexts), 1)
        self.request()
        self.assertEqual(len(self.tls.contexts), 1)
        self.module.release_context()
        self.assertIsNone(self.module._Context)
        self.request()
        self.assertEqual(len(self.tls.contexts), 2)

    def test_cached_context_tampering_fails_closed(self):
        self.request()
        self.tls.contexts[0].mode = self.tls.CERT_NONE
        with self.assertRaisesRegex(ValueError, "verification disabled"):
            self.request()
        self.assert_no_network()

    def test_unapproved_host_non_tls_or_unbounded_settings_are_rejected(self):
        cases = (("evil.example", True, 32, 10),
                 ("musicbrainz.org:80", True, 32, 10),
                 ("musicbrainz.org", False, 32, 10),
                 ("musicbrainz.org", True, 131073, 10),
                 ("musicbrainz.org", True, 32, 11))
        for host, use_tls, max_bytes, timeout in cases:
            with self.subTest(host=host, tls=use_tls, size=max_bytes, timeout=timeout):
                with self.assertRaisesRegex(ValueError, "bounded fetch"):
                    self.module.create(host, use_tls, max_bytes, timeout)
        self.assert_no_network()

    def test_clock_recovery_is_bounded_with_backoff_and_tick_wrap(self):
        self.module.time.gmtime = lambda: (2021, 1, 1)
        sync = Mock(side_effect=OSError("NTP unavailable"))
        self.module.ntptime = SimpleNamespace(timeout=1, settime=sync)
        for start in (0, 0xfffffff0):
            with self.subTest(start=start):
                sync.reset_mock()
                recovery = self.module.ClockRecovery()
                for delta in (0, 1, 4999):
                    self.assertFalse(recovery.step((start + delta) & 0xffffffff))
                self.assertEqual(sync.call_count, 1)
                self.assertFalse(recovery.step((start + 5000) & 0xffffffff))
                self.assertEqual(sync.call_count, 2)
                self.assertFalse(recovery.step((start + 34999) & 0xffffffff))
                self.assertEqual(sync.call_count, 2)
                for delta in (35000, 35001, 100000, 1000000):
                    self.assertFalse(recovery.step((start + delta) & 0xffffffff))
                self.assertEqual(sync.call_count, 3)
                self.assertIn("clock", recovery.message)
                recovery.rearm()
                self.assertFalse(recovery.step((start + 1000001) & 0xffffffff))
                self.assertEqual(sync.call_count, 4)
        self.assert_no_network()

    def test_clock_recovery_success_yields_whole_turn_and_valid_clock_skips_ntp(self):
        year = [2021]
        self.module.time.gmtime = lambda: (year[0], 1, 1)
        sync = Mock(side_effect=lambda: year.__setitem__(0, 2026))
        self.module.ntptime = SimpleNamespace(timeout=1, settime=sync)
        recovery = self.module.ClockRecovery()
        self.assertFalse(recovery.step(0))
        self.assertEqual(sync.call_count, 1)
        self.assertTrue(recovery.step(1))
        self.assertTrue(recovery.step(100000))
        recovery.rearm()
        self.assertTrue(recovery.step(100001))
        self.assertEqual(sync.call_count, 1)
        self.assertEqual(self.tls.contexts, [])
        self.assert_no_network()

    def test_clock_recovery_rejects_missing_or_unbounded_ntp_without_io(self):
        self.module.time.gmtime = lambda: (2021, 1, 1)
        sync = Mock(side_effect=AssertionError("unsupported NTP must not execute"))
        for module in (None, SimpleNamespace(timeout=1),
                       SimpleNamespace(timeout=0, settime=sync),
                       SimpleNamespace(timeout=2, settime=sync)):
            with self.subTest(module=module):
                self.module.ntptime = module
                recovery = self.module.ClockRecovery()
                for now in (0, 5000, 35000):
                    self.assertFalse(recovery.step(now))
                self.assertEqual(recovery.attempts, 3)
                self.assertIn("clock sync support", recovery.message)
        sync.assert_not_called()
        self.assert_no_network()

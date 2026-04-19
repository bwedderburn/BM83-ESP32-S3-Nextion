"""Tests for blehid.ble.BleHid.

Covers advertising backoff on exceptions, connect/disconnect edge
handling, and pairing retry throttling/attempt limits. All
CircuitPython-only imports are stubbed out so the tests run in CI.
"""
import time
from unittest import mock

from blehid.ble import BleHid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeBLE:
    """Minimal stand-in for ``adafruit_ble.BLERadio``."""

    def __init__(self):
        self.name = ""
        self.connected = False
        self.advertising = False
        self._connections = []
        self._adv_calls = 0
        self._stop_adv_calls = 0
        self._adv_error = None   # set to an Exception to simulate failures

    @property
    def connections(self):
        return self._connections

    def start_advertising(self, adv):
        if self._adv_error:
            raise self._adv_error
        self.advertising = True
        self._adv_calls += 1

    def stop_advertising(self):
        self.advertising = False
        self._stop_adv_calls += 1


class FakeCC:
    """Minimal stand-in for ``adafruit_hid.consumer_control.ConsumerControl``."""

    def __init__(self):
        self.last_sent = None

    def send(self, code):
        self.last_sent = code


class FakeCCC:
    """Minimal stand-in for ``ConsumerControlCode``."""
    VOLUME_INCREMENT = 0xE9
    VOLUME_DECREMENT = 0xEA
    MUTE = 0xE2


class FakeConnection:
    """Minimal stand-in for a BLE connection object."""

    def __init__(self, paired=False):
        self.paired = paired
        self.pair_called = False

    def pair(self):
        self.pair_called = True
        self.paired = True


def _make_ready(ble_hid):
    """Patch a BleHid instance so it thinks setup() succeeded."""
    fake_ble = FakeBLE()
    fake_cc = FakeCC()
    ble_hid._ble = fake_ble
    ble_hid._cc = fake_cc
    ble_hid._CCC = FakeCCC
    ble_hid._adv = object()   # non-None sentinel
    ble_hid._hid = mock.MagicMock()
    ble_hid._ready = True
    return fake_ble, fake_cc


# ---------------------------------------------------------------------------
# Advertising backoff
# ---------------------------------------------------------------------------

def test_adv_backoff_on_generic_error():
    """A non-OOM error should set a flat 4 s backoff."""
    hid = BleHid(True, "test")
    ble, _ = _make_ready(hid)
    ble._adv_error = RuntimeError("something broke")

    hid._start_adv(force=True)

    # inhibit_until should be ~4 s in the future
    assert hid._adv_inhibit_until > time.monotonic()
    assert hid._adv_oom_count == 0  # generic, not OOM


def test_adv_backoff_grows_on_nimble_oom():
    """Nimble OOM errors should increment _adv_oom_count and grow backoff."""
    hid = BleHid(True, "test")
    ble, _ = _make_ready(hid)
    ble._adv_error = RuntimeError("Nimble out of memory")

    hid._start_adv(force=True)
    assert hid._adv_oom_count == 1

    # Clear the inhibit window so the next attempt isn't suppressed.
    hid._adv_inhibit_until = 0.0
    hid._start_adv(force=True)
    assert hid._adv_oom_count == 2


def test_adv_inhibit_prevents_start():
    """While inhibited, _start_adv should do nothing."""
    hid = BleHid(True, "test")
    ble, _ = _make_ready(hid)
    hid._adv_inhibit_until = time.monotonic() + 999

    hid._start_adv(force=True)
    assert ble._adv_calls == 0  # should be blocked


def test_adv_kick_restarts_advertising():
    """tick() should restart advertising when the kick period elapses."""
    hid = BleHid(True, "test")
    ble, _ = _make_ready(hid)
    ble.advertising = True  # pretend already advertising
    hid._last_adv_kick_at = 0.0  # far in the past

    hid.tick()

    # _start_adv(force=True) should have been called, which calls
    # stop_advertising then start_advertising.
    assert ble._stop_adv_calls >= 1
    assert ble._adv_calls >= 1


# ---------------------------------------------------------------------------
# Connect / disconnect edge handling
# ---------------------------------------------------------------------------

def test_on_connect_sets_pairing_check():
    """_on_connect should set _need_pairing_check and reset pair attempts."""
    hid = BleHid(True, "test")
    ble, _ = _make_ready(hid)

    # Simulate connection edge via tick()
    ble.connected = True
    hid.tick()

    assert hid._need_pairing_check is True
    assert hid._pair_attempts == 0


def test_on_disconnect_kicks_advertising():
    """_on_disconnect should start advertising immediately."""
    hid = BleHid(True, "test")
    ble, _ = _make_ready(hid)

    # Simulate connect then disconnect
    ble.connected = True
    hid.tick()
    ble.connected = False
    hid.tick()

    assert hid._need_pairing_check is False
    assert ble._adv_calls >= 1


def test_is_connected_reflects_ble_state():
    """is_connected() should mirror _ble.connected."""
    hid = BleHid(True, "test")
    ble, _ = _make_ready(hid)

    assert hid.is_connected() is False
    ble.connected = True
    assert hid.is_connected() is True


def test_is_connected_false_when_disabled():
    """is_connected() returns False when BLE is disabled."""
    hid = BleHid(False, "test")
    assert hid.is_connected() is False


# ---------------------------------------------------------------------------
# Pairing retry throttling / attempt limits
# ---------------------------------------------------------------------------

def test_ensure_paired_respects_throttle():
    """_ensure_paired should skip if called within the retry window."""
    hid = BleHid(True, "test")
    ble, _ = _make_ready(hid)
    ble.connected = True
    conn = FakeConnection(paired=False)
    ble._connections = [conn]

    hid._need_pairing_check = True
    hid._last_pair_try_at = time.monotonic()  # just tried
    hid._ensure_paired()

    # Should have been throttled — pair() not called
    assert not conn.pair_called


def test_ensure_paired_stops_after_limit():
    """_ensure_paired should give up after _pair_attempt_limit attempts."""
    hid = BleHid(True, "test")
    ble, _ = _make_ready(hid)
    ble.connected = True

    hid._need_pairing_check = True
    hid._pair_attempts = hid._pair_attempt_limit  # at limit

    hid._ensure_paired()

    assert hid._need_pairing_check is False  # gave up


def test_ensure_paired_pairs_connection():
    """_ensure_paired should call pair() on an unpaired connection."""
    hid = BleHid(True, "test")
    ble, _ = _make_ready(hid)
    ble.connected = True
    conn = FakeConnection(paired=False)
    ble._connections = [conn]

    hid._need_pairing_check = True
    hid._last_pair_try_at = 0.0  # long ago
    hid._ensure_paired()

    assert conn.pair_called
    assert conn.paired
    assert hid._need_pairing_check is False


def test_ensure_paired_skips_already_paired():
    """_ensure_paired should clear the flag if connection is already paired."""
    hid = BleHid(True, "test")
    ble, _ = _make_ready(hid)
    ble.connected = True
    conn = FakeConnection(paired=True)
    ble._connections = [conn]

    hid._need_pairing_check = True
    hid._last_pair_try_at = 0.0
    hid._ensure_paired()

    assert not conn.pair_called
    assert hid._need_pairing_check is False

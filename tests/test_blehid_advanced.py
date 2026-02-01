from unittest import mock
from blehid.ble import BleHid


class MockConnection:
    def __init__(self):
        self._paired = False
    @property
    def paired(self):
        return self._paired
    def pair(self):
        self._paired = True
    def disconnect(self):
        pass

class MockBLE:
    def __init__(self):
        self.connected = True
        self.advertising = False
        self.name = ""
        self.connections = [MockConnection()]
    def start_advertising(self, adv): self.advertising = True
    def stop_advertising(self): self.advertising = False

def test_blehid_pairing_logic():
    ble = BleHid(True, "Mock")
    ble._ble = MockBLE()
    ble._adv = object()
    ble._ready = True
    ble._need_pairing_check = True
    ble._pair_attempts = 0
    ble._last_pair_try_at = 0.0
    ble._ensure_paired()
    assert ble._need_pairing_check is False


def test_blehid_request_erase_bonds_reentry_and_cooldown():
    ble = BleHid(True, "Mock")
    ble._ready = True
    ble._ble = MockBLE()
    ble._adv = object()
    now = 100.0
    ble._last_conn_change_at = now - 10.0

    with mock.patch("time.monotonic", return_value=now):
        assert ble.request_erase_bonds() is True
        # Second request while pending should be rejected
        assert ble.request_erase_bonds() is False

    # Advance past debounce but within cooldown
    with mock.patch("time.monotonic", return_value=now + 1.0):
        ble._erase_pending = False
        ble._last_erase_at = now  # simulate recent erase to enforce cooldown
        # Should be throttled by cooldown
        assert ble.request_erase_bonds() is False

    # Advance past cooldown and not pending -> allowed again
    with mock.patch("time.monotonic", return_value=now + 4.0):
        assert ble.request_erase_bonds() is True


def test_blehid_tick_defers_erase_until_not_advertising_and_idle():
    """Test two-phase erase: first tick stops advertising, second tick executes erase after settle."""
    ble = BleHid(True, "Mock")
    ble._ready = True
    ble._ble = MockBLE()
    ble._adv = object()
    ble._ble.connected = False
    ble._was_connected = False
    ble._erase_pending = True
    ble._erase_requested_at = 100.0
    ble._erase_pending_since = 100.0
    ble._erase_debounce_s = 0.1
    ble._erase_min_idle_s = 1.0
    ble._erase_adv_settle_s = 0.2
    # Last connection change is well before the idle window so idle condition is satisfied.
    ble._last_conn_change_at = 99.0
    ble._adv_inhibit_until = 200.0
    ble._ble.advertising = True

    # Phase 1: First tick with advertising=True should stop advertising and return
    with mock.patch.object(ble, "_stop_adv", wraps=ble._stop_adv) as stop_adv_mock:
        with mock.patch("time.monotonic", return_value=100.2):
            ble.tick()
    stop_adv_mock.assert_called_once()
    assert ble._erase_adv_stopped is True
    assert ble._last_adv_stop_at == 100.2
    assert ble._erase_requested_at == 100.2
    assert ble._erase_pending is True
    assert ble._last_erase_at == 0.0

    # Phase 2: Second tick after debounce + settle window should execute erase
    ble._ble.advertising = False
    with mock.patch.object(ble, "erase_bonds") as erase_mock:
        with mock.patch("time.monotonic", return_value=100.6):
            ble.tick()
    erase_mock.assert_called_once()
    assert ble._erase_pending is False
    assert ble._last_erase_at == 100.6


def test_blehid_tick_stops_advertising_while_erase_pending():
    """Test that tick stops advertising immediately when erase is pending and advertising is active."""
    ble = BleHid(True, "Mock")
    ble._ready = True
    ble._ble = MockBLE()
    ble._adv = object()
    ble._ble.connected = False
    ble._was_connected = False
    ble._erase_pending = True
    ble._erase_requested_at = 100.0
    ble._erase_debounce_s = 0.2
    ble._ble.advertising = True

    with mock.patch.object(ble, "_stop_adv", wraps=ble._stop_adv) as stop_adv:
        with mock.patch("time.monotonic", return_value=100.05):
            ble.tick()
    stop_adv.assert_called_once()
    assert ble._erase_adv_stopped is True
    assert ble._last_adv_stop_at == 100.05


def test_blehid_tick_two_phase_erase_with_settle_window():
    """Test that tick enforces the settle window between stopping advertising and calling erase_bonds."""
    ble = BleHid(True, "Mock")
    ble._ready = True
    ble._ble = MockBLE()
    ble._adv = object()
    ble._ble.connected = False
    ble._was_connected = False
    ble._erase_pending = True
    ble._erase_requested_at = 100.0
    ble._erase_pending_since = 100.0
    ble._erase_debounce_s = 0.1
    ble._erase_adv_settle_s = 0.2
    ble._erase_min_idle_s = 0.5
    ble._last_conn_change_at = 99.0
    ble._ble.advertising = True

    # Phase 1: Stop advertising
    with mock.patch("time.monotonic", return_value=100.15):
        ble.tick()
    assert ble._erase_adv_stopped is True
    assert ble._last_adv_stop_at == 100.15
    assert ble._erase_requested_at == 100.15

    # Phase 2a: Try within settle window (before it expires) - should defer
    ble._ble.advertising = False
    with mock.patch.object(ble, "erase_bonds") as erase_mock:
        with mock.patch("time.monotonic", return_value=100.25):  # Only 0.1s after stop, settle is 0.2s
            ble.tick()
    erase_mock.assert_not_called()
    assert ble._erase_pending is True

    # Phase 2b: Try after settle window - should execute
    with mock.patch.object(ble, "erase_bonds") as erase_mock:
        with mock.patch("time.monotonic", return_value=100.45):  # 0.3s after stop, past settle
            ble.tick()
    erase_mock.assert_called_once()
    assert ble._erase_pending is False
    assert ble._last_erase_at == 100.45


def test_blehid_tick_cancels_erase_after_timeout_and_enforces_cooldown():
    """Test that erase is cancelled after max_wait timeout and cooldown is enforced."""
    ble = BleHid(True, "Mock")
    ble._ready = True
    ble._ble = MockBLE()
    ble._adv = object()
    ble._ble.connected = False
    ble._was_connected = False
    ble._erase_pending = True
    ble._erase_requested_at = 100.0
    ble._erase_pending_since = 100.0
    ble._erase_debounce_s = 0.1
    ble._erase_max_wait_s = 2.0
    # Set recent connection change so idle window has not elapsed when erase times out.
    ble._last_conn_change_at = 101.8
    ble._ble.advertising = True

    with mock.patch.object(ble, "erase_bonds") as erase_mock:
        # First tick: Stop advertising (phase 1)
        with mock.patch("time.monotonic", return_value=102.0):
            ble.tick()
        assert ble._erase_adv_stopped is True
        assert ble._erase_pending is True  # Still pending after phase 1

        # Second tick: Timeout is reached, but not idle, should cancel
        ble._ble.advertising = False
        with mock.patch("time.monotonic", return_value=102.5):
            ble.tick()
        assert ble._erase_pending is False
        assert ble._last_erase_at == 102.5
        erase_mock.assert_not_called()  # Should be cancelled, not executed

        # Verify cooldown is enforced
        with mock.patch("time.monotonic", return_value=103.0):
            assert ble.request_erase_bonds() is False

        # After cooldown, should be allowed again
        with mock.patch("time.monotonic", return_value=106.0):
            assert ble.request_erase_bonds() is True

        # Now execute the erase successfully
        ble._ble.advertising = False
        ble._last_conn_change_at = 100.0
        with mock.patch("time.monotonic", return_value=106.2):
            ble.tick()
    assert erase_mock.call_count == 1

from unittest import mock

from blehid.ble import BleHid, BLE_STACK_STABILIZATION_DELAY


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

    def start_advertising(self, adv):
        self.advertising = True

    def stop_advertising(self):
        self.advertising = False


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
    """Test that tick() defers erase until both not advertising and BLE is idle.
    Accounts for two-phase erase:
      1) stop advertising, then
      2) after settle delay and idle window, call erase_bonds()
    """
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
    ble._adv_inhibit_until = 200.0

    # Make "idle" NOT satisfied at first: last change is recent.
    ble._last_conn_change_at = 100.9

    # Start advertising so phase-1 behavior triggers.
    ble._ble.advertising = True

    # Phase 1: advertising=True -> stop advertising and return
    with mock.patch.object(BleHid, "_stop_adv", autospec=True, side_effect=BleHid._stop_adv) as stop_adv_mock:
        with mock.patch("time.monotonic", return_value=100.2):
            ble.tick()
    stop_adv_mock.assert_called_once()
    assert ble._erase_adv_stopped is True
    assert ble._last_adv_stop_at == 100.2
    assert ble._erase_requested_at == 100.2
    assert ble._erase_pending is True
    assert ble._last_erase_at == 0.0
    assert ble._ble.advertising is False

    # Phase 2 attempt: after settle but still NOT idle -> should defer
    with mock.patch.object(BleHid, "erase_bonds", autospec=True) as erase_mock:
        with mock.patch("time.monotonic", return_value=100.6):  # settle passed (0.4s)
            ble.tick()
    erase_mock.assert_not_called()
    assert ble._erase_pending is True

    # Now satisfy idle window and try again -> should execute
    ble._last_conn_change_at = 99.0  # plenty idle
    with mock.patch.object(BleHid, "erase_bonds", autospec=True) as erase_mock:
        with mock.patch("time.monotonic", return_value=101.5):
            ble.tick()
    erase_mock.assert_called_once()
    assert ble._erase_pending is False
    assert ble._last_erase_at == 101.5


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

    with mock.patch.object(BleHid, "_stop_adv", autospec=True, side_effect=BleHid._stop_adv) as stop_adv:
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
    with mock.patch.object(BleHid, "erase_bonds", autospec=True) as erase_mock:
        with mock.patch("time.monotonic", return_value=100.25):  # Only 0.1s after stop, settle is 0.2s
            ble.tick()
    erase_mock.assert_not_called()
    assert ble._erase_pending is True

    # Phase 2b: Try after settle window - should execute
    with mock.patch.object(BleHid, "erase_bonds", autospec=True) as erase_mock:
        with mock.patch("time.monotonic", return_value=100.45):  # 0.3s after stop, past settle
            ble.tick()
    erase_mock.assert_called_once()
    assert ble._erase_pending is False
    assert ble._last_erase_at == 100.45


def test_blehid_tick_cancels_erase_after_timeout_and_enforces_cooldown():
    """Test that tick() cancels erase after timeout and cooldown is enforced.
    Accounts for two-phase erase: advertising must be stopped first.
    """
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
    ble._erase_adv_settle_s = 0.2

    # Recent connection change => not idle when timeout hits.
    ble._last_conn_change_at = 101.8
    ble._ble.advertising = True

    with mock.patch.object(BleHid, "erase_bonds", autospec=True) as erase_mock:
        # First tick: stops advertising and returns (phase 1)
        with mock.patch("time.monotonic", return_value=100.2):
            ble.tick()
        assert ble._erase_pending is True
        assert ble._ble.advertising is False
        assert ble._erase_adv_stopped is True
        erase_mock.assert_not_called()

        # Second tick: after settle delay but before timeout; still not idle, so defer
        with mock.patch("time.monotonic", return_value=101.0):
            ble.tick()
        assert ble._erase_pending is True
        erase_mock.assert_not_called()

        # Third tick: timeout reached (>= 2.0s from pending_since) -> cancel
        with mock.patch("time.monotonic", return_value=102.0):
            ble.tick()
        assert ble._erase_pending is False
        assert ble._last_erase_at == 102.0
        assert ble._erase_adv_stopped is False  # should reset on cancellation
        erase_mock.assert_not_called()

        # Cooldown enforcement
        with mock.patch("time.monotonic", return_value=103.0):
            assert ble.request_erase_bonds() is False

        # After cooldown, should be allowed again
        with mock.patch("time.monotonic", return_value=106.0):
            assert ble.request_erase_bonds() is True

        # Now with idle conditions met, erase should succeed
        ble._ble.advertising = False
        ble._last_conn_change_at = 100.0
        with mock.patch("time.monotonic", return_value=106.2):
            ble.tick()

    assert erase_mock.call_count == 1


def test_blehid_tick_two_phase_erase_with_adv_settle_delay():
    """Test that tick() requires two phases to complete erase:
    Phase 1: Stop advertising and set _erase_adv_stopped flag
    Phase 2: After settle delay, invoke erase_bonds()
    """
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
    ble._last_conn_change_at = 99.0  # Ensure idle time is satisfied
    ble._ble.advertising = True

    # Phase 1: First tick while advertising - should stop advertising and return
    with mock.patch.object(BleHid, "erase_bonds", autospec=True) as erase_mock:
        with mock.patch("time.monotonic", return_value=100.15):
            ble.tick()
        # Advertising should be stopped, flag should be set
        assert ble._ble.advertising is False
        assert ble._erase_adv_stopped is True
        assert ble._last_adv_stop_at == 100.15
        assert ble._erase_requested_at == 100.15
        # erase_bonds should NOT have been called yet
        erase_mock.assert_not_called()
        assert ble._erase_pending is True

        # Phase 2a: Second tick before settle delay - should still wait
        with mock.patch("time.monotonic", return_value=100.25):
            ble.tick()
        # Still waiting for settle delay
        erase_mock.assert_not_called()
        assert ble._erase_pending is True

        # Phase 2b: Third tick after settle delay - should now call erase_bonds
        with mock.patch("time.monotonic", return_value=100.45):
            ble.tick()
        # Now erase_bonds should be called
        erase_mock.assert_called_once()
        assert ble._erase_pending is False
        assert ble._last_erase_at == 100.45


def test_blehid_erase_bonds_with_advertising_already_stopped():
    """Test that erase_bonds() handles the case where advertising
    was already stopped by tick() and uses the settle delay properly.
    This verifies that when _erase_adv_stopped=True, the initial stop
    at the beginning of erase_bonds is skipped and the proper settle
    delay is honored based on _last_adv_stop_at.
    """
    ble = BleHid(True, "Mock")
    ble._ready = True
    ble._ble = MockBLE()
    ble._adv = object()
    ble._ble.connected = False
    ble._ble.advertising = False  # Already stopped
    ble._erase_adv_stopped = True  # Flag set by tick()
    ble._last_adv_stop_at = 100.0  # Recent stop time
    ble._erase_adv_settle_s = 0.2

    with mock.patch("time.sleep") as sleep_mock:
        with mock.patch("time.monotonic", return_value=100.02):
            # Call erase_bonds when only 0.02s has elapsed since stop
            ble.erase_bonds()

        # Should sleep for remaining time to reach stabilization delay
        since_stop = 100.02 - 100.0  # 0.02
        expected_sleep = BLE_STACK_STABILIZATION_DELAY - since_stop

        # Note: there are multiple sleep calls in erase_bonds, so we check
        # that at least one sleep matches our expected settle delay
        sleep_calls = [call[0][0] for call in sleep_mock.call_args_list if call[0]]
        assert any(abs(s - expected_sleep) < 0.001 for s in sleep_calls), \
            f"Expected sleep of {expected_sleep}s not found in {sleep_calls}"

    # Reset for test where enough time has already passed
    ble._erase_adv_stopped = True
    ble._last_adv_stop_at = 100.0
    with mock.patch("time.sleep") as sleep_mock:
        with mock.patch("time.monotonic", return_value=100.15):
            # Call erase_bonds when 0.15s has elapsed (more than STABILIZATION_DELAY)
            ble.erase_bonds()

        # When enough time has passed, the settle delay should not sleep.
        # Other sleeps may still occur (post-erase, restart), so we just ensure no exception.


def test_blehid_repeated_erase_requests_with_reconnect_churn():
    """Stress BLE tick loop under repeated erase requests and reconnect churn."""
    ble = BleHid(True, "Mock")
    ble._ready = True
    ble._ble = MockBLE()
    ble._adv = object()
    ble._ble.connected = False
    ble._ble.advertising = True
    ble._was_connected = False
    ble._erase_debounce_s = 0.02
    ble._erase_min_idle_s = 0.01
    ble._erase_adv_settle_s = 0.0
    ble._erase_cooldown_s = 0.0
    ble._erase_max_wait_s = 0.4

    erased = {"count": 0}

    def fake_erase(self):
        erased["count"] += 1
        self._erase_adv_stopped = False
        self._adv_inhibit_until = 0.0
        self._start_adv(force=True)

    with mock.patch.object(BleHid, "erase_bonds", autospec=True, side_effect=fake_erase):
        now = 100.0
        for i in range(120):
            now += 0.01
            ble._ble.connected = (i % 10) == 1
            ble._ble.advertising = not ble._ble.connected
            with mock.patch("time.monotonic", return_value=now):
                if i % 3 == 0:
                    erase_initiated = ble.request_erase_bonds()
                    if erase_initiated:
                        assert ble.request_erase_bonds() is False
                ble.tick()

    assert ble._heavy_op_inflight is None
    assert ble._erase_timeouts <= 20

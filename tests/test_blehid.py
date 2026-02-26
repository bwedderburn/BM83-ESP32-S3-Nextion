import os
import tempfile
import time
from blehid.ble import BleHid, _read_ble_counter, _write_ble_counter


class DummyBLE:
    connected = False
    advertising = False
    name = ""

    def start_advertising(self, adv):
        self.advertising = True

    def stop_advertising(self):
        self.advertising = False

    def erase_bonding(self):
        pass


def test_blehid_advertising_restart():
    blehid = BleHid(enabled=True, name="TestDevice")
    blehid._ble = DummyBLE()
    blehid._adv = object()
    blehid._ready = True

    blehid._start_adv(force=True)
    assert blehid._ble.advertising is True

    blehid._stop_adv()
    assert blehid._ble.advertising is False


def test_erase_bonds_when_ble_not_ready():
    """Test that erase_bonds handles BLE not being ready gracefully."""
    blehid = BleHid(enabled=True, name="TestDevice")
    blehid._ready = False
    blehid._ble = None

    # Should not crash when BLE is not ready
    blehid.erase_bonds()


def test_erase_bonds_when_ble_is_none():
    """Test that erase_bonds handles _ble being None gracefully."""
    blehid = BleHid(enabled=True, name="TestDevice")
    blehid._ready = True
    blehid._ble = None

    # Should not crash when _ble is None
    blehid.erase_bonds()


def test_ble_name_cycling():
    """Test that BLE name cycles with counter on erase_bonds."""
    from unittest import mock
    # Create a temporary counter file for testing
    import blehid.ble as ble_module
    original_file = ble_module.BLE_COUNTER_FILE

    try:
        # Use a temporary file for testing
        test_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
        test_file.write("5")
        test_file.close()
        ble_module.BLE_COUNTER_FILE = test_file.name

        # Test reading counter
        counter = _read_ble_counter()
        assert counter == 5

        # Test writing counter
        success = _write_ble_counter(6)
        assert success is True
        counter = _read_ble_counter()
        assert counter == 6

        # Test erase_bonds updates name with counter
        blehid = BleHid(enabled=True, name="Test Device")
        blehid._ble = DummyBLE()
        blehid._adv = object()
        blehid._ready = True
        # Set up counter state to use persistent storage
        blehid._counter_persisted = True

        # Initial name should be "Test Device"
        assert blehid.name == "Test Device"
        assert blehid.base_name == "Test Device"

        # After erase_bonds, name should be updated with incremented counter
        with mock.patch("time.sleep"):  # Skip delays in test for speed
            blehid.erase_bonds()
        assert blehid.name == "Test Device07"
        assert blehid._ble.name == "Test Device07"

        # Counter should be incremented (both in file and memory)
        counter = _read_ble_counter()
        assert counter == 7
        assert blehid._memory_counter == 7

    finally:
        # Cleanup
        ble_module.BLE_COUNTER_FILE = original_file
        if os.path.exists(test_file.name):
            os.unlink(test_file.name)


def test_erase_bonds_with_failing_connections():
    """Test that erase_bonds handles connection errors gracefully."""
    from unittest import mock

    class FaultyConnection:
        def disconnect(self):
            raise RuntimeError("Connection error")

    class FaultyBLE:
        connected = False
        advertising = False
        name = ""
        connections = [FaultyConnection(), FaultyConnection()]

        def start_advertising(self, adv):
            self.advertising = True

        def stop_advertising(self):
            self.advertising = False

        def erase_bonding(self):
            pass

    blehid = BleHid(enabled=True, name="TestDevice")
    blehid._ble = FaultyBLE()
    blehid._adv = object()
    blehid._ready = True

    # Should not crash even when disconnections fail
    with mock.patch("time.sleep"):  # Skip delays in test for speed
        blehid.erase_bonds()

    # Should still attempt to restart advertising
    assert blehid._ble.advertising is True


def test_erase_bonds_with_failing_erase_bonding():
    """Test that erase_bonds handles erase_bonding errors gracefully."""
    from unittest import mock

    class FaultyBLE:
        connected = False
        advertising = False
        name = ""
        connections = []

        def start_advertising(self, adv):
            self.advertising = True

        def stop_advertising(self):
            self.advertising = False

        def erase_bonding(self):
            raise RuntimeError("Erase bonding error")

    blehid = BleHid(enabled=True, name="TestDevice")
    blehid._ble = FaultyBLE()
    blehid._adv = object()
    blehid._ready = True

    # Should not crash even when erase_bonding fails
    with mock.patch("time.sleep"):  # Skip delays in test for speed
        blehid.erase_bonds()

    # On erase failure, re-advertise should be deferred via backoff
    assert blehid._ble.advertising is False
    assert blehid._adv_inhibit_until > time.monotonic()

    # BLE name should NOT be updated when erase_bonding fails
    assert blehid.name == "TestDevice"
    assert blehid._ble.name == ""  # Name not updated


def test_erase_bonds_with_advertising_failure():
    """Test that erase_bonds handles advertising restart failures gracefully."""
    from unittest import mock

    class FailingAdvBLE:
        connected = False
        advertising = False
        name = ""
        connections = []
        _adv_call_count = 0

        def start_advertising(self, adv):
            self._adv_call_count += 1
            raise RuntimeError("Nimble out of memory")

        def stop_advertising(self):
            self.advertising = False

        def erase_bonding(self):
            pass

    blehid = BleHid(enabled=True, name="TestDevice")
    blehid._ble = FailingAdvBLE()
    blehid._adv = object()
    blehid._ready = True

    # Should not crash even when advertising restart fails after erase
    with mock.patch("time.monotonic", return_value=100.0):
        with mock.patch("time.sleep"):  # Skip delays in test for speed
            blehid.erase_bonds()

    # Advertising failed, so it should remain False
    assert blehid._ble.advertising is False
    # Inhibit should be set to allow stack to recover
    assert blehid._adv_inhibit_until > 100.0


def test_erase_bonds_with_oserror_advertising_failure():
    """Test that erase_bonds handles OSError (BLE stack issue) gracefully."""
    from unittest import mock

    class OSErrorAdvBLE:
        connected = False
        advertising = False
        name = ""
        connections = []

        def start_advertising(self, adv):
            raise OSError("BLE stack failure")

        def stop_advertising(self):
            self.advertising = False

        def erase_bonding(self):
            pass

    blehid = BleHid(enabled=True, name="TestDevice")
    blehid._ble = OSErrorAdvBLE()
    blehid._adv = object()
    blehid._ready = True

    # Should not crash even when OSError occurs during advertising
    with mock.patch("time.monotonic", return_value=100.0):
        with mock.patch("time.sleep"):  # Skip delays in test for speed
            blehid.erase_bonds()

    # Advertising failed, so it should remain False
    assert blehid._ble.advertising is False
    # Inhibit should be set to allow stack to recover
    assert blehid._adv_inhibit_until > 100.0


def test_erase_bonds_with_both_erase_and_adv_failure():
    """Test that when both erase_bonding AND advertising restart fail,
    max() preserves the longer erase backoff over the fixed readv delay."""
    from unittest import mock

    class BothFailBLE:
        connected = False
        advertising = False
        name = ""
        connections = []

        def start_advertising(self, adv):
            raise RuntimeError("Nimble out of memory")

        def stop_advertising(self):
            self.advertising = False

        def erase_bonding(self):
            raise RuntimeError("Erase bonding error")

    blehid = BleHid(enabled=True, name="TestDevice")
    blehid._ble = BothFailBLE()
    blehid._adv = object()
    blehid._ready = True
    # Set high failure count so erase backoff exceeds the 4s readv delay.
    # backoff = min(8.0, 2.0 + 5*1.0) = 7.0 -> erase inhibit = now + 7.0
    # readv inhibit = now + 4.0
    # max(now+7.0, now+4.0) should be now+7.0
    blehid._erase_failures = 4  # will be incremented to 5 inside erase_bonds

    with mock.patch("time.monotonic", return_value=100.0):
        with mock.patch("time.sleep"):
            blehid.erase_bonds()

    # The erase backoff (7.0s) is longer than readv (4.0s), so it must be preserved
    assert blehid._adv_inhibit_until == 107.0
    assert blehid._ble.advertising is False
    assert blehid._erase_failures == 5


def test_erase_bonds_with_readonly_filesystem():
    """Test that erase_bonds works even when filesystem is read-only."""
    from unittest import mock
    import sys
    ble_module = sys.modules["blehid.ble"]

    # Mock the write function to simulate read-only filesystem
    original_write = ble_module._write_ble_counter

    def mock_write_readonly(count):
        # Simulate read-only filesystem error
        return False

    try:
        ble_module._write_ble_counter = mock_write_readonly

        blehid = BleHid(enabled=True, name="TestDevice")
        blehid._ble = DummyBLE()
        blehid._adv = object()
        blehid._ready = True
        blehid._memory_counter = 5
        blehid._counter_persisted = False

        # Erase bonds should work even with read-only filesystem
        with mock.patch("time.sleep"):  # Skip delays in test for speed
            blehid.erase_bonds()

        # Name should be updated with in-memory counter
        assert blehid.name == "TestDevice06"
        assert blehid._ble.name == "TestDevice06"

        # Memory counter should be incremented
        assert blehid._memory_counter == 6

    finally:
        ble_module._write_ble_counter = original_write


def test_erase_bonds_filesystem_transition():
    """Test counter continues incrementing when filesystem becomes read-only mid-operation."""
    from unittest import mock
    import sys
    ble_module = sys.modules["blehid.ble"]

    original_file = ble_module.BLE_COUNTER_FILE
    original_write = ble_module._write_ble_counter

    write_count = [0]  # Use list to allow modification in nested function

    def mock_write_with_transition(count):
        write_count[0] += 1
        # First write succeeds, subsequent writes fail (simulate filesystem becoming read-only)
        if write_count[0] == 1:
            return original_write(count)
        return False

    try:
        # Create temporary file for testing
        test_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
        test_file.write("10")
        test_file.close()
        ble_module.BLE_COUNTER_FILE = test_file.name
        ble_module._write_ble_counter = mock_write_with_transition

        blehid = BleHid(enabled=True, name="TestDevice")
        blehid._ble = DummyBLE()
        blehid._adv = object()
        blehid._ready = True
        blehid._counter_persisted = True  # Start with writable filesystem

        with mock.patch("time.sleep"):  # Skip delays in test for speed
            # First erase: filesystem is writable
            blehid.erase_bonds()
            assert blehid.name == "TestDevice11"
            assert blehid._memory_counter == 11
            assert blehid._counter_persisted is True

            # Second erase: filesystem becomes read-only
            blehid.erase_bonds()
            assert blehid.name == "TestDevice12"
            assert blehid._memory_counter == 12
            assert blehid._counter_persisted is False  # Write failed

            # Third erase: filesystem still read-only, counter should continue incrementing
            blehid.erase_bonds()
            assert blehid.name == "TestDevice13"
            assert blehid._memory_counter == 13
            assert blehid._counter_persisted is False

    finally:
        ble_module.BLE_COUNTER_FILE = original_file
        ble_module._write_ble_counter = original_write
        if os.path.exists(test_file.name):
            os.unlink(test_file.name)


def test_erase_bonds_with_stop_adv_crash():
    """Test that erase_bonds handles _stop_adv crash gracefully.

    This tests the defensive handling added to protect against hard crashes
    that can occur when the Nimble BLE stack is under memory pressure.
    The crash at _stop_adv was causing the E-BIND button to crash the device
    when BM83 was off (issue #37).
    """
    from unittest import mock

    class CrashingStopAdvBLE:
        connected = False
        advertising = True  # Start as advertising
        name = ""
        connections = []
        _stop_called = False
        _start_called = False
        _erase_called = False

        def start_advertising(self, adv):
            self._start_called = True
            self.advertising = True

        def stop_advertising(self):
            self._stop_called = True
            # Simulate Nimble stack crash during stop_advertising
            raise OSError("Nimble out of memory")

        def erase_bonding(self):
            self._erase_called = True

    blehid = BleHid(enabled=True, name="TestDevice")
    blehid._ble = CrashingStopAdvBLE()
    blehid._adv = object()
    blehid._ready = True

    # Should not crash even when _stop_adv crashes
    with mock.patch("time.monotonic", return_value=100.0):
        with mock.patch("time.sleep"):  # Skip delays in test
            blehid.erase_bonds()

    # Verify stop_advertising was called (even though it crashed)
    assert blehid._ble._stop_called is True

    # Verify that despite the crash in _stop_adv, the function continued:
    # - erase_bonding() was called
    assert blehid._ble._erase_called is True

    # - start_advertising was attempted at the end
    assert blehid._ble._start_called is True

    # - BLE name was updated (since erase_bonding succeeded)
    assert "01" in blehid.name  # Counter incremented from 0 to 1

    # - Advertising was restarted successfully
    assert blehid._ble.advertising is True


def test_erase_bonds_with_adv_already_stopped():
    """Test that erase_bonds honors _erase_adv_stopped and uses stabilization delay correctly.

    This tests the path where advertising has already been stopped by the tick loop
    (via the two-phase erase flow), and erase_bonds should not re-stop advertising
    at the beginning but should honor the settle interval relative to _last_adv_stop_at.
    """
    from unittest import mock
    from blehid.ble import BLE_STACK_STABILIZATION_DELAY

    blehid = BleHid(enabled=True, name="TestDevice")
    blehid._ble = DummyBLE()
    blehid._adv = object()
    blehid._ready = True
    blehid._ble.advertising = False
    blehid._erase_adv_stopped = True

    # Test case 1: Last stop was BLE_STACK_STABILIZATION_DELAY - 0.01s ago
    # (i.e., 0.01s of stabilization time still remaining). Should sleep for remaining time.
    blehid._last_adv_stop_at = 100.0 - (BLE_STACK_STABILIZATION_DELAY - 0.01)  # 0.01s remaining

    sleep_calls = []
    original_stop_adv = BleHid._stop_adv

    def track_stop_adv_calls(_self):
        """Track if _stop_adv is called in the initial branch (not from _start_adv)."""
        nonlocal initial_stop_adv_called
        initial_stop_adv_called = True
        original_stop_adv(_self)

    initial_stop_adv_called = False

    with mock.patch("time.monotonic", return_value=100.0):
        with mock.patch("time.sleep", side_effect=lambda d: sleep_calls.append(d)):
            # Patch _stop_adv to track calls, but only check if the initial branch uses it
            with mock.patch.object(BleHid, "_stop_adv", autospec=True, side_effect=track_stop_adv_calls):
                # Temporarily patch _start_adv to prevent it from calling _stop_adv
                # so we can isolate the initial branch behavior
                with mock.patch.object(BleHid, "_start_adv", autospec=True):
                    blehid.erase_bonds()

    # The initial erase_bonds branch taken when _erase_adv_stopped is True
    # should NOT call _stop_adv, since advertising is already considered stopped
    assert initial_stop_adv_called is False

    # Should sleep for the remaining stabilization time (approximately)
    assert len(sleep_calls) >= 1
    # First sleep should be close to the remaining stabilization delay
    assert 0.0 < sleep_calls[0] <= BLE_STACK_STABILIZATION_DELAY

    # Test case 2: Last stop was long enough ago (>= stabilization delay)
    # Should not sleep for initial stabilization but proceed directly
    blehid2 = BleHid(enabled=True, name="TestDevice2")
    blehid2._ble = DummyBLE()
    blehid2._adv = object()
    blehid2._ready = True
    blehid2._ble.advertising = False
    blehid2._erase_adv_stopped = True
    blehid2._last_adv_stop_at = 100.0 - (BLE_STACK_STABILIZATION_DELAY + 0.1)  # Well past delay

    sleep_calls2 = []
    initial_stop_adv_called2 = False
    original_stop_adv2 = BleHid._stop_adv

    def track_stop_adv_calls2(_self):
        nonlocal initial_stop_adv_called2
        initial_stop_adv_called2 = True
        original_stop_adv2(_self)

    with mock.patch("time.monotonic", return_value=100.0):
        with mock.patch("time.sleep", side_effect=lambda d: sleep_calls2.append(d)):
            with mock.patch.object(BleHid, "_stop_adv", autospec=True, side_effect=track_stop_adv_calls2):
                with mock.patch.object(BleHid, "_start_adv", autospec=True):
                    blehid2.erase_bonds()

    # The initial branch should NOT have called _stop_adv
    assert initial_stop_adv_called2 is False

    # First sleep should be for post-disconnect, not initial stabilization
    # (since we're already past the stabilization window)

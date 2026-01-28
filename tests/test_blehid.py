import os
import tempfile
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
        _write_ble_counter(6)
        counter = _read_ble_counter()
        assert counter == 6

        # Test erase_bonds updates name with counter
        blehid = BleHid(enabled=True, name="Test Device")
        blehid._ble = DummyBLE()
        blehid._adv = object()
        blehid._ready = True

        # Initial name should be "Test Device"
        assert blehid.name == "Test Device"
        assert blehid.base_name == "Test Device"

        # After erase_bonds, name should be updated with incremented counter
        blehid.erase_bonds()
        assert blehid.name == "Test Device07"
        assert blehid._ble.name == "Test Device07"

        # Counter should be incremented
        counter = _read_ble_counter()
        assert counter == 7

    finally:
        # Cleanup
        ble_module.BLE_COUNTER_FILE = original_file
        if os.path.exists(test_file.name):
            os.unlink(test_file.name)


def test_erase_bonds_with_failing_connections():
    """Test that erase_bonds handles connection errors gracefully."""
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
    blehid.erase_bonds()

    # Should still attempt to restart advertising
    assert blehid._ble.advertising is True


def test_erase_bonds_with_failing_erase_bonding():
    """Test that erase_bonds handles erase_bonding errors gracefully."""
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
    blehid.erase_bonds()

    # Should still attempt to restart advertising
    assert blehid._ble.advertising is True

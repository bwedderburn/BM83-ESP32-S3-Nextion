import types
from blehid.ble import BleHid


class DummyBLE:
    connected = False
    advertising = False

    def start_advertising(self, adv):
        self.advertising = True

    def stop_advertising(self):
        self.advertising = False

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


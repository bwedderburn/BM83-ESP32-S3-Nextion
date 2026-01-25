import sys
from pathlib import Path

# Add firmware directory to path
FIRMWARE_DIR = Path(__file__).parent.parent / "firmware" / "circuitpython"
sys.path.insert(0, str(FIRMWARE_DIR))

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

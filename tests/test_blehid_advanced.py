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

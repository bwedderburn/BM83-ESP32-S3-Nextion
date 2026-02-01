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


def test_blehid_tick_defers_erase_until_idle():
    ble = BleHid(True, "Mock")
    ble._ready = True
    ble._ble = MockBLE()
    ble._adv = object()
    ble._ble.connected = False
    ble._was_connected = False
    ble._erase_pending = True
    ble._erase_requested_at = 100.0
    ble._erase_debounce_s = 0.1
    ble._erase_min_idle_s = 1.0
    ble._last_conn_change_at = 100.1
    ble._adv_inhibit_until = 200.0

    with mock.patch("time.monotonic", return_value=101.0):
        ble.tick()
    assert ble._erase_pending is True
    assert ble._last_erase_at == 0.0
    assert ble._erase_requested_at == 101.0

    ble._ble.advertising = True
    with mock.patch("time.monotonic", return_value=102.5):
        ble.tick()
    assert ble._erase_pending is True
    assert ble._last_erase_at == 0.0

    ble._ble.advertising = False
    with mock.patch.object(ble, "erase_bonds") as erase_mock:
        with mock.patch("time.monotonic", return_value=103.5):
            ble.tick()
    erase_mock.assert_called_once()
    assert ble._erase_pending is False
    assert ble._last_erase_at == 103.5

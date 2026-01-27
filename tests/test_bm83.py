from bm83.bm83 import Bm83


def test_checksum():
    hi, lo = 0x00, 0x03
    body = bytes([0x01, 0x02, 0x03])
    chk = Bm83._checksum(hi, lo, body)
    total = (hi + lo + sum(body) + chk) & 0xFF
    assert total == 0


def test_avc_payload():
    pdu = 0x30
    params = b"\x01\x02"
    payload = Bm83._avc_payload(pdu, params)
    assert payload.startswith(b"\x30\x00")
    assert payload[4:] == params


class MockUARTForPower:
    def __init__(self):
        self.writes = []
        self.to_read = bytearray()
        self.in_waiting = 0

    def write(self, data):
        self.writes.append(data)

    def read(self, n):
        out = self.to_read[:n]
        self.to_read = self.to_read[n:]
        self.in_waiting = len(self.to_read)
        return out


def test_power_on_nonblocking():
    """Test that power_on_cmd starts state machine without blocking."""
    uart = MockUARTForPower()
    bm = Bm83(uart)
    bm.power_on_cmd()
    # Should have sent power on press command immediately
    assert len(uart.writes) == 1
    assert bm._power_state == "on_press"
    assert not bm.power_on  # Not yet on


def test_power_off_nonblocking():
    """Test that power_off_cmd starts state machine without blocking."""
    uart = MockUARTForPower()
    bm = Bm83(uart)
    bm.power_on = True
    bm.power_off_cmd()
    # Should have sent power off press command immediately
    assert len(uart.writes) == 1
    assert bm._power_state == "off_press"
    assert bm.power_on  # Still on until state machine completes


def test_tick_power_on_sequence():
    """Test tick_power completes power on sequence."""
    import time
    uart = MockUARTForPower()
    bm = Bm83(uart)
    bm.power_on_cmd()
    assert bm._power_state == "on_press"

    # Simulate time passing and tick
    bm._power_next_at = time.monotonic() - 1  # Force immediate
    bm.tick_power()
    assert bm._power_state == "on_release"

    bm._power_next_at = time.monotonic() - 1
    bm.tick_power()
    assert bm._power_state == "on_init"

    bm._power_next_at = time.monotonic() - 1
    bm.tick_power()
    assert bm._power_state is None
    assert bm.power_on is True


def test_tick_power_off_sequence():
    """Test tick_power completes power off sequence."""
    import time
    uart = MockUARTForPower()
    bm = Bm83(uart)
    bm.power_on = True
    bm.connected = True
    bm.power_off_cmd()
    assert bm._power_state == "off_press"

    # Simulate time passing and tick
    bm._power_next_at = time.monotonic() - 1
    bm.tick_power()
    assert bm._power_state == "off_release"

    bm._power_next_at = time.monotonic() - 1
    bm.tick_power()
    assert bm._power_state is None
    assert bm.power_on is False
    assert bm.connected is False


def test_poll_limits_events():
    """Test that poll respects max_events parameter."""
    from tests.test_bm83_uart import MockUART, frame_to_bytes
    uart = MockUART()
    bm = Bm83(uart)
    # Queue up many events
    for _ in range(20):
        pkt = frame_to_bytes(Bm83.EVT_EQ_MODE_IND, bytes([0x05]))
        uart.to_read += pkt
    uart.in_waiting = len(uart.to_read)
    # Default max_events is 8
    events = bm.poll()
    assert len(events) == 8


def test_poll_buffer_overflow_protection():
    """Test that buffer overflow is handled gracefully."""
    uart = MockUARTForPower()
    bm = Bm83(uart)
    # Manually overfill buffer
    bm._rx = bytearray(b'\x00' * 5000)
    uart.to_read = bytearray(b'\x00' * 100)
    uart.in_waiting = 100
    # Should not crash
    events = bm.poll()
    # Buffer should be trimmed
    assert len(bm._rx) <= bm._rx_max

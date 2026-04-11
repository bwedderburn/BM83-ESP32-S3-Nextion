import time
from bm83.bm83 import Bm83
from tests.test_bm83_uart import MockUART, frame_to_bytes


def test_checksum():
    hi, lo = 0x00, 0x03
    body = bytes([0x01, 0x02, 0x03])
    chk = Bm83._checksum(hi, lo, body)
    total = (hi + lo + sum(body) + chk) & 0xFF
    assert total == 0


def test_checksum_range_matches_checksum():
    """_checksum_range over buf[start:end] must equal _checksum for the same bytes."""
    hi, lo = 0x00, 0x03
    body = bytearray([0x01, 0x02, 0x03])
    assert Bm83._checksum_range(hi, lo, body, 0, len(body)) == Bm83._checksum(hi, lo, body)
    # With an offset into a larger buffer
    buf = bytearray([0xFF, 0x01, 0x02, 0x03, 0xFF])
    assert Bm83._checksum_range(hi, lo, buf, 1, 4) == Bm83._checksum(hi, lo, buf[1:4])


def test_avc_payload():
    pdu = 0x30
    params = b"\x01\x02"
    payload = Bm83._avc_payload(pdu, params)
    assert payload.startswith(b"\x30\x00")
    assert payload[4:] == params


def test_power_on_nonblocking():
    """Test that power_on_cmd starts state machine without blocking."""
    uart = MockUART()
    bm = Bm83(uart)
    bm.power_on_cmd()
    # Should have sent power on press command immediately
    assert len(uart.writes) == 1
    assert bm._power_state == "on_press"
    assert not bm.power_on  # Not yet on


def test_power_off_nonblocking():
    """Test that power_off_cmd starts state machine without blocking."""
    uart = MockUART()
    bm = Bm83(uart)
    bm.power_on = True
    bm.power_off_cmd()
    # Should have sent power off press command immediately
    assert len(uart.writes) == 1
    assert bm._power_state == "off_press"
    assert bm.power_on  # Still on until state machine completes


def test_tick_power_on_sequence():
    """Test tick_power completes power on sequence with correct command timing."""
    uart = MockUART()
    bm = Bm83(uart)
    bm.power_on_cmd()
    assert bm._power_state == "on_press"
    assert len(uart.writes) == 1  # Press command sent
    # Verify press command contains MMI_POWER_ON_PRESS (0x51)
    assert Bm83.MMI_POWER_ON_PRESS in uart.writes[0]

    # Simulate 0.2s elapsed, tick should send release and transition to on_init
    bm._power_next_at = time.monotonic() - 1  # Force immediate
    bm.tick_power()
    assert bm._power_state == "on_init"
    assert len(uart.writes) == 2  # Release command sent
    # Verify release command contains MMI_POWER_ON_RELEASE (0x52)
    assert Bm83.MMI_POWER_ON_RELEASE in uart.writes[1]

    # Simulate 0.5s elapsed, tick should call init_link
    bm._power_next_at = time.monotonic() - 1
    bm.tick_power()
    assert bm._power_state is None
    assert bm.power_on is True
    assert len(uart.writes) >= 4  # init_link sends multiple commands
    # Verify init_link commands include OP_READ_BD_ADDR (0x0F)
    init_link_cmds = uart.writes[2:]
    assert any(Bm83.OP_READ_BD_ADDR in cmd for cmd in init_link_cmds)


def test_tick_power_off_sequence():
    """Test tick_power completes power off sequence with correct command timing."""
    uart = MockUART()
    bm = Bm83(uart)
    bm.power_on = True
    bm.connected = True
    bm.power_off_cmd()
    assert bm._power_state == "off_press"
    assert len(uart.writes) == 1  # Press command sent
    # Verify press command contains MMI_POWER_OFF_PRESS (0x53)
    assert Bm83.MMI_POWER_OFF_PRESS in uart.writes[0]

    # Simulate 1.5s elapsed, tick should send release and complete
    bm._power_next_at = time.monotonic() - 1
    bm.tick_power()
    assert bm._power_state is None
    assert bm.power_on is False
    assert bm.connected is False
    assert len(uart.writes) == 2  # Release command sent
    # Verify release command contains MMI_POWER_OFF_RELEASE (0x54)
    assert Bm83.MMI_POWER_OFF_RELEASE in uart.writes[1]


def test_rapid_power_toggle_ignored():
    """Test that rapid power toggles during state machine are ignored."""
    uart = MockUART()
    bm = Bm83(uart)

    # Start power on
    bm.power_on_cmd()
    assert bm._power_state == "on_press"
    initial_writes = len(uart.writes)

    # Try to call power_on again - should be ignored
    bm.power_on_cmd()
    assert bm._power_state == "on_press"  # State unchanged
    assert len(uart.writes) == initial_writes  # No new commands

    # Try to call power_off - should also be ignored while on sequence active
    bm.power_off_cmd()
    assert bm._power_state == "on_press"  # State unchanged
    assert len(uart.writes) == initial_writes  # No new commands


def test_poll_limits_events():
    """Test that poll respects max_events parameter."""
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
    """Test that buffer overflow clears buffer to prevent corruption."""
    uart = MockUART()
    bm = Bm83(uart)
    # Manually overfill buffer
    bm._rx = bytearray(b'\x00' * 5000)
    uart.to_read = bytearray(b'\x00' * 100)
    uart.in_waiting = 100
    # Should not crash
    bm.poll()
    # Buffer should be cleared on overflow
    assert len(bm._rx) == 0


def test_eq_throttle():
    """Test that rapid EQ button presses are throttled."""
    uart = MockUART()
    bm = Bm83(uart)
    # bm.eq_index starts at 0

    # First EQ command should go through
    # eq_index: 0 -> 1, returns EQ_SEQ[1] (SOFT)
    mode1 = bm.next_eq()
    assert bm.eq_index == 1
    assert mode1 == Bm83.EQ_SEQ[1]
    assert len(uart.writes) == 1

    # Immediate second call should be throttled (returns current mode, no index change)
    # eq_index stays at 1, returns EQ_SEQ[1] (SOFT)
    mode2 = bm.next_eq()
    assert bm.eq_index == 1  # Not incremented
    assert mode2 == Bm83.EQ_SEQ[1]  # Returns current mode
    assert len(uart.writes) == 1  # No new command sent

    # Simulate time passing beyond throttle window
    bm._last_eq_cmd_at = time.monotonic() - 1.0  # Force past throttle
    # eq_index: 1 -> 2, returns EQ_SEQ[2] (BASS)
    mode3 = bm.next_eq()
    assert bm.eq_index == 2
    assert mode3 == Bm83.EQ_SEQ[2]
    assert len(uart.writes) == 2  # New command sent


def test_track_changed_reregister_throttle():
    """Test that TrackChanged re-registration is throttled to prevent loops."""
    uart = MockUART()
    bm = Bm83(uart)

    # First re-registration should go through
    result1 = bm.avrcp_reregister_track_changed()
    assert result1 is True
    assert len(uart.writes) == 1

    # Immediate second call should be throttled
    result2 = bm.avrcp_reregister_track_changed()
    assert result2 is False
    assert len(uart.writes) == 1  # No new command

    # Simulate time passing beyond throttle window (2s)
    bm._last_track_changed_reg_at = time.monotonic() - 3.0
    result3 = bm.avrcp_reregister_track_changed()
    assert result3 is True
    assert len(uart.writes) == 2  # New command sent


def test_schedule_attrs_force_bypasses_throttle():
    uart = MockUART()
    bm = Bm83(uart)

    bm._last_attrs_req_at = time.monotonic()
    assert bm.schedule_attrs(0.2) is False
    assert bm._next_attrs_at == 0.0

    assert bm.schedule_attrs(0.2, force=True) is True
    assert bm._next_attrs_at > 0.0


def test_tick_avrcp_attrs_drains_pending_attrs_only_when_connected():
    uart = MockUART()
    bm = Bm83(uart)
    bm._next_attrs_at = time.monotonic() - 0.1

    assert bm.tick_avrcp_attrs() is False
    assert uart.writes == []

    bm.connected = True
    assert bm.tick_avrcp_attrs() is True
    assert len(uart.writes) == 1
    assert uart.writes[0][3] == Bm83.OP_AVRCP_VENDOR_DEP_CMD
    assert bm._next_attrs_at == 0.0

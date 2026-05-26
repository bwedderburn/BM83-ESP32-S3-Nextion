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
    """Test that buffer overflow trims to tail to prevent corruption."""
    uart = MockUART()
    bm = Bm83(uart)
    # Manually overfill buffer
    bm._rx = bytearray(b'\x00' * 5000)
    uart.to_read = bytearray(b'\x00' * 100)
    uart.in_waiting = 100
    # Should not crash
    bm.poll()
    # After overflow trim (to 256 bytes) + parser clearing no-SOF data,
    # the buffer ends up empty.  The key invariant is that no exception
    # occurred and the buffer length is bounded.
    assert len(bm._rx) <= 256


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


def test_tick_avrcp_attrs_uses_supplied_now_without_monotonic(monkeypatch):
    uart = MockUART()
    bm = Bm83(uart)
    bm.connected = True
    now = time.monotonic()
    bm._next_attrs_at = now - 0.1

    def fail_monotonic():
        raise AssertionError("tick_avrcp_attrs should reuse the supplied timestamp")

    monkeypatch.setattr("bm83.bm83.time.monotonic", fail_monotonic)

    assert bm.tick_avrcp_attrs(now) is True
    assert len(uart.writes) == 1
    assert bm._next_attrs_at == 0.0


def test_connection_watchdog_no_trip_before_timeout():
    """check_connection_watchdog does not trip before _btm_silence_timeout_s."""
    bm = Bm83(None)
    bm.connected = True
    now = time.monotonic()
    bm._last_connected_seen = now
    # Well within the timeout window
    assert bm.check_connection_watchdog(now + 1.0) is None
    assert bm.connected is True


def test_connection_watchdog_trips_after_timeout():
    """check_connection_watchdog flips connected=False after _btm_silence_timeout_s."""
    bm = Bm83(None)
    bm.connected = True
    now = time.monotonic()
    bm._last_connected_seen = now
    result = bm.check_connection_watchdog(now + bm._btm_silence_timeout_s + 1.0)
    assert result == "DISCONNECTED"
    assert bm.connected is False


def test_connection_watchdog_noop_when_disconnected():
    """check_connection_watchdog is a no-op when already disconnected."""
    bm = Bm83(None)
    bm.connected = False
    assert bm.check_connection_watchdog() is None


def test_tick_heartbeat_throttles_until_next_deadline(capsys, monkeypatch):
    bm = Bm83(None)
    monkeypatch.setattr("bm83.bm83.gc.mem_free", lambda: 1234, raising=False)
    now = time.monotonic()
    bm._hb_next_at = now + 5.0
    bm._hb_max_gap_window = 0.75
    bm.tick_heartbeat(now)
    assert capsys.readouterr().out == ""
    assert bm._hb_max_gap_window == 0.75


def test_tick_heartbeat_degraded_uses_instantaneous_gap(capsys, monkeypatch):
    bm = Bm83(None)
    # DEGRADED is only printed when self.connected is True. When not
    # connected, idle silence is normal and is suppressed (or demoted
    # to dprint, which is gated by DEBUG). See P0 #3 in
    # docs/code-review-2026-05-26.md.
    bm.connected = True
    monkeypatch.setattr("bm83.bm83.gc.mem_free", lambda: 1234, raising=False)
    now = time.monotonic()
    silence_margin_s = 1.0
    bm._hb_next_at = now
    bm._last_rx_byte_at = now - 0.05
    bm._hb_max_gap_window = bm._hb_silence_warn_s + silence_margin_s
    bm.tick_heartbeat(now)
    out = capsys.readouterr().out
    assert "DEGRADED" in out
    assert "SILENT" not in out
    assert bm._hb_max_gap_window == 0.0


def test_tick_heartbeat_degraded_suppressed_when_not_connected(capsys, monkeypatch):
    """When not connected, DEGRADED must NOT be printed.

    The BM83 legitimately stays silent for many seconds between boot
    and the first BTM_Status, or while BT is off. The old behaviour
    printed DEGRADED in those cases, swamping the log with noise that
    didn't indicate a real degradation.
    """
    bm = Bm83(None)
    assert bm.connected is False
    monkeypatch.setattr("bm83.bm83.gc.mem_free", lambda: 1234, raising=False)
    now = time.monotonic()
    bm._hb_next_at = now
    bm._last_rx_byte_at = now - 0.05
    bm._hb_max_gap_window = bm._hb_silence_warn_s + 1.0
    bm.tick_heartbeat(now)
    out = capsys.readouterr().out
    assert "DEGRADED" not in out
    assert "SILENT" not in out


def test_tick_heartbeat_window_max_resets_each_period(capsys, monkeypatch):
    bm = Bm83(None)
    bm.connected = True  # DEGRADED is gated on connected; see test above.
    monkeypatch.setattr("bm83.bm83.gc.mem_free", lambda: 1234, raising=False)
    bm._hb_period_s = 1.0
    now = time.monotonic()

    bm._hb_next_at = now
    bm._last_rx_byte_at = now - 0.01
    bm._hb_max_gap_window = bm._hb_silence_warn_s - 0.2
    bm.tick_heartbeat(now)
    first = capsys.readouterr().out
    assert "DEGRADED" in first
    assert bm._hb_max_gap_window == 0.0

    next_now = now + bm._hb_period_s
    bm._last_rx_byte_at = next_now - 0.01
    bm.tick_heartbeat(next_now)
    second = capsys.readouterr().out
    assert "alive" in second
    assert "DEGRADED" not in second


# --- play_pause AUX guard -------------------------------------------------

def test_play_pause_suppressed_when_aux_source():
    """play_pause must not write OP_MUSIC_CONTROL when audio_source is AUX.

    Sending the AVRCP transport MMI while the BM83 is routing Line-In
    nudges the chip's source state machine toward A2DP and interrupts
    AUX audio. See main.py:bm83 commit message for the full rationale.
    """
    uart = MockUART()
    bm = Bm83(uart)
    bm.audio_source = bm.AUDIO_SRC_AUX
    bm.play_pause()
    assert uart.writes == [], "play_pause must be a no-op while AUX is active"


def test_play_pause_sends_when_a2dp_source():
    """play_pause sends OP_MUSIC_CONTROL when audio_source is A2DP."""
    uart = MockUART()
    bm = Bm83(uart)
    bm.audio_source = bm.AUDIO_SRC_A2DP
    bm.play_pause()
    assert len(uart.writes) == 1
    # Frame: 0xAA <hi> <lo> OP_MUSIC_CONTROL <db> MC_PLAY_PAUSE <chk>
    pkt = uart.writes[0]
    assert pkt[0] == 0xAA
    assert pkt[3] == Bm83.OP_MUSIC_CONTROL
    assert pkt[5] == Bm83.MC_PLAY_PAUSE


def test_play_pause_sends_when_source_unknown():
    """play_pause sends when audio_source is None (boot, before first source event).

    The AUX guard is deliberately narrow: a None source means we haven't
    seen a 0x80/0x81/0x82 yet, in which case the user's Play press should
    still be honored as a "kick A2DP / resume" intent.
    """
    uart = MockUART()
    bm = Bm83(uart)
    assert bm.audio_source is None  # default
    bm.play_pause()
    assert len(uart.writes) == 1


# --- audio_source reset on disconnect -------------------------------------

def test_note_btm_state_clears_audio_source_on_disconnect_hold():
    """note_btm_state hold-timeout disconnect path resets audio_source to None.

    Without this, audio_source stays pinned at 0x82 from the last A2DP
    session, and should_show_aux() never returns True even when AUX is
    the active physical source after the BT link drops.
    """
    bm = Bm83(None)
    bm.connected = True
    bm.audio_source = bm.AUDIO_SRC_A2DP
    # Pretend the BM83 hasn't been seen for longer than the disconnect hold.
    bm._last_connected_seen = time.monotonic() - (bm._disconnect_hold_s + 1.0)
    # Pass a state that's NOT in CONNECTED_STATES and NOT in AUDIO_SRC_STATES
    # so the disconnect branch fires. 0x0F (SPP/iAP disconnected) qualifies.
    result = bm.note_btm_state(0x0F)
    assert result == "DISCONNECTED"
    assert bm.connected is False
    assert bm.audio_source is None


def test_check_connection_watchdog_clears_audio_source_on_timeout():
    """check_connection_watchdog silence-timeout path resets audio_source."""
    bm = Bm83(None)
    bm.connected = True
    bm.audio_source = bm.AUDIO_SRC_A2DP
    now = time.monotonic()
    bm._last_connected_seen = now
    result = bm.check_connection_watchdog(now + bm._btm_silence_timeout_s + 1.0)
    assert result == "DISCONNECTED"
    assert bm.connected is False
    assert bm.audio_source is None
def test_status_changed_reregister_throttle():
    """avrcp_reregister_status_changed is throttled to ~0.5 s."""
    uart = MockUART()
    bm = Bm83(uart)

    # First call goes through.
    assert bm.avrcp_reregister_status_changed() is True
    assert len(uart.writes) == 1

    # Immediate second call is throttled.
    assert bm.avrcp_reregister_status_changed() is False
    assert len(uart.writes) == 1

    # After the throttle window, allowed again.
    bm._last_status_changed_reg_at = time.monotonic() - (bm._status_reg_throttle_s + 0.1)
    assert bm.avrcp_reregister_status_changed() is True
    assert len(uart.writes) == 2


def test_position_changed_reregister_throttle():
    """avrcp_reregister_position_changed is throttled to ~0.5 s."""
    uart = MockUART()
    bm = Bm83(uart)

    assert bm.avrcp_reregister_position_changed() is True
    assert len(uart.writes) == 1

    assert bm.avrcp_reregister_position_changed() is False
    assert len(uart.writes) == 1

    bm._last_pos_changed_reg_at = time.monotonic() - (bm._pos_reg_throttle_s + 0.1)
    assert bm.avrcp_reregister_position_changed() is True
    assert len(uart.writes) == 2


def test_poll_does_not_refresh_watchdog_on_btm_status():
    """poll() must NOT stamp _last_connected_seen on BTM_Status frames.

    Otherwise note_btm_state's _disconnect_hold_s check is always-false
    and a real disconnect-state BTM_Status can never demote self.connected.
    """
    uart = MockUART()
    bm = Bm83(uart)
    bm.connected = True
    # Anchor the watchdog timestamp far in the past so we can detect a refresh.
    stale = time.monotonic() - 100.0
    bm._last_connected_seen = stale

    # Inject a BTM_Status frame (op=0x01) with a non-connected state byte.
    btm_frame = bm.frame(Bm83.EVT_BTM_STATUS, bytes([0x00]))
    uart.to_read = bytearray(btm_frame)
    uart.in_waiting = len(uart.to_read)
    events = bm.poll()
    assert any(op == Bm83.EVT_BTM_STATUS for op, _ in events)
    # Must remain stale — BTM_Status is excluded from the refresh.
    assert bm._last_connected_seen == stale


def test_poll_refreshes_watchdog_on_non_btm_frame():
    """poll() refreshes _last_connected_seen on non-BTM inbound frames."""
    uart = MockUART()
    bm = Bm83(uart)
    bm.connected = True
    stale = time.monotonic() - 100.0
    bm._last_connected_seen = stale

    # AVRCP vendor response frame — a non-BTM op.
    avrcp_frame = bm.frame(Bm83.EVT_AVC_VENDOR_RSP, bytes([0x00, 0x00]))
    uart.to_read = bytearray(avrcp_frame)
    uart.in_waiting = len(uart.to_read)
    events = bm.poll()
    assert any(op == Bm83.EVT_AVC_VENDOR_RSP for op, _ in events)
    # Must have been refreshed.
    assert bm._last_connected_seen > stale


def test_btm_silence_timeout_default_is_90s():
    """The watchdog default tolerates idle pauses (>=90s)."""
    bm = Bm83(None)
    assert bm._btm_silence_timeout_s >= 90.0

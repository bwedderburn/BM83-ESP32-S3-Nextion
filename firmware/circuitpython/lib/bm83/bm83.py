import time
from utils.common import dprint
from utils import common as _utils_common
from utils.compat import const

# endregion
# endregion
_AVRCP_ATTR_IDS = (1, 2, 3, 6, 4, 5, 7)
_AVRCP_ATTR_PAYLOAD = bytes([len(_AVRCP_ATTR_IDS)]) + b"".join(
    int(a).to_bytes(4, "big") for a in _AVRCP_ATTR_IDS
)
_AVRCP_ATTR_NAMES = {
    1: "title",
    2: "artist",
    3: "album",
    4: "track_num",
    5: "total_tracks",
    6: "genre",
}
# Class: Bm83 - Represents the Bm83 class.
class Bm83:
# region Bm83
# Bm83 class encapsulates functionality related to bm83. #
    __slots__ = (
        "uart",
        "_rx",
        "_rx_max",
        "power_on",
        "eq_index",
        "connected",
        "_last_connected_seen",
        "_disconnect_hold_s",
        "_next_playstatus_at",
        "_playstatus_period_s",
        "_next_attrs_at",
        "_attrs_throttle_s",
        "_last_attrs_req_at",
        "_gea_frag",
        "_gea_expect_len",
        "_gea_frag_at",
        "_gea_frag_timeout_s",
        "_power_state",
        "_power_next_at",
        "_last_eq_cmd_at",
        "_eq_throttle_s",
        "_last_track_changed_reg_at",
        "_track_changed_reg_throttle_s",
        "_btm_silence_timeout_s",
        "audio_source",
    )
    # Audio-source values reported by BTM_Status (MSPKv2 / Audio Transceiver
    # BM83 variants). Datasheet "AudioUARTCommandSet v2.09" section 7.2
    # BTM_Status state table, page 169.
    AUDIO_SRC_NONE = const(0x80)   # Current audio source is not Aux in or A2DP
    AUDIO_SRC_AUX  = const(0x81)   # Current audio source is Aux in
    AUDIO_SRC_A2DP = const(0x82)   # Current audio source is A2DP
    AUDIO_SRC_STATES = (AUDIO_SRC_NONE, AUDIO_SRC_AUX, AUDIO_SRC_A2DP)
    OP_MMI_ACTION = const(0x02)
    OP_EVENT_FILTER = const(0x03)
    OP_MUSIC_CONTROL = const(0x04)
    OP_AVC_VENDOR_CMD = const(0x0B)
    OP_READ_BD_ADDR = const(0x0F)
    OP_BTM_UTILITY_FUNC = const(0x13)
    OP_EVENT_ACK = const(0x14)
    OP_EQ_MODE_SETTING = const(0x1C)
    OP_AVRCP_VENDOR_DEP_CMD = const(0x4A)

# endregion
    EVT_BTM_STATUS = const(0x01)
    EVT_EQ_MODE_IND = const(0x10)
    EVT_AVC_VENDOR_RSP = const(0x1A)
    EVT_AVRCP_VENDOR_DEP_RSP = const(0x5D)

# endregion
    MMI_POWER_ON_PRESS = const(0x51)
    MMI_POWER_ON_RELEASE = const(0x52)
    MMI_POWER_OFF_PRESS = const(0x53)
    MMI_POWER_OFF_RELEASE = const(0x54)
    MMI_ENTER_PAIRING = const(0x5D)
    # Line-In input gain controls (AudioUARTCommandSet v2.09, table on
    # page 136, Support version V2.07). These target the *analog/input*
    # Line-In gain stage directly, unlike Set_Overall_Gain 0x23 with the
    # Line_In mask bit which only moves a digital mixer level and leaves
    # the actual AUX loudness unchanged on this firmware variant.
    MMI_LINE_IN_GAIN_UP = const(0x82)
    MMI_LINE_IN_GAIN_DOWN = const(0x83)

# endregion
    MC_PLAY_PAUSE = const(0x07)
    MC_NEXT = const(0x09)
    MC_PREV = const(0x0A)

# endregion
    EQ_SEQ = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11)
    EQ_L = {
        0: "OFF", 1: "SOFT", 2: "BASS", 3: "TREBLE", 4: "CLASSICAL",
        5: "ROCK", 6: "JAZZ", 7: "POP", 8: "DANCE", 9: "RNB", 11: "USER"
    }
    EQ_LABELS = EQ_L  # Alias for test compatibility
    CONNECTED_STATES = (0x06, 0x0B, 0x82, 0x64, 0x65, 0x66)

# endregion
    # Loop through items
# Function: __init__ - Defines the behavior for `__init__`.
    def __init__(self, uart=None):
# region __init__
    # __init__ handles   init   logic. #
        self.uart = uart
        self._rx = bytearray()
        self._rx_max = 4096  # Max buffer size to prevent memory exhaustion
        self.power_on = False
        self.eq_index = 0
        self.connected = False
        self._last_connected_seen = 0.0
        self._disconnect_hold_s = 2.0
        self._next_playstatus_at = 0.0
        self._playstatus_period_s = 1.0
        self._next_attrs_at = 0.0
        self._attrs_throttle_s = 1.5
        self._last_attrs_req_at = 0.0
        self._gea_frag = bytearray()
        self._gea_expect_len = None
        self._gea_frag_at = 0.0
        # Drop any fragment we haven't added to within this many seconds — a
        # dropped final packet from the BM83 would otherwise leave state dangling.
        self._gea_frag_timeout_s = 5.0
        # Non-blocking power state machine
        self._power_state = None  # None, "on_press", "on_init", "off_press"
        self._power_next_at = 0.0
        # EQ command throttle to prevent rapid-fire from fast button presses
        self._last_eq_cmd_at = 0.0
        self._eq_throttle_s = 0.25  # Min time between EQ commands
        # TrackChanged re-registration throttle to prevent feedback loops
        self._last_track_changed_reg_at = 0.0
        self._track_changed_reg_throttle_s = 2.0  # Min time between re-registrations
        # If no BTM_Status (or other connection-refreshing event) arrives for this
        # many seconds while we think we're connected, assume the radio went silent
        # and flip to disconnected. The AVRCP-silence heuristic in main.py alone
        # can't clear self.connected, so without this the state sticks forever.
        self._btm_silence_timeout_s = 30.0

        # Current audio source reported by BTM_Status (state 0x80/0x81/0x82).
        # None until the first source event arrives. 0x81 means AUX jack is the
        # active source; UI gates "AUX IN" indicators on this. See AUDIO_SRC_*
        # constants and should_show_aux().
        self.audio_source = None

# endregion
    @staticmethod
    # Loop through items
# Function: _checksum - Defines the behavior for `_checksum`.
    def _checksum(hi, lo, body):
# region _checksum
    # _checksum handles  checksum logic. #
    # Return the result
        return (-((hi + lo + sum(body)) & 0xFF)) & 0xFF
# endregion

# endregion
    @staticmethod
    def _checksum_range(hi, lo, buf, start, end):
        """Compute checksum over buf[start:end] without copying caller buffers."""
        view = buf[start:end]
        return (-((hi + lo + sum(view)) & 0xFF)) & 0xFF

# endregion
    # Loop through items
# Function: _frame - Defines the behavior for `_frame`.
    def _frame(self, op, params=b""):
# region _frame
    # _frame handles  frame logic. #
        body = bytes([op]) + params
        ln = len(body)
        hi, lo = (ln >> 8) & 0xFF, ln & 0xFF
        chk = self._checksum(hi, lo, body)
    # Return the result
        return bytes([0xAA, hi, lo]) + body + bytes([chk])
# endregion

# endregion
    # Public alias for testing
    def frame(self, op, params=b""):
        return self._frame(op, params)

# endregion
    # Loop through items
# Function: _checksum_valid - Validates a checksum
    def _checksum_valid(self, body_with_checksum):
# region _checksum_valid
    # _checksum_valid handles checksum validation logic. #
        if len(body_with_checksum) < 2:
            return False
        body = body_with_checksum[:-1]
        chk = body_with_checksum[-1]
        ln = len(body)
        hi, lo = (ln >> 8) & 0xFF, ln & 0xFF
        expected = self._checksum(hi, lo, body)
        return chk == expected
# endregion

# endregion
    # Loop through items
# Function: send - Defines the behavior for `send`.
    def send(self, op, params=b""):
# region send
    # send handles send logic. #
        pkt = self._frame(op, params)
        # Avoid hex formatting when DEBUG is off (hot path, allocates)
        if _utils_common.DEBUG:
            dprint("[BM83 TX]", " ".join("%02X" % b for b in pkt))
    # Try block to catch exceptions
        try:
            self.uart.write(pkt)
    # Handle exceptions
        except Exception as e:
            print("[BM83] write err:", e)

# endregion
    # Loop through items
# Function: ack_event - Defines the behavior for `ack_event`.
    def ack_event(self, event_op):
# region ack_event
    # ack_event handles ack event logic. #
    # Conditional check
        if event_op == 0x00:
            return
        self.send(self.OP_EVENT_ACK, bytes([event_op & 0xFF]))

# endregion
    # Loop through items
# Function: poll - Defines the behavior for `poll`.
    def poll(self, max_read=768, max_events=8):
# region poll
    # poll handles poll logic. #
        out = []
    # Try block to catch exceptions
        try:
            n = getattr(self.uart, "in_waiting", 0) or 0
            chunk = self.uart.read(min(max_read, n)) if n else None
    # Handle exceptions
        except Exception as e:
            dprint("[BM83] read err:", e)
    # Return the result
            return out
# endregion
    # Conditional check
        if chunk:
            self._rx.extend(chunk)
        # Limit buffer size to prevent memory exhaustion. Keep the tail so an
        # in-progress frame can still resync from its start-of-frame byte.
        if len(self._rx) > self._rx_max:
            keep = 256  # Larger than any plausible single frame
            dprint("[BM83] buffer overflow, trimming head, keeping", keep, "bytes")
            # CircuitPython bytearray doesn't support slice deletion — reassign.
            self._rx = self._rx[-keep:]
    # While loop execution
        while len(out) < max_events:
    # Conditional check
            if len(self._rx) < 4:
                break
            sof = self._rx.find(b"\xAA")
    # Conditional check
            if sof < 0:
                self._rx.clear()
                break
    # Conditional check
            if sof > 0:
                # CircuitPython bytearray doesn't support slice deletion.
                self._rx = self._rx[sof:]
    # Conditional check
            if len(self._rx) < 4:
                break
            hi, lo = self._rx[1], self._rx[2]
            ln = (hi << 8) | lo
            total = 3 + ln + 1
    # Conditional check
            if len(self._rx) < total:
                break
            body = bytes(self._rx[3 : 3 + ln])
            chk = self._rx[3 + ln]
    # Conditional check
            if chk != self._checksum(hi, lo, body):
                # CircuitPython bytearray doesn't support slice deletion.
                self._rx = self._rx[1:]
                continue
            op = body[0]
            params = body[1:]
            # Avoid hex formatting when DEBUG is off (hot path, allocates)
            if _utils_common.DEBUG:
                dprint("[BM83 EVT] op=0x%02X len=%d data=" % (op, len(params)), " ".join("%02X" % b for b in params))
            out.append((op, params))
            # Any successful inbound frame proves the BM83 is alive. Refresh
            # the connection-watchdog timestamp so the silence watchdog only
            # trips on an actually-silent radio (not on steady-state BT
            # playback where BTM_Status doesn't re-emit between transitions).
            if self.connected:
                self._last_connected_seen = time.monotonic()
            # CircuitPython bytearray doesn't support slice deletion.
            self._rx = self._rx[total:]
    # Return the result
        return out
# endregion

# endregion
    # Loop through items
# Function: init_link - Defines the behavior for `init_link`.
    def init_link(self):
# region init_link
    # init_link handles init link logic. #
        self.send(self.OP_READ_BD_ADDR)
        self.send(self.OP_EVENT_FILTER, b"\x00\x00\x00\x00")
        self.send(self.OP_BTM_UTILITY_FUNC, b"\x03\x01")
        print("[BM83] Link initialized")

# endregion
    # Loop through items
# Function: power_on_cmd - Defines the behavior for `power_on_cmd`.
    def power_on_cmd(self):
# region power_on_cmd
    # power_on_cmd handles power on cmd logic (non-blocking state machine). #
        # Ignore if state machine already in progress to prevent inconsistent state
        if self._power_state is not None:
            return
        now = time.monotonic()
        self._power_state = "on_press"
        self._power_next_at = now + 0.2  # Wait 0.2s before sending release
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_POWER_ON_PRESS]))

# endregion
    # Loop through items
# Function: power_off_cmd - Defines the behavior for `power_off_cmd`.
    def power_off_cmd(self):
# region power_off_cmd
    # power_off_cmd handles power off cmd logic (non-blocking state machine). #
        # Ignore if state machine already in progress to prevent inconsistent state
        if self._power_state is not None:
            return
        now = time.monotonic()
        self._power_state = "off_press"
        self._power_next_at = now + 1.5  # Wait 1.5s before sending release
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_POWER_OFF_PRESS]))

# endregion
    # Loop through items
# Function: tick_power - Defines the behavior for `tick_power`.
    def tick_power(self):
# region tick_power
    # tick_power handles non-blocking power state machine. #
        if self._power_state is None:
            return
        now = time.monotonic()
        if now < self._power_next_at:
            return
        if self._power_state == "on_press":
            # 0.2s elapsed since press, now send release
            self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_POWER_ON_RELEASE]))
            self._power_state = "on_init"
            self._power_next_at = now + 0.5  # Wait 0.5s before init_link
        elif self._power_state == "on_init":
            self.init_link()
            self.power_on = True
            self._power_state = None
            print("[POWER] ON (UART)")
        elif self._power_state == "off_press":
            # 1.5s elapsed since press, now send release
            self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_POWER_OFF_RELEASE]))
            self.power_on = False
            self.connected = False
            self._power_state = None
            print("[POWER] OFF (UART)")
# endregion

# endregion
    # Loop through items
# Function: power_toggle - Defines the behavior for `power_toggle`.
    def power_toggle(self):
# region power_toggle
    # power_toggle handles power toggle logic. #
        self.power_off_cmd() if self.power_on else self.power_on_cmd()

# endregion
    # Loop through items
# Function: pair - Defines the behavior for `pair`.
    def pair(self):
# region pair
    # pair handles pair logic. #
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_ENTER_PAIRING]))
        print("[PAIR] Enter pairing")

# endregion
    # Loop through items
# Function: play_pause - Defines the behavior for `play_pause`.
    def play_pause(self):
# region play_pause
    # play_pause handles play pause logic. #
        self.send(self.OP_MUSIC_CONTROL, bytes([0x00, self.MC_PLAY_PAUSE]))
        print("[PLAY/PAUSE] toggled")

# endregion
    # Loop through items
# Function: prev - Defines the behavior for `prev`.
    def prev(self):
# region prev
    # prev handles prev logic. #
        self.send(self.OP_MUSIC_CONTROL, bytes([0x00, self.MC_PREV]))
        print("[PREV] triggered")

# endregion
    # Loop through items
# Function: next - Defines the behavior for `next`.
    def next(self):
# region next
    # next handles next logic. #
        self.send(self.OP_MUSIC_CONTROL, bytes([0x00, self.MC_NEXT]))
        print("[NEXT] triggered")

# endregion
    # Loop through items
# Function: next_eq - Defines the behavior for `next_eq`.
    def next_eq(self):
# region next_eq
    # next_eq handles next eq logic with throttling to prevent UART flood. #
        now = time.monotonic()
        if (now - self._last_eq_cmd_at) < self._eq_throttle_s:
            # Return current mode without sending command (throttled)
            return self.EQ_SEQ[self.eq_index]
        self._last_eq_cmd_at = now
        self.eq_index = (self.eq_index + 1) % len(self.EQ_SEQ)
        mode = self.EQ_SEQ[self.eq_index]
        self.send(self.OP_EQ_MODE_SETTING, bytes([mode, 0x00]))
    # Return the result
        return mode
# endregion

    def volume_up(self):
        """Step Line-In input gain up via MMI 0x82.

        Used only when AUX is the active source (BT-streaming volume is
        routed through BLE HID in main.py). The `Set_Overall_Gain` 0x23
        path with mask=Line_In was tried first but only moved a digital
        mixer level — audible output didn't change on this firmware
        variant, just a cap-chirp at max. MMI 0x82 hits the actual
        Line-In input gain stage instead. Datasheet v2.09 p.136.
        """
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_LINE_IN_GAIN_UP]))
        print("[VOL+] (BM83 Line-In gain up)")

    def volume_down(self):
        """Step Line-In input gain down via MMI 0x83. See volume_up()."""
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_LINE_IN_GAIN_DOWN]))
        print("[VOL-] (BM83 Line-In gain down)")

    def kick_aux_routing(self):
        """Nudge the BM83 audio engine when AUX has just gone active.

        Works around a BM83 jack-detect quirk: on the very first AUX
        plug-in after boot (or sometimes after a soft disconnect), the
        chip's internal detection misses the mating transition and the
        Line-In path stays muted until you unplug and replug. Sending a
        Line-In gain-up MMI right after we observe audio_source flip to
        0x81 re-triggers the routing path inside the BM83 and the audio
        starts passing through without the user needing to replug.

        Side effect: Line-In gain bumps one step louder per fresh plug-in.
        Accepted trade-off; if gain ever pegs at max there's a chirp but
        no audible side effect on loudness.
        """
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_LINE_IN_GAIN_UP]))
        print("[AUX] routing kick sent (MMI Line-In gain up)")

# endregion
    # Loop through items
# Function: note_btm_state - Defines the behavior for `note_btm_state`.
    def note_btm_state(self, state):
# region note_btm_state
    # note_btm_state handles note btm state logic. #
        now = time.monotonic()
        # Audio-source tracking. States 0x80/0x81/0x82 report which audio
        # source the BM83 is currently routing (none / AUX / A2DP). They are
        # orthogonal to link-state codes like 0x06 (A2DP link established),
        # so we record them separately and do NOT use them to drive
        # self.connected. should_show_aux() reads this to gate the AUX UI.
        if state in self.AUDIO_SRC_STATES:
            self.audio_source = state
            return None
    # Conditional check
        if state in self.CONNECTED_STATES:
            self._last_connected_seen = now
    # Conditional check
            if not self.connected:
                self.connected = True
    # Return the result
                return "CONNECTED"
# endregion
    # Return the result
            return None
# endregion
    # Conditional check
        if self.connected and (now - self._last_connected_seen) > self._disconnect_hold_s:
            self.connected = False
    # Return the result
            return "DISCONNECTED"
# endregion
    # Return the result
        return None
# endregion

    def should_show_aux(self):
        """Return True when the UI should show AUX IN indicators.

        Primary signal is the BM83 audio-source state reported by
        BTM_Status (0x80/0x81/0x82). 0x81 = AUX is the active source, so
        show. 0x80 (no source) and 0x82 (A2DP) both mean: do not show AUX.

        Before the first source event arrives (audio_source is None), we
        fall back to the pre-existing link-state heuristic so the UI still
        behaves sanely during the boot-to-first-BTM_Status window.
        """
        if not self.power_on:
            return False
        if self.audio_source == self.AUDIO_SRC_AUX:
            return True
        if self.audio_source in (self.AUDIO_SRC_NONE, self.AUDIO_SRC_A2DP):
            return False
        # Haven't seen a source event yet — fall back to link state.
        return not self.connected

    def check_connection_watchdog(self, now=None):
        """Return "DISCONNECTED" if the BM83 has gone completely silent.

        ``_last_connected_seen`` is refreshed on *any* successful inbound frame
        in ``poll()`` while ``self.connected`` is True — BTM_Status events,
        AVRCP notifications, metadata responses, play-status replies, etc. —
        so this watchdog only trips when the radio emits nothing at all for
        ``_btm_silence_timeout_s`` (e.g., crash, brown-out, UART wedged).
        Steady-state playback that triggers only AVRCP traffic (no BTM state
        transitions) must NOT trip this, otherwise the UI will flap into AUX.
        """
        if not self.connected:
            return None
        if now is None:
            now = time.monotonic()
        if (now - self._last_connected_seen) > self._btm_silence_timeout_s:
            self.connected = False
            return "DISCONNECTED"
        return None

# endregion
    @staticmethod
    # Loop through items
# Function: _avc_payload - Defines the behavior for `_avc_payload`.
    def _avc_payload(pdu, params):
# region _avc_payload
    # _avc_payload handles  avc payload logic. #
    # Return the result
        return bytes([pdu, 0x00]) + len(params).to_bytes(2, "big") + params
# endregion

# endregion
    # Loop through items
# Function: avrcp_get_play_status - Defines the behavior for `avrcp_get_play_status`.
    def avrcp_get_play_status(self, db=0):
# region avrcp_get_play_status
    # avrcp_get_play_status handles avrcp get play status logic. #
        self.send(self.OP_AVC_VENDOR_CMD, bytes([db]) + self._avc_payload(0x30, b""))

# endregion
    # Loop through items
# Function: avrcp_register_notification - Defines the behavior for `avrcp_register_notification`.
    def avrcp_register_notification(self, event_id, interval_s=0, db=0):
# region avrcp_register_notification
    # avrcp_register_notification handles avrcp register notification logic. #
        params = bytes([event_id]) + int(interval_s).to_bytes(4, "big")
        self.send(self.OP_AVC_VENDOR_CMD, bytes([db]) + self._avc_payload(0x31, params))

# endregion
    # Loop through items
# Function: avrcp_reregister_track_changed - Re-register TrackChanged with throttle
    def avrcp_reregister_track_changed(self, db=0):
# region avrcp_reregister_track_changed
    # Throttled re-registration for TrackChanged to prevent feedback loops. #
        now = time.monotonic()
        if (now - self._last_track_changed_reg_at) < self._track_changed_reg_throttle_s:
            return False  # Throttled
        self._last_track_changed_reg_at = now
        self.avrcp_register_notification(0x02, interval_s=0, db=db)
        return True
# endregion

# endregion
    # Loop through items
# Function: avrcp_get_element_attributes - Defines the behavior for `avrcp_get_element_attributes`.
    def avrcp_get_element_attributes(self, db=0):
# region avrcp_get_element_attributes
    # avrcp_get_element_attributes handles avrcp get element attributes logic. #
        self.send(self.OP_AVRCP_VENDOR_DEP_CMD, bytes([db, 0x20]) + _AVRCP_ATTR_PAYLOAD)

# endregion
    def schedule_play_status(self, delay_s=0.05):
        """Request the next AVRCP GetPlayStatus poll after ``delay_s`` seconds.

        Use this from callers (e.g., the main loop) instead of poking
        ``_next_playstatus_at`` directly.
        """
        self._next_playstatus_at = time.monotonic() + delay_s

    # Loop through items
# Function: schedule_attrs - Defines the behavior for `schedule_attrs`.
    def schedule_attrs(self, delay_s=0.35, force=False):
# region schedule_attrs
    # schedule_attrs handles schedule attrs logic. #
        now = time.monotonic()
    # Conditional check
        if (not force) and (now - self._last_attrs_req_at) < self._attrs_throttle_s:
            return False
        t = now + delay_s
    # Conditional check
        if self._next_attrs_at == 0.0 or t < self._next_attrs_at:
            self._next_attrs_at = t
            return True
        return False

# endregion
    # Loop through items
# Function: tick_avrcp - Defines the behavior for `tick_avrcp`.
    def tick_avrcp(self):
# region tick_avrcp
    # tick_avrcp handles tick avrcp logic. #
    # Conditional check
        if not self.connected:
            return
        now = time.monotonic()
    # Conditional check
        if now >= self._next_playstatus_at:
            self.avrcp_get_play_status(0)
            self._next_playstatus_at = now + self._playstatus_period_s
        self.tick_avrcp_attrs(now)

# endregion
    def tick_avrcp_attrs(self, now=None):
        if (not self.connected) or (self._next_attrs_at == 0.0):
            return False
        if now is None:
            now = time.monotonic()
        if now >= self._next_attrs_at:
            self._last_attrs_req_at = now
            self._next_attrs_at = 0.0
            self.avrcp_get_element_attributes(0)
            return True
        return False

# endregion
    @staticmethod
    # Loop through items
# Function: parse_avc_vendor_rsp - Defines the behavior for `parse_avc_vendor_rsp`.
    def parse_avc_vendor_rsp(params):
# region parse_avc_vendor_rsp
    # parse_avc_vendor_rsp handles parse avc vendor rsp logic. #
    # Conditional check
        if len(params) < 1 + 10:
    # Return the result
            return None
# endregion
        db = params[0]
        p = params[1:]
        pdu = p[6]
        pkt_type = p[7]
        plen = int.from_bytes(p[8:10], "big")
    # Conditional check
        if len(p) < 10 + plen:
    # Return the result
            return None
# endregion
    # Return the result
        return db, pdu, pkt_type, p[10 : 10 + plen]
# endregion

# endregion
    # Loop through items
# Function: parse_gea_0x5d - Defines the behavior for `parse_gea_0x5d`.
    def parse_gea_0x5d(self, params):
# region parse_gea_0x5d
    # parse_gea_0x5d handles parse gea 0x5d logic. #
    # Conditional check
        if len(params) < 2:
    # Return the result
            return None
# endregion
        pdu_id = params[0]
        payload = params[2:]
    # Conditional check
        if pdu_id != 0x20 or len(payload) < 5:
    # Return the result
            return None
# endregion
        resp = payload[0]
        is_end = payload[1]
        attr_num = payload[2]
        total_len = int.from_bytes(payload[3:5], "big")
        part = payload[5:]
    # Conditional check
        if total_len <= 0:
            self._gea_frag = bytearray()
            self._gea_expect_len = None
            self._gea_frag_at = 0.0
            dprint("[META] drop empty GEA response")
            return None
        now = time.monotonic()
        # Age out a fragment that was never completed — a dropped final packet
        # would otherwise keep the buffer alive until the next total_len change.
        if (
            self._gea_expect_len is not None
            and self._gea_frag_at > 0.0
            and (now - self._gea_frag_at) > self._gea_frag_timeout_s
        ):
            dprint("[META] drop stale GEA frag age=%.1fs" % (now - self._gea_frag_at))
            self._gea_frag = bytearray()
            self._gea_expect_len = None
            self._gea_frag_at = 0.0
        if self._gea_expect_len is None or self._gea_expect_len != total_len:
            if self._gea_expect_len is not None and len(self._gea_frag):
                dprint("[META] reset fragmented GEA len=%d->%d" % (self._gea_expect_len, total_len))
            self._gea_expect_len = total_len
            self._gea_frag = bytearray()
        self._gea_frag.extend(part)
        self._gea_frag_at = now
        if len(self._gea_frag) > self._gea_expect_len:
            dprint("[META] trim oversized GEA frag %d>%d" % (len(self._gea_frag), self._gea_expect_len))
            self._gea_frag = self._gea_frag[: self._gea_expect_len]
    # Conditional check
        if is_end != 0x01:
    # Return the result
            return None
# endregion
        if len(self._gea_frag) < self._gea_expect_len:
            dprint("[META] drop short final GEA %d<%d" % (len(self._gea_frag), self._gea_expect_len))
            self._gea_frag = bytearray()
            self._gea_expect_len = None
            self._gea_frag_at = 0.0
            return None
        full = bytes(self._gea_frag[: self._gea_expect_len])
        self._gea_frag = bytearray()
        self._gea_expect_len = None
        self._gea_frag_at = 0.0
        attrs = {}
        idx = 0
    # Loop through items
        for _ in range(attr_num):
    # Conditional check
            if idx + 8 > len(full):
                dprint("[META] truncated GEA header at", idx)
                break
            aid = int.from_bytes(full[idx : idx + 4], "big")
            vlen = int.from_bytes(full[idx + 6 : idx + 8], "big")
            if idx + 8 + vlen > len(full):
                dprint("[META] truncated GEA attr id=%d len=%d" % (aid, vlen))
                break
            val = full[idx + 8 : idx + 8 + vlen]
            idx += 8 + vlen
    # Try block to catch exceptions
            try:
                s = val.decode("utf-8", "replace").strip()
    # Handle exceptions
            except UnicodeError:
                s = "".join(chr(b) if 32 <= b <= 126 else " " for b in val).strip()
            attrs[aid] = s
    # Return the result
        return resp, attrs
# endregion

# endregion
    @staticmethod
# Function: parse_avrcp_metadata - Parses simple AVRCP metadata for tests
    def parse_avrcp_metadata(data):
# region parse_avrcp_metadata
    # parse_avrcp_metadata handles simple parsing logic for tests. #
        if len(data) < 3:
            return {}

        attr_id = data[0]
        # Skip charset byte at data[1]
        length = data[2]

        # Validate that data contains enough bytes for the declared length
        if len(data) < 3 + length:
            return {}

        text = data[3:3 + length].decode("utf-8", "replace")

        result = {}
        if attr_id in _AVRCP_ATTR_NAMES:
            result[_AVRCP_ATTR_NAMES[attr_id]] = text
        return result
    # endregion

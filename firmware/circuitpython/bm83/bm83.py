import time
from utils.common import dprint, _sanitize_text

# endregion
# Class: Bm83 - Represents the Bm83 class.
class Bm83:
# region Bm83
# Bm83 class encapsulates functionality related to bm83. #
    OP_MMI_ACTION = 0x02
    OP_EVENT_FILTER = 0x03
    OP_MUSIC_CONTROL = 0x04
    OP_AVC_VENDOR_CMD = 0x0B
    OP_READ_BD_ADDR = 0x0F
    OP_BTM_UTILITY_FUNC = 0x13
    OP_EVENT_ACK = 0x14
    OP_EQ_MODE_SETTING = 0x1C
    OP_AVRCP_VENDOR_DEP_CMD = 0x4A

# endregion
    EVT_BTM_STATUS = 0x01
    EVT_EQ_MODE_IND = 0x10
    EVT_AVC_VENDOR_RSP = 0x1A
    EVT_AVRCP_VENDOR_DEP_RSP = 0x5D

# endregion
    MMI_POWER_ON_PRESS = 0x51
    MMI_POWER_ON_RELEASE = 0x52
    MMI_POWER_OFF_PRESS = 0x53
    MMI_POWER_OFF_RELEASE = 0x54
    MMI_ENTER_PAIRING = 0x5D

# endregion
    MC_PLAY_PAUSE = 0x07
    MC_NEXT = 0x09
    MC_PREV = 0x0A

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
        """Public wrapper for _frame() to support tests."""
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
    def poll(self, max_read=768):
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
    # While loop execution
        while True:
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
                self._rx = self._rx[1:]
                continue
            op = body[0]
            params = body[1:]
            dprint("[BM83 EVT] op=0x%02X len=%d data=" % (op, len(params)), " ".join("%02X" % b for b in params))
            out.append((op, params))
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
    # power_on_cmd handles power on cmd logic. #
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_POWER_ON_PRESS]))
        time.sleep(0.2)
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_POWER_ON_RELEASE]))
        time.sleep(0.5)
        self.init_link()
        self.power_on = True
        print("[POWER] ON (UART)")

# endregion
    # Loop through items
# Function: power_off_cmd - Defines the behavior for `power_off_cmd`.
    def power_off_cmd(self):
# region power_off_cmd
    # power_off_cmd handles power off cmd logic. #
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_POWER_OFF_PRESS]))
        time.sleep(1.5)
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_POWER_OFF_RELEASE]))
        self.power_on = False
        self.connected = False
        print("[POWER] OFF (UART)")

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
    # next_eq handles next eq logic. #
        self.eq_index = (self.eq_index + 1) % len(self.EQ_SEQ)
        mode = self.EQ_SEQ[self.eq_index]
        self.send(self.OP_EQ_MODE_SETTING, bytes([mode, 0x00]))
    # Return the result
        return mode
# endregion

# endregion
    # Loop through items
# Function: note_btm_state - Defines the behavior for `note_btm_state`.
    def note_btm_state(self, state):
# region note_btm_state
    # note_btm_state handles note btm state logic. #
        now = time.monotonic()
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
# Function: avrcp_get_element_attributes - Defines the behavior for `avrcp_get_element_attributes`.
    def avrcp_get_element_attributes(self, db=0):
# region avrcp_get_element_attributes
    # avrcp_get_element_attributes handles avrcp get element attributes logic. #
        attr_ids = (1, 2, 3, 6, 4, 5, 7)
        p = bytes([len(attr_ids)])
    # Loop through items
        for a in attr_ids:
            p += int(a).to_bytes(4, "big")
        self.send(self.OP_AVRCP_VENDOR_DEP_CMD, bytes([db, 0x20]) + p)

# endregion
    # Loop through items
# Function: schedule_attrs - Defines the behavior for `schedule_attrs`.
    def schedule_attrs(self, delay_s=0.35):
# region schedule_attrs
    # schedule_attrs handles schedule attrs logic. #
        now = time.monotonic()
    # Conditional check
        if (now - self._last_attrs_req_at) < self._attrs_throttle_s:
            return
        t = now + delay_s
    # Conditional check
        if self._next_attrs_at == 0.0 or t < self._next_attrs_at:
            self._next_attrs_at = t

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
    # Conditional check
        if self._next_attrs_at and now >= self._next_attrs_at:
            self._last_attrs_req_at = now
            self._next_attrs_at = 0.0
            self.avrcp_get_element_attributes(0)

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
        if self._gea_expect_len is None:
            self._gea_expect_len = total_len
            self._gea_frag = bytearray()
        self._gea_frag.extend(part)
    # Conditional check
        if is_end != 0x01:
    # Return the result
            return None
# endregion
        full = bytes(self._gea_frag[: self._gea_expect_len])
        self._gea_frag = bytearray()
        self._gea_expect_len = None
        attrs = {}
        idx = 0
    # Loop through items
        for _ in range(attr_num):
    # Conditional check
            if idx + 8 > len(full):
                break
            aid = int.from_bytes(full[idx : idx + 4], "big")
            vlen = int.from_bytes(full[idx + 6 : idx + 8], "big")
            val = full[idx + 8 : idx + 8 + vlen]
            idx += 8 + vlen
    # Try block to catch exceptions
            try:
                s = val.decode("utf-8", "replace").strip()
    # Handle exceptions
            except Exception:
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
        """Parse simple AVRCP metadata from raw attribute data.
        
        Test format: attr_id (1 byte), charset (1 byte), length (1 byte), text
        Maps attr_id: 1=title, 2=artist, 3=album, 4=track_num, 5=total_tracks, 6=genre
        """
        if len(data) < 3:
            return {}
        
        attr_id = data[0]
        # Skip charset byte at data[1]
        length = data[2]
        if len(data) < 3 + length:
            # Inconsistent length; treat as no valid metadata
            return {}
        
        # Validate that data contains enough bytes for the declared length
        if len(data) < 3 + length:
            return {}
        
        text = data[3:3 + length].decode("utf-8", "replace")
        
        # Map attribute IDs to names
        attr_names = {
            1: "title",
            2: "artist", 
            3: "album",
            4: "track_num",
            5: "total_tracks",
            6: "genre"
        }
        
        result = {}
        if attr_id in attr_names:
            result[attr_names[attr_id]] = text
        return result
# endregion
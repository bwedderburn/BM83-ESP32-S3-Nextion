# Documentation for `main.py`

```python
import gc
import time
import board
import busio

# endregion
from utils.common import dprint, _fmt_ms, _sanitize_text
from nextion.display import Nextion, NX_RUNTIME, EQ_OBJ_PAGE0, EQ_OBJ_PAGE1, AUX_OBJ_PAGE1
from blehid.ble import BleHid
from bm83.bm83 import Bm83

# endregion
NX_BAUD = 9600
BM83_BAUD = 115200
NX_TX, NX_RX = board.IO15, board.IO16
BM83_TX, BM83_RX = board.IO17, board.IO18

# endregion
BLE_ENABLED = True
BLE_NAME = "AmpBench Remote"

# endregion
# Function: main - Defines the behavior for `main`.
def main():
# region main
# main handles main logic. 
    gc.collect()

# endregion
    nx_uart = busio.UART(NX_TX, NX_RX, baudrate=NX_BAUD, timeout=0.0, receiver_buffer_size=1024)
    bm_uart = busio.UART(BM83_TX, BM83_RX, baudrate=BM83_BAUD, timeout=0.0, receiver_buffer_size=8192)

# endregion
    nx = Nextion(nx_uart)
    bm = Bm83(bm_uart)

# endregion
    ble = BleHid(BLE_ENABLED, BLE_NAME)
    ble.setup()

# endregion
    print("=== ESP32-S3 BM83 + Nextion + BLE HID (VOLUME ONLY) ===")

# endregion
    nx.boot_sync(0.9)

# endregion
    desired_eq = "OFF"
    # Loop through items
    desired_meta = {k: "—" for k in NX_RUNTIME.keys()}
    desired_aux = ""
    aux_mode = False
    aux_mode_prev = False

# endregion
    AVRCP_SILENCE_TO_AUX_S = 4.0
    AVRCP_PROBE_PERIOD_S = 3.0
    next_avrcp_probe_at = 0.0
    last_avrcp_rx_at = 0.0
    last_pos_ms = None
    last_total_ms = None
    last_voldn_at = 0.0
    mute_window_s = 0.35

# endregion
    # Loop through items
# Function: flush_page - Defines the behavior for `flush_page`.
    def flush_page(pageid):
# region flush_page
    # flush_page handles flush page logic. 
    # Conditional check
        if pageid == 0:
            nx.set_text_active_page(EQ_OBJ_PAGE0, desired_eq)
    # Conditional check
        elif pageid == 1:
            nx.set_text_active_page(EQ_OBJ_PAGE1, desired_eq)
            nx.set_text_active_page(AUX_OBJ_PAGE1, desired_aux)
    # Loop through items
            for k, obj in NX_RUNTIME.items():
                nx.set_text_active_page(obj, desired_meta.get(k, "—"))

# endregion
    # Loop through items
# Function: maybe_track_changed - Defines the behavior for `maybe_track_changed`.
    def maybe_track_changed(pos_ms, total_ms):
# region maybe_track_changed
    # maybe_track_changed handles maybe track changed logic. 
        nonlocal last_pos_ms, last_total_ms
    # Conditional check
        if pos_ms is None or total_ms is None:
            last_pos_ms = pos_ms
            last_total_ms = total_ms
    # Return the result
            return False
# endregion
        changed = False
    # Conditional check
        if last_total_ms and total_ms > 0 and last_total_ms > 0 and total_ms != last_total_ms:
            changed = True
    # Conditional check
        if last_pos_ms is not None and (pos_ms + 2500) < last_pos_ms and pos_ms < 3000:
            changed = True
        last_pos_ms = pos_ms
        last_total_ms = total_ms
    # Return the result
        return changed
# endregion

# endregion
    # Loop through items
# Function: enter_aux_mode - Defines the behavior for `enter_aux_mode`.
    def enter_aux_mode():
# region enter_aux_mode
    # enter_aux_mode handles enter aux mode logic. 
        nonlocal desired_aux, desired_meta, last_pos_ms, last_total_ms
        desired_aux = "AUX IN"
    # Loop through items
        for k in desired_meta:
            desired_meta[k] = "—"
        last_pos_ms = None
        last_total_ms = None

# endregion
    # Loop through items
# Function: exit_aux_mode - Defines the behavior for `exit_aux_mode`.
    def exit_aux_mode():
# region exit_aux_mode
    # exit_aux_mode handles exit aux mode logic. 
        nonlocal desired_aux
        desired_aux = ""
        bm._next_playstatus_at = 0.0
        bm.schedule_attrs(0.3)

# endregion
    last_gc = time.monotonic()

# endregion
    # While loop execution
    while True:
        now = time.monotonic()
    # Conditional check
        if now - last_gc > 8.0:
            gc.collect()
            last_gc = now

# endregion
        nx.tick()
        tokens, page_changed = nx.read()
    # Conditional check
        if page_changed and nx.current_page is not None:
            dprint("[NX] page=", nx.current_page)
            flush_page(nx.current_page)

# endregion
        ble.tick()

# endregion
        streaming_seems_active = bm.connected and last_avrcp_rx_at > 0.0 and (now - last_avrcp_rx_at) < AVRCP_SILENCE_TO_AUX_S
        aux_mode = bm.power_on and (not bm.connected or not streaming_seems_active)

# endregion
    # Conditional check
        if aux_mode != aux_mode_prev:
            aux_mode_prev = aux_mode
    # Conditional check
            if aux_mode:
                print("[AUX] inferred -> gating AVRCP polling, showing tAUX")
                enter_aux_mode()
            else:
                print("[AUX] cleared -> enabling AVRCP polling, hiding tAUX")
                exit_aux_mode()
    # Conditional check
            if nx.current_page == 1:
                flush_page(1)

# endregion
    # Conditional check
        if not aux_mode:
            bm.tick_avrcp()
        else:
    # Conditional check
            if bm.connected and now >= next_avrcp_probe_at:
                next_avrcp_probe_at = now + AVRCP_PROBE_PERIOD_S
                bm.avrcp_get_play_status(0)

# endregion
    # Loop through items
        for op, params in bm.poll():
            bm.ack_event(op)
    # Conditional check
            if op == bm.EVT_BTM_STATUS and params:
                state = params[0]
                print("[BTM_Status] state=0x%02X" % state)
                change = bm.note_btm_state(state)
    # Conditional check
                if change == "CONNECTED":
                    print("[BTM] Connected -> register notifications + request metadata")
                    bm.avrcp_register_notification(0x01, interval_s=1)
                    bm.avrcp_register_notification(0x02, interval_s=0)
                    bm.avrcp_register_notification(0x05, interval_s=1)
                    bm._next_playstatus_at = 0.0
                    bm.schedule_attrs(0.8)
    # Conditional check
            elif op == bm.EVT_EQ_MODE_IND and params:
                mode = params[0]
                desired_eq = bm.EQ_L.get(mode, "OFF")
                dprint("[EQ_IND] mode=%d label=%s" % (mode, desired_eq))
    # Conditional check
                if nx.current_page is not None:
                    flush_page(nx.current_page)
    # Conditional check
            elif op == bm.EVT_AVC_VENDOR_RSP:
                parsed = bm.parse_avc_vendor_rsp(params)
    # Conditional check
                if not parsed:
                    continue
                _db, pdu, pkt_type, avp = parsed
    # Conditional check
                if pkt_type != 0x00:
                    continue
                last_avrcp_rx_at = time.monotonic()
    # Conditional check
                if pdu == 0x30 and len(avp) >= 9:
                    total_ms = int.from_bytes(avp[0:4], "big")
                    pos_ms = int.from_bytes(avp[4:8], "big")
                    desired_meta["time_cur"] = _fmt_ms(pos_ms)
    # Conditional check
                    if total_ms > 0:
                        desired_meta["time"] = _fmt_ms(total_ms)
    # Conditional check
                    if maybe_track_changed(pos_ms, total_ms):
                        dprint("[TRACK] inferred change -> request metadata")
                        bm.schedule_attrs(0.25)
    # Conditional check
                    if nx.current_page == 1 and not aux_mode:
                        flush_page(1)
    # Conditional check
                elif pdu == 0x31 and len(avp) >= 1:
                    event_id = avp[0]
    # Conditional check
                    if event_id == 0x02:
                        dprint("[AVRCP] TrackChanged -> request metadata")
                        bm.schedule_attrs(0.25)
                        bm.avrcp_register_notification(0x02, interval_s=0)
    # Conditional check
                    elif event_id == 0x05 and len(avp) >= 5:
                        pos = int.from_bytes(avp[1:5], "big")
                        desired_meta["time_cur"] = _fmt_ms(pos)
    # Conditional check
                        if nx.current_page == 1 and not aux_mode:
                            flush_page(1)
    # Conditional check
            elif op == bm.EVT_AVRCP_VENDOR_DEP_RSP:
                gea = bm.parse_gea_0x5d(params)
    # Conditional check
                if gea:
                    last_avrcp_rx_at = time.monotonic()
                    _resp, attrs = gea
                    print("[META] GetElementAttributes received:", sorted(attrs.keys()))
    # Conditional check
                    if 1 in attrs:
                        desired_meta["title"] = _sanitize_text(attrs[1])
    # Conditional check
                    if 2 in attrs:
                        desired_meta["artist"] = _sanitize_text(attrs[2])
    # Conditional check
                    if 3 in attrs:
                        desired_meta["album"] = _sanitize_text(attrs[3])
    # Conditional check
                    if 6 in attrs:
                        desired_meta["genre"] = _sanitize_text(attrs[6])
    # Conditional check
                    if 4 in attrs:
                        desired_meta["track_num"] = _sanitize_text(attrs[4], max_len=8)
    # Conditional check
                    if 5 in attrs:
                        desired_meta["total_tracks"] = _sanitize_text(attrs[5], max_len=8)
    # Conditional check
                    if 7 in attrs:
                        desired_meta["time"] = _fmt_ms(attrs[7])
    # Conditional check
                    if nx.current_page == 1 and not aux_mode:
                        flush_page(1)

# endregion
    # Loop through items
        for tok in tokens:
            dprint("[NX] Token:", tok)
    # Conditional check
            if tok == b"BT_POWER":
                bm.power_toggle()
    # Conditional check
            elif tok == b"BT_PAIR":
                bm.pair()
    # Conditional check
            elif tok == b"BT_PLAY":
                bm.play_pause()
    # Conditional check
            elif tok == b"BT_PREV":
                bm.prev()
    # Conditional check
            elif tok == b"BT_NEXT":
                bm.next()
    # Conditional check
            elif tok == b"BT_EQ":
                mode = bm.next_eq()
                desired_eq = bm.EQ_L.get(mode, "OFF")
                print("[EQ] set to", desired_eq)
    # Conditional check
                if nx.current_page is not None:
                    flush_page(nx.current_page)
    # Conditional check
            elif tok == b"BT_VOLUP":
                ble.volume(True)
    # Conditional check
            elif tok == b"BT_VOLDN":
    # Conditional check
                if (now - last_voldn_at) <= mute_window_s:
                    ble.mute()
                    last_voldn_at = 0.0
                else:
                    ble.volume(False)
                    last_voldn_at = now
    # Conditional check
            elif tok == b"BT_EBIND":
                ble.erase_bonds()

# endregion
        time.sleep(0.005)

# endregion
    # Conditional check
if __name__ == "__main__":
    # Try block to catch exceptions
    try:
        main()
    # Handle exceptions
    except Exception as e:
    # Try block to catch exceptions
        try:
            import traceback
            print("[FATAL]", e)
            traceback.print_exception(e)
    # Handle exceptions
        except Exception:
            print("[FATAL]", e)
    # While loop execution
        while True:
            time.sleep(1)
```


# Documentation for `setup.py`

```python
from setuptools import setup, find_packages

# endregion
setup(
    name="esp32-audio-remote",
    version="1.0.0",
    description="CircuitPython-based audio remote with BM83, BLE HID, and Nextion display",
    author="Your Name",
    author_email="you@example.com",
    url="https://github.com/yourusername/esp32-audio-remote",
    packages=find_packages(),
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
)
```


# Documentation for `nextion/__init__.py`

```python

```


# Documentation for `nextion/display.py`

```python
import time
from utils.common import dprint, _sanitize_text

# endregion
TERM = b"\xFF\xFF\xFF"
TOKENS = {
    b"BT_POWER", b"BT_POWEROFF", b"BT_PAIR", b"BT_PLAY", b"BT_PREV",
    b"BT_NEXT", b"BT_EQ", b"BT_VOLUP", b"BT_VOLDN", b"BT_EBIND"
}

# endregion
EQ_OBJ_PAGE0 = "tEQ0"
EQ_OBJ_PAGE1 = "tEQ1"
AUX_OBJ_PAGE1 = "tAUX"

# endregion
NX_RUNTIME = {
    "title": "tTitle", "artist": "tArtist", "album": "tAlbum", "genre": "tGenre",
    "time_cur": "tTIME_CUR", "time": "tTime", "track_num": "tTrack_num",
    "total_tracks": "tTotalTracks"
}

# endregion
# Class: Nextion - Represents the Nextion class.
class Nextion:
# region Nextion
# Nextion class encapsulates functionality related to nextion. 
    # Loop through items
# Function: __init__ - Defines the behavior for `__init__`.
    def __init__(self, uart):
# region __init__
    # __init__ handles   init   logic. 
        self.uart = uart
        self._rx = bytearray()

# endregion
        self.current_page = None
        self._last_sendme_at = 0.0
        self._sendme_period_s = 0.5

# endregion
        self._txq = []
        self._last_tx_at = 0.0
        self._tx_interval_s = 0.035

# endregion
        self._last_token = None
        self._last_token_at = 0.0

# endregion
    # Loop through items
# Function: boot_sync - Defines the behavior for `boot_sync`.
    def boot_sync(self, delay_s=0.8):
# region boot_sync
    # boot_sync handles boot sync logic. 
        time.sleep(delay_s)
        self._rx = bytearray()
        self._txq.clear()
        self.current_page = None
        self._last_sendme_at = 0.0
        self._last_tx_at = 0.0
        self.enqueue("bkcmd=3")
        self.enqueue("sendme")

# endregion
    # Loop through items
# Function: enqueue - Defines the behavior for `enqueue`.
    def enqueue(self, cmd):
# region enqueue
    # enqueue handles enqueue logic. 
        self._txq.append(cmd)

# endregion
    # Loop through items
# Function: sendme_tick - Defines the behavior for `sendme_tick`.
    def sendme_tick(self):
# region sendme_tick
    # sendme_tick handles sendme tick logic. 
        now = time.monotonic()
    # Conditional check
        if (now - self._last_sendme_at) >= self._sendme_period_s:
            self._last_sendme_at = now
            self.enqueue("sendme")

# endregion
    # Loop through items
# Function: tick - Defines the behavior for `tick`.
    def tick(self):
# region tick
    # tick handles tick logic. 
        self.sendme_tick()
        now = time.monotonic()
    # Conditional check
        if not self._txq or (now - self._last_tx_at) < self._tx_interval_s:
            return
        cmd = self._txq.pop(0)
    # Try block to catch exceptions
        try:
            self.uart.write(cmd.encode("ascii", "replace") + TERM)
            self._last_tx_at = now
    # Handle exceptions
        except Exception as e:
            dprint("[NX] write err:", e)

# endregion
    # Loop through items
# Function: _read_more - Defines the behavior for `_read_more`.
    def _read_more(self):
# region _read_more
    # _read_more handles  read more logic. 
    # Try block to catch exceptions
        try:
            n = getattr(self.uart, "in_waiting", 0) or 0
            chunk = self.uart.read(min(256, n)) if n else None
    # Handle exceptions
        except Exception as e:
            dprint("[NX] read err:", e)
            return
    # Conditional check
        if chunk:
            self._rx.extend(chunk)

# endregion
    # Loop through items
# Function: _pop_frame - Defines the behavior for `_pop_frame`.
    def _pop_frame(self):
# region _pop_frame
    # _pop_frame handles  pop frame logic. 
        i = self._rx.find(TERM)
    # Conditional check
        if i < 0:
    # Return the result
            return None
# endregion
        frame = bytes(self._rx[:i])
        self._rx = self._rx[i + 3:]
    # Return the result
        return frame
# endregion

# endregion
    @staticmethod
    # Loop through items
# Function: _is_token_frame - Defines the behavior for `_is_token_frame`.
    def _is_token_frame(frame):
# region _is_token_frame
    # _is_token_frame handles  is token frame logic. 
        f = frame.strip()
    # Conditional check
        if not f:
    # Return the result
            return False
# endregion
    # Loop through items
        for b in f:
    # Conditional check
            if 48 <= b <= 57 or 65 <= b <= 90 or b == 95:
                continue
    # Return the result
            return False
# endregion
    # Return the result
        return f in TOKENS
# endregion

# endregion
    # Loop through items
# Function: read - Defines the behavior for `read`.
    def read(self, max_tokens=6, debounce_s=0.10):
# region read
    # read handles read logic. 
        tokens = []
        page_changed = False
        self._read_more()
    # While loop execution
        while True:
            frame = self._pop_frame()
    # Conditional check
            if frame is None:
                break
    # Conditional check
            if len(frame) >= 2 and frame[0] == 0x66:
                pageid = frame[1]
    # Conditional check
                if self.current_page != pageid:
                    self.current_page = pageid
                    page_changed = True
                continue
    # Conditional check
            if self._is_token_frame(frame):
                now = time.monotonic()
    # Conditional check
                if self._last_token == frame and (now - self._last_token_at) < debounce_s:
                    continue
                self._last_token = frame
                self._last_token_at = now
                tokens.append(frame)
    # Conditional check
                if len(tokens) >= max_tokens:
                    break
    # Return the result
        return tokens, page_changed
# endregion

# endregion
    # Loop through items
# Function: set_text_active_page - Defines the behavior for `set_text_active_page`.
    def set_text_active_page(self, obj, txt):
# region set_text_active_page
    # set_text_active_page handles set text active page logic. 
        safe = _sanitize_text(txt)
        self.enqueue('%s.txt="%s"' % (obj, safe))
```


# Documentation for `bm83/__init__.py`

```python

```


# Documentation for `bm83/bm83.py`

```python
import time
from utils.common import dprint, _sanitize_text

# endregion
# Class: Bm83 - Represents the Bm83 class.
class Bm83:
# region Bm83
# Bm83 class encapsulates functionality related to bm83. 
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
    CONNECTED_STATES = (0x06, 0x0B, 0x82, 0x64, 0x65, 0x66)

# endregion
    # Loop through items
# Function: __init__ - Defines the behavior for `__init__`.
    def __init__(self, uart):
# region __init__
    # __init__ handles   init   logic. 
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
    # _checksum handles  checksum logic. 
    # Return the result
        return (-((hi + lo + sum(body)) & 0xFF)) & 0xFF
# endregion

# endregion
    # Loop through items
# Function: _frame - Defines the behavior for `_frame`.
    def _frame(self, op, params=b""):
# region _frame
    # _frame handles  frame logic. 
        body = bytes([op]) + params
        ln = len(body)
        hi, lo = (ln >> 8) & 0xFF, ln & 0xFF
        chk = self._checksum(hi, lo, body)
    # Return the result
        return bytes([0xAA, hi, lo]) + body + bytes([chk])
# endregion

# endregion
    # Loop through items
# Function: send - Defines the behavior for `send`.
    def send(self, op, params=b""):
# region send
    # send handles send logic. 
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
    # ack_event handles ack event logic.  
    # Conditional check
        if event_op == 0x00:
            return
        self.send(self.OP_EVENT_ACK, bytes([event_op & 0xFF]))

# endregion
    # Loop through items
# Function: poll - Defines the behavior for `poll`.
    def poll(self, max_read=768):
# region poll
     # poll handles poll logic. 
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
    # init_link handles init link logic.  
        self.send(self.OP_READ_BD_ADDR)
        self.send(self.OP_EVENT_FILTER, b"\x00\x00\x00\x00")
        self.send(self.OP_BTM_UTILITY_FUNC, b"\x03\x01")
        print("[BM83] Link initialized")

# endregion
    # Loop through items
# Function: power_on_cmd - Defines the behavior for `power_on_cmd`.
    def power_on_cmd(self):
# region power_on_cmd
    # power_on_cmd handles power on cmd logic. 
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
    # power_off_cmd handles power off cmd logic. 
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
    # power_toggle handles power toggle logic. 
        self.power_off_cmd() if self.power_on else self.power_on_cmd()

# endregion
    # Loop through items
# Function: pair - Defines the behavior for `pair`.
    def pair(self):
# region pair
    # pair handles pair logic. 
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_ENTER_PAIRING]))
        print("[PAIR] Enter pairing")

# endregion
    # Loop through items
# Function: play_pause - Defines the behavior for `play_pause`.
    def play_pause(self):
# region play_pause
    # play_pause handles play pause logic. 
        self.send(self.OP_MUSIC_CONTROL, bytes([0x00, self.MC_PLAY_PAUSE]))
        print("[PLAY/PAUSE] toggled")

# endregion
    # Loop through items
# Function: prev - Defines the behavior for `prev`.
    def prev(self):
# region prev
    # prev handles prev logic. 
        self.send(self.OP_MUSIC_CONTROL, bytes([0x00, self.MC_PREV]))
        print("[PREV] triggered")

# endregion
    # Loop through items
# Function: next - Defines the behavior for `next`.
    def next(self):
# region next
    # next handles next logic. 
        self.send(self.OP_MUSIC_CONTROL, bytes([0x00, self.MC_NEXT]))
        print("[NEXT] triggered")

# endregion
    # Loop through items
# Function: next_eq - Defines the behavior for `next_eq`.
    def next_eq(self):
# region next_eq
    # next_eq handles next eq logic. 
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
    # note_btm_state handles note btm state logic. 
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
    # _avc_payload handles  avc payload logic. 
    # Return the result
        return bytes([pdu, 0x00]) + len(params).to_bytes(2, "big") + params
# endregion

# endregion
    # Loop through items
# Function: avrcp_get_play_status - Defines the behavior for `avrcp_get_play_status`.
    def avrcp_get_play_status(self, db=0):
# region avrcp_get_play_status
    # avrcp_get_play_status handles avrcp get play status logic. 
        self.send(self.OP_AVC_VENDOR_CMD, bytes([db]) + self._avc_payload(0x30, b""))

# endregion
    # Loop through items
# Function: avrcp_register_notification - Defines the behavior for `avrcp_register_notification`.
    def avrcp_register_notification(self, event_id, interval_s=0, db=0):
# region avrcp_register_notification
    # avrcp_register_notification handles avrcp register notification logic. 
        params = bytes([event_id]) + int(interval_s).to_bytes(4, "big")
        self.send(self.OP_AVC_VENDOR_CMD, bytes([db]) + self._avc_payload(0x31, params))

# endregion
    # Loop through items
# Function: avrcp_get_element_attributes - Defines the behavior for `avrcp_get_element_attributes`.
    def avrcp_get_element_attributes(self, db=0):
# region avrcp_get_element_attributes
    # avrcp_get_element_attributes handles avrcp get element attributes logic. 
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
    # schedule_attrs handles schedule attrs logic. 
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
    # tick_avrcp handles tick avrcp logic. 
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
    # parse_avc_vendor_rsp handles parse avc vendor rsp logic. 
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
    # parse_gea_0x5d handles parse gea 0x5d logic. 
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
```


# Documentation for `blehid/__init__.py`

```python

```


# Documentation for `blehid/ble.py`

```python
import time
import gc
from utils.common import dprint

# endregion
# Class: BleHid - Represents the BleHid class.
class BleHid:
# region BleHid
# BleHid class encapsulates functionality related to blehid. 
    # Loop through items
# Function: __init__ - Defines the behavior for `__init__`.
    def __init__(self, enabled, name):
# region __init__
    # __init__ handles   init   logic. 
        self.enabled = enabled
        self.name = name

# endregion
        self._ble = None
        self._adv = None
        self._hid = None
        self._cc = None
        self._CCC = None

# endregion
        self._ready = False
        self._was_connected = False

# endregion
        self._adv_inhibit_until = 0.0
        self._adv_oom_count = 0
        self._adv_kick_period_s = 6.0
        self._last_adv_kick_at = 0.0

# endregion
        self._last_cc_at = 0.0
        self._cc_min_interval_s = 0.06

# endregion
        self._need_pairing_check = False
        self._last_pair_try_at = 0.0
        self._pair_retry_s = 2.0
        self._pair_attempts = 0
        self._pair_attempt_limit = 4

# endregion
    # Loop through items
# Function: setup - Defines the behavior for `setup`.
    def setup(self):
# region setup
    # setup handles setup logic. 
    # Conditional check
        if not self.enabled:
            return
    # Try block to catch exceptions
        try:
            from adafruit_ble import BLERadio
            from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
            from adafruit_ble.services.standard.hid import HIDService
            from adafruit_hid.consumer_control import ConsumerControl
            from adafruit_hid.consumer_control_code import ConsumerControlCode as CCC

# endregion
            self._ble = BLERadio()
            self._ble.name = self.name

# endregion
            self._hid = HIDService()
            self._adv = ProvideServicesAdvertisement(self._hid)
            self._cc = ConsumerControl(self._hid.devices)
            self._CCC = CCC

# endregion
            self._ready = True
            print("[BLE] Ready:", self.name)
            self._start_adv(force=True)
    # Handle exceptions
        except Exception as e:
            print("[BLE] Disabled:", e)
            self._ready = False

# endregion
    # Loop through items
# Function: _stop_adv - Defines the behavior for `_stop_adv`.
    def _stop_adv(self):
# region _stop_adv
    # _stop_adv handles  stop adv logic. 
    # Conditional check
        if not self._ready or not self._ble:
            return
    # Try block to catch exceptions
        try:
    # Conditional check
            if getattr(self._ble, "advertising", False):
                self._ble.stop_advertising()
    # Handle exceptions
        except Exception as e:
            dprint("[BLE] stop adv err:", e)

# endregion
    # Loop through items
# Function: _start_adv - Defines the behavior for `_start_adv`.
    def _start_adv(self, force=False):
# region _start_adv
    # _start_adv handles  start adv logic. 
    # Conditional check
        if not self._ready or not self._ble or not self._adv:
            return
        now = time.monotonic()

# endregion
    # Conditional check
        if now < self._adv_inhibit_until:
            return
    # Conditional check
        if getattr(self._ble, "connected", False):
            return
        advertising = False
    # Try block to catch exceptions
        try:
            advertising = bool(getattr(self._ble, "advertising", False))
    # Handle exceptions
        except Exception:
            advertising = False
    # Conditional check
        if advertising and not force:
            return
    # Conditional check
        if force:
            self._stop_adv()
        gc.collect()
    # Try block to catch exceptions
        try:
            self._ble.start_advertising(self._adv)
            self._adv_oom_count = 0
            self._adv_inhibit_until = 0.0
            self._last_adv_kick_at = now
    # Handle exceptions
        except Exception as e:
            msg = str(e).lower()
    # Conditional check
            if "nimble" in msg and "memory" in msg:
                self._adv_oom_count += 1
                backoff = min(20.0, 4.0 + 4.0 * self._adv_oom_count)
            else:
                backoff = 4.0
            self._adv_inhibit_until = now + backoff
            self._last_adv_kick_at = now + backoff
            dprint("[BLE] adv err (backoff %.1fs):" % backoff, e)

# endregion
    # Loop through items
# Function: _on_connect - Defines the behavior for `_on_connect`.
    def _on_connect(self):
# region _on_connect
    # _on_connect handles  on connect logic. 
        print("[BLE] Connected")
    # Try block to catch exceptions
        try:
            from adafruit_hid.consumer_control import ConsumerControl
            self._cc = ConsumerControl(self._hid.devices)
    # Handle exceptions
        except Exception as e:
            print("[BLE] ConsumerControl init fail:", e)
        self._need_pairing_check = True
        self._pair_attempts = 0
        self._last_pair_try_at = 0.0

# endregion
    # Loop through items
# Function: _on_disconnect - Defines the behavior for `_on_disconnect`.
    def _on_disconnect(self):
# region _on_disconnect
    # _on_disconnect handles  on disconnect logic. 
        print("[BLE] Disconnected")
        self._need_pairing_check = False
        self._pair_attempts = 0
        self._start_adv(force=True)

# endregion
    # Loop through items
# Function: _ensure_paired - Defines the behavior for `_ensure_paired`.
    def _ensure_paired(self):
# region _ensure_paired
    # _ensure_paired handles  ensure paired logic. 
    # Conditional check
        if not self._ble or not getattr(self._ble, "connected", False):
            return
    # Conditional check
        if self._pair_attempts >= self._pair_attempt_limit:
            self._need_pairing_check = False
            return
        now = time.monotonic()
    # Conditional check
        if (now - self._last_pair_try_at) < self._pair_retry_s:
            return
        self._last_pair_try_at = now

# endregion
    # Try block to catch exceptions
        try:
            conns = list(getattr(self._ble, "connections", []))
    # Handle exceptions
        except Exception:
            conns = []

# endregion
    # Loop through items
        for c in conns:
    # Try block to catch exceptions
            try:
                paired = getattr(c, "paired", None)
    # Conditional check
                if paired is False:
                    print("[BLE] Pairing...")
                    c.pair()
                    self._pair_attempts += 1
                    paired = getattr(c, "paired", None)

# endregion
    # Conditional check
                if paired:
                    self._need_pairing_check = False
                    self._pair_attempts = 0
                    print("[BLE] Paired/encrypted")
    # Handle exceptions
            except Exception as e:
                self._pair_attempts += 1
                dprint("[BLE] pair err (attempt %d):" % self._pair_attempts, e)

# endregion
    # Loop through items
# Function: erase_bonds - Defines the behavior for `erase_bonds`.
    def erase_bonds(self):
# region erase_bonds
    # erase_bonds handles erase bonds logic. 
        print("[BLE] Erase bonding requested")
    # Try block to catch exceptions
        try:
    # Loop through items
            for c in list(getattr(self._ble, "connections", [])):
    # Try block to catch exceptions
                try:
                    c.disconnect()
    # Handle exceptions
                except Exception:
                    pass
    # Handle exceptions
        except Exception:
            pass

# endregion
        ok = False
    # Try block to catch exceptions
        try:
    # Conditional check
            if hasattr(self._ble, "erase_bonding"):
                self._ble.erase_bonding()
                ok = True
    # Handle exceptions
        except Exception:
            ok = False

# endregion
    # Conditional check
        if not ok:
    # Try block to catch exceptions
            try:
                import _bleio
    # Conditional check
                if hasattr(_bleio.adapter, "erase_bonding"):
                    _bleio.adapter.erase_bonding()
                    ok = True
    # Handle exceptions
            except Exception:
                ok = False

# endregion
    # Conditional check
        print("[BLE] erase_bonding:", "OK" if ok else "Unavailable on this build")
        self._adv_inhibit_until = 0.0
        self._adv_oom_count = 0
        self._need_pairing_check = False
        self._pair_attempts = 0
        self._start_adv(force=True)

# endregion
    # Loop through items
# Function: tick - Defines the behavior for `tick`.
    def tick(self):
# region tick
    # tick handles tick logic. 
    # Conditional check
        if not self._ready or not self._ble:
            return
        connected = bool(getattr(self._ble, "connected", False))
    # Conditional check
        if connected != self._was_connected:
            self._was_connected = connected
    # Conditional check
            if connected:
                self._on_connect()
            else:
                self._on_disconnect()
        now = time.monotonic()
    # Conditional check
        if not connected:
            advertising = False
    # Try block to catch exceptions
            try:
                advertising = bool(getattr(self._ble, "advertising", False))
    # Handle exceptions
            except Exception:
                advertising = False
    # Conditional check
            if not advertising:
                self._start_adv(force=False)
    # Conditional check
            elif (now - self._last_adv_kick_at) > self._adv_kick_period_s:
                self._last_adv_kick_at = now
        else:
    # Conditional check
            if self._need_pairing_check:
                self._ensure_paired()

# endregion
    # Loop through items
# Function: _send_ccc - Defines the behavior for `_send_ccc`.
    def _send_ccc(self, code):
# region _send_ccc
    # _send_ccc handles  send ccc logic. 
    # Conditional check
        if not self._ready or not self._ble or not self._cc:
            return
    # Conditional check
        if not getattr(self._ble, "connected", False):
            return
        now = time.monotonic()
    # Conditional check
        if (now - self._last_cc_at) < self._cc_min_interval_s:
            return
        self._last_cc_at = now
    # Conditional check
        if self._need_pairing_check:
            self._ensure_paired()
    # Try block to catch exceptions
        try:
            self._cc.send(code)
    # Handle exceptions
        except Exception as e:
            print("[BLE] send fail:", e)

# endregion
    # Loop through items
# Function: volume - Defines the behavior for `volume`.
    def volume(self, up):
# region volume
    # volume handles volume logic. 
    # Conditional check
        if not self._CCC:
            return
        self._send_ccc(self._CCC.VOLUME_INCREMENT if up else self._CCC.VOLUME_DECREMENT)

# endregion
    # Loop through items
# Function: mute - Defines the behavior for `mute`.
    def mute(self):
# region mute
    # mute handles mute logic. 
    # Conditional check
        if not self._CCC:
            return
        self._send_ccc(self._CCC.MUTE)
```


# Documentation for `utils/__init__.py`

```python

```


# Documentation for `utils/common.py`

```python
import time

# endregion
DEBUG = True

# endregion
# Function: dprint - Defines the behavior for `dprint`.
def dprint(*a):
# region dprint
# dprint handles dprint logic. 
    # Conditional check
    if DEBUG:
        print(*a)

# endregion
    # Loop through items
# Function: _sanitize_text - Defines the behavior for `_sanitize_text`.
def _sanitize_text(txt, max_len=48):
# region _sanitize_text
# _sanitize_text handles  sanitize text logic. 
    # Conditional check
    if txt is None:
    # Return the result
        return "—"
# endregion
    out = []
    # Loop through items
    for ch in str(txt):
        o = ord(ch)
        out.append(ch if 32 <= o <= 126 else " ")
    s = "".join(out).replace('"', "'").strip()
    # Conditional check
    if not s:
        s = "—"
    # Conditional check
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    # Return the result
    return s
# endregion

# endregion
    # Loop through items
# Function: _fmt_ms - Defines the behavior for `_fmt_ms`.
def _fmt_ms(ms):
# region _fmt_ms
# _fmt_ms handles  fmt ms logic. 
    # Conditional check
    if ms is None:
    # Return the result
        return "—"
# endregion
    # Try block to catch exceptions
    try:
        ms = int(ms)
    # Handle exceptions
    except Exception:
    # Return the result
        return _sanitize_text(ms, max_len=16)
# endregion
    # Conditional check
    if ms < 0:
        ms = 0
    total = ms // 1000
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    # Conditional check
    if h > 0:
    # Return the result
        return "%d:%02d:%02d" % (h, m, s)
# endregion
    # Return the result
    return "%d:%02d" % (m, s)
# endregion
```

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
## main handles main logic. #
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
    # flush_page handles flush page logic. #
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
    # maybe_track_changed handles maybe track changed logic. #
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
    # enter_aux_mode handles enter aux mode logic. #
        nonlocal desired_aux, last_pos_ms, last_total_ms
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
    # exit_aux_mode handles exit aux mode logic. #
        nonlocal desired_aux
        desired_aux = ""
        bm._next_playstatus_at = 0.0
        bm.schedule_attrs(0.3)

# endregion
    last_gc = time.monotonic()
    gc_interval_s = 4.0  # More frequent GC to prevent memory pressure

# endregion
    # While loop execution
    while True:
        now = time.monotonic()
    # Conditional check
        if now - last_gc > gc_interval_s:
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
        # Tick non-blocking power state machine
        bm.tick_power()

# endregion
        streaming_seems_active = bm.connected and last_avrcp_rx_at > 0.0 and (now - last_avrcp_rx_at) < AVRCP_SILENCE_TO_AUX_S
        aux_mode = bm.power_on and (not bm.connected or not streaming_seems_active)

# endregion
    # Conditional check
        if aux_mode != aux_mode_prev:
            aux_mode_prev = aux_mode
    # Conditional check
            if aux_mode:
                print("[AUX] inferred -> gating AVRCP polling, showing tAUX1")
                enter_aux_mode()
            else:
                print("[AUX] cleared -> enabling AVRCP polling, hiding tAUX1")
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
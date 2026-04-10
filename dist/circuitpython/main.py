import gc
import time
import board
import busio

# endregion
from utils.common import (
    TIME_UNKNOWN,
    dprint,
    _fmt_ms,
    _fmt_track_time_ms,
    _normalize_track_time_ms,
    _sanitize_text,
)
from nextion.display import Nextion, NX_RUNTIME, EQ_OBJ_PAGE0, EQ_OBJ_PAGE1, AUX_OBJ_PAGE0, AUX_OBJ_PAGE1
from blehid.ble import BleHid
from bm83.bm83 import Bm83

# endregion
NX_BAUD = 9600
BM83_BAUD = 115200
NX_TX, NX_RX = board.IO15, board.IO16
BM83_TX, BM83_RX = board.IO17, board.IO18
VOL_REPEAT_MAX = 2

# endregion
BLE_ENABLED = True
BLE_NAME = "B's Groovy BT CTRL"

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
    # Local bindings for speed/low allocation on mpy
    monotonic = time.monotonic
    sleep = time.sleep
    nx_tick = nx.tick
    nx_read = nx.read
    nx_set_text = nx.set_text_active_page
    bm_poll = bm.poll
    bm_ack = bm.ack_event
    bm_tick_power = bm.tick_power
    bm_tick_avrcp = bm.tick_avrcp
    bm_avrcp_get_play_status = bm.avrcp_get_play_status
    ble_tick = ble.tick
    ble_volume = ble.volume
    ble_mute = ble.mute
    ble_request_erase_bonds = ble.request_erase_bonds
    ble_is_connected = ble.is_connected
    eq_labels = bm.EQ_L

# endregion
    print("=== ESP32-S3 BM83 + Nextion + BLE HID (VOLUME ONLY) ===")

# endregion
    nx.boot_sync(0.9)

# endregion
    desired_eq = "OFF"
    # Loop through items
    desired_meta = {}
    for k in NX_RUNTIME.keys():
        desired_meta[k] = TIME_UNKNOWN if k in ("time_cur", "time") else "—"
    desired_aux = ""
    aux_mode = False
    aux_mode_prev = False
    avrcp_notifs_registered = False

# endregion
    AVRCP_SILENCE_TO_AUX_S = 4.0
    AVRCP_PROBE_PERIOD_S = 3.0
    next_avrcp_probe_at = 0.0
    last_avrcp_rx_at = 0.0
    last_pos_ms = None
    last_total_ms = None
    last_play_status = None
    last_voldn_at = 0.0
    mute_window_s = 0.25
    ebind_min_interval_s = 2.0
    last_ebind_at = 0.0

    # Hold-and-repeat state for volume controls
    vol_hold_active = None        # None, "up", or "down"
    vol_hold_start_at = 0.0       # When the button was first pressed
    vol_last_repeat_at = 0.0      # When we last sent a repeat
    vol_repeat_count = 0          # How many steps have been sent in this hold
    vol_initial_delay_s = 0.85     # 850ms before repeat starts
    vol_repeat_interval_s = 0.35  # 350ms between repeats

# endregion
    META_UPDATE_ORDER = ("title", "artist", "album", "genre", "track_num", "total_tracks", "time_cur", "time")
    TRACK_STALE_KEYS = ("album", "genre", "track_num", "total_tracks", "time_cur", "time")
    PLAYING_STATES = (0x01, 0x03, 0x04)

    # Loop through items
# Function: flush_page - Defines the behavior for `flush_page`.
    def flush_page(pageid):
# region flush_page
    # flush_page handles flush page logic. #
    # Conditional check
        if pageid == 0:
            nx_set_text(EQ_OBJ_PAGE0, desired_eq)
            nx_set_text(AUX_OBJ_PAGE0, desired_aux)
    # Conditional check
        elif pageid == 1:
            nx_set_text(EQ_OBJ_PAGE1, desired_eq)
            nx_set_text(AUX_OBJ_PAGE1, desired_aux)
    # Loop through items
            for k, obj in NX_RUNTIME.items():
                nx_set_text(obj, desired_meta.get(k, "—"))

# endregion
    def push_meta_updates(keys):
        if nx.current_page != 1 or aux_mode or not keys:
            return
        for key in META_UPDATE_ORDER:
            if key in keys:
                nx_set_text(NX_RUNTIME[key], desired_meta[key])


    def meta_set(key, value, changed):
        if value is None or desired_meta.get(key) == value:
            return
        desired_meta[key] = value
        changed.append(key)


    def invalidate_track_meta(clear_primary=False):
        changed = []
        if clear_primary:
            meta_set("title", "—", changed)
            meta_set("artist", "—", changed)
        for key in TRACK_STALE_KEYS:
            meta_set(key, TIME_UNKNOWN if key in ("time_cur", "time") else "—", changed)
        return changed


    def primary_metadata_missing():
        return desired_meta.get("title") == "—" or desired_meta.get("artist") == "—"

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
        nonlocal desired_aux, last_play_status, last_pos_ms, last_total_ms
        desired_aux = "AUX IN"
        invalidate_track_meta(clear_primary=True)
        last_play_status = None
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
        bm._next_playstatus_at = monotonic() + 0.05
        bm.schedule_attrs(0.3)

# endregion
    last_gc = monotonic()
    gc_interval_s = 4.0  # Empirically chosen: 4s strikes a balance between GC overhead and memory pressure
    # On this workload (BM83 + Nextion event floods), 8s GC caused occasional alloc failures,
    # while <=2s GC increased pause time without reducing peak usage further. Tweak if patterns change.

# endregion
    # While loop execution
    while True:
        now = monotonic()
    # Conditional check
        if now - last_gc > gc_interval_s:
            gc.collect()
            last_gc = now

# endregion
        nx_tick()
        tokens, page_changed = nx_read()
    # Conditional check
        if page_changed and nx.current_page is not None:
            dprint("[NX] page=", nx.current_page)
            flush_page(nx.current_page)

# endregion
        ble_tick()

# endregion
        # Tick non-blocking power state machine
        bm_tick_power()

# endregion
        streaming_seems_active = bm.connected and last_avrcp_rx_at > 0.0 and (now - last_avrcp_rx_at) < AVRCP_SILENCE_TO_AUX_S
        aux_mode = bm.power_on and (not bm.connected or not streaming_seems_active)

# endregion
    # Conditional check
        if aux_mode != aux_mode_prev:
            aux_mode_prev = aux_mode
    # Conditional check
            if aux_mode:
                print("[AUX] inferred -> gating AVRCP polling, showing AUX indicators")
                enter_aux_mode()
            else:
                print("[AUX] cleared -> enabling AVRCP polling, hiding AUX indicators")
                exit_aux_mode()
    # Refresh current page to update AUX indicator
            flush_page(nx.current_page)

# endregion
    # Conditional check
        if not aux_mode:
            bm_tick_avrcp()
        else:
    # Conditional check
            if bm.connected and now >= next_avrcp_probe_at:
                next_avrcp_probe_at = now + AVRCP_PROBE_PERIOD_S
                bm_avrcp_get_play_status(0)

# endregion
    # Loop through items
        for op, params in bm_poll():
            bm_ack(op)
    # Conditional check
            if op == bm.EVT_BTM_STATUS and params:
                state = params[0]
                print("[BTM_Status] state=0x%02X" % state)
                change = bm.note_btm_state(state)
    # Conditional check
                if change == "CONNECTED" and not avrcp_notifs_registered:
                    print("[BTM] Connected -> register notifications + request metadata")
                    bm.avrcp_register_notification(0x01, interval_s=0)
                    bm.avrcp_register_notification(0x02, interval_s=0)
                    bm.avrcp_register_notification(0x05, interval_s=1)
                    bm._next_playstatus_at = now + 0.05
                    bm.schedule_attrs(0.8)
                    avrcp_notifs_registered = True
                elif change == "DISCONNECTED":
                    avrcp_notifs_registered = False
                    last_play_status = None
    # Conditional check
            elif op == bm.EVT_EQ_MODE_IND and params:
                mode = params[0]
                desired_eq = eq_labels.get(mode, "OFF")
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
                    total_ms = _normalize_track_time_ms(int.from_bytes(avp[0:4], "big"))
                    pos_ms = _normalize_track_time_ms(int.from_bytes(avp[4:8], "big"))
                    last_play_status = avp[8]
                    changed = []
                    if maybe_track_changed(pos_ms, total_ms):
                        changed.extend(invalidate_track_meta())
                        dprint("[TRACK] inferred change -> request metadata")
                        bm.schedule_attrs(0.25)
                    if primary_metadata_missing() and (pos_ms is not None or (total_ms is not None and total_ms > 0)):
                        bm.schedule_attrs(0.15)
                    if pos_ms is not None and (last_play_status in PLAYING_STATES or desired_meta.get("time_cur") == TIME_UNKNOWN):
                        meta_set("time_cur", _fmt_ms(pos_ms), changed)
                    if total_ms is not None and total_ms > 0:
                        meta_set("time", _fmt_ms(total_ms), changed)
                    push_meta_updates(changed)
    # Conditional check
                elif pdu == 0x31 and len(avp) >= 1:
                    event_id = avp[0]
    # Conditional check
                    if event_id == 0x01 and len(avp) >= 2:
                        # PlaybackStatusChanged: keep local status cache fresh
                        # between GetPlayStatus polling intervals.
                        prev_status = last_play_status
                        last_play_status = avp[1]
                        bm.avrcp_register_notification(0x01, interval_s=0)
                        bm._next_playstatus_at = now + 0.05
                        if last_play_status in PLAYING_STATES and (
                            primary_metadata_missing()
                            or (prev_status != last_play_status and desired_meta.get("time") == TIME_UNKNOWN)
                        ):
                            dprint("[META] playback start -> request metadata")
                            bm.schedule_attrs(0.15, force=True)
    # Conditional check
                    elif event_id == 0x02:
                        last_pos_ms = None
                        last_total_ms = None
                        push_meta_updates(invalidate_track_meta())
                        dprint("[AVRCP] TrackChanged -> request metadata")
                        bm.schedule_attrs(0.25)
                        bm.avrcp_reregister_track_changed()
                    elif event_id == 0x05 and len(avp) >= 5:
                        pos = _normalize_track_time_ms(int.from_bytes(avp[1:5], "big"))
                        # Playback Position Changed notifications may still be emitted
                        # around state transitions. Avoid advancing the UI clock while
                        # paused/stopped to prevent "counting while paused" behavior.
                        if pos is not None and last_play_status in PLAYING_STATES:
                            changed = []
                            meta_set("time_cur", _fmt_ms(pos), changed)
                            push_meta_updates(changed)
                        bm.avrcp_register_notification(0x05, interval_s=1)
    # Conditional check
            elif op == bm.EVT_AVRCP_VENDOR_DEP_RSP:
                gea = bm.parse_gea_0x5d(params)
    # Conditional check
                if gea:
                    last_avrcp_rx_at = time.monotonic()
                    _resp, attrs = gea
                    print("[META] GetElementAttributes received:", sorted(attrs.keys()))
                    changed = []
    # Conditional check
                    if 1 in attrs:
                        meta_set("title", _sanitize_text(attrs[1]), changed)
    # Conditional check
                    if 2 in attrs:
                        meta_set("artist", _sanitize_text(attrs[2]), changed)
    # Conditional check
                    if 3 in attrs:
                        meta_set("album", _sanitize_text(attrs[3]), changed)
    # Conditional check
                    if 6 in attrs:
                        meta_set("genre", _sanitize_text(attrs[6]), changed)
    # Conditional check
                    if 4 in attrs:
                        meta_set("track_num", _sanitize_text(attrs[4], max_len=8), changed)
    # Conditional check
                    if 5 in attrs:
                        meta_set("total_tracks", _sanitize_text(attrs[5], max_len=8), changed)
    # Conditional check
                    if 7 in attrs:
                        ref_total_ms = last_total_ms if last_total_ms and last_total_ms > 0 else None
                        attr_time = _normalize_track_time_ms(attrs[7], ref_ms=ref_total_ms, from_attr=True)
                        if attr_time is not None and attr_time > 0:
                            if ref_total_ms is None or attr_time == ref_total_ms:
                                last_total_ms = attr_time
                                meta_set("time", _fmt_track_time_ms(attr_time), changed)
                            else:
                                dprint("[META] ignore duration attr", attrs[7], "baseline=", last_total_ms)
                    push_meta_updates(changed)

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
                if aux_mode:
                    print("[AUX] Ignoring BT_PLAY while AUX IN is active")
                else:
                    bm.play_pause()
    # Conditional check
            elif tok == b"BT_PREV":
                if aux_mode:
                    print("[AUX] Ignoring BT_PREV while AUX IN is active")
                else:
                    bm.prev()
    # Conditional check
            elif tok == b"BT_NEXT":
                if aux_mode:
                    print("[AUX] Ignoring BT_NEXT while AUX IN is active")
                else:
                    bm.next()
    # Conditional check
            elif tok == b"BT_EQ":
                mode = bm.next_eq()
                next_label = bm.EQ_L.get(mode, "OFF")
    # Conditional check
                if next_label != desired_eq:
                    desired_eq = next_label
                    print("[EQ] set to", desired_eq)
    # Conditional check
                    if nx.current_page is not None:
                        flush_page(nx.current_page)
    # Conditional check
            elif tok == b"BT_VOLUP_P":
                # Volume up pressed - send immediate volume up and start hold tracking
                ble_volume(True)
                vol_hold_active = "up"
                vol_hold_start_at = now
                vol_last_repeat_at = now
                vol_repeat_count = 1
            elif tok == b"BT_VOLUP_R":
                # Volume up released - stop hold-and-repeat
                if vol_hold_active == "up":
                    vol_hold_active = None
                    vol_repeat_count = 0
    # Conditional check
            elif tok == b"BT_VOLDN_P":
                # Volume down pressed - check for double-tap mute, then start hold tracking
    # Conditional check
                if (now - last_voldn_at) <= mute_window_s:
                    ble_mute()
                    last_voldn_at = 0.0
                    vol_hold_active = None  # Don't repeat after mute
                    vol_repeat_count = 0
                else:
                    ble_volume(False)
                    last_voldn_at = now
                    vol_hold_active = "down"
                    vol_hold_start_at = now
                    vol_last_repeat_at = now
                    vol_repeat_count = 1
            elif tok == b"BT_VOLDN_R":
                # Volume down released - stop hold-and-repeat
                if vol_hold_active == "down":
                    vol_hold_active = None
                    vol_repeat_count = 0
    # Conditional check
            elif tok == b"BT_EBIND":
                if (now - last_ebind_at) >= ebind_min_interval_s:
                    last_ebind_at = now
                    if ble_is_connected():
                        print("[BLE] erase-bonds denied while BLE connection is active")
                    elif ble_request_erase_bonds():
                        print("[BLE] erase-bonds requested")
                    else:
                        print("[BLE] erase-bonds request ignored (busy/cooldown)")
                    if ble_request_erase_bonds():
                        last_ebind_at = now
                        print("[BLE] erase-bonds requested")
                    else:
                        print("[BLE] erase-bonds request ignored (busy/cooldown)")
                else:
                    print("[BLE] erase-bonds request ignored (ui cooldown)")

# endregion
        # Handle volume hold-and-repeat
        if vol_hold_active is not None:
            # How long this button has been considered "held"
            hold_elapsed = now - vol_hold_start_at
            # Only start repeating after the initial delay has passed
            if hold_elapsed >= vol_initial_delay_s:
                # Safety cap: stop repeating after a maximum hold duration
                # This prevents a missed release token from causing unbounded repeats.
                if hold_elapsed > 2.0 or vol_repeat_count >= VOL_REPEAT_MAX:
                    vol_hold_active = None
                    vol_repeat_count = 0
                else:
                    # Check if it's time for another repeat step
                    if (now - vol_last_repeat_at) >= vol_repeat_interval_s:
                        if vol_hold_active == "up":
                            ble_volume(True)
                        elif vol_hold_active == "down":
                            ble_volume(False)
                        vol_last_repeat_at = now
                        vol_repeat_count += 1

        sleep(0.005)

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

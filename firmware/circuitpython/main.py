import gc
import time
import board
import busio

from utils.common import (
    TIME_UNKNOWN,
    dprint,
    _fmt_ms,
    _fmt_track_time_ms,
    _normalize_track_time_ms,
    _sanitize_text,
)
from nextion.display import Nextion, NX_RUNTIME, EQ_MAP, EQ_OBJ_PAGE0, EQ_OBJ_PAGE1, AUX_OBJ_PAGE0, AUX_OBJ_PAGE1
from bm83.bm83 import Bm83
from blehid.ble import BleHid

NX_BAUD = 9600
BM83_BAUD = 115200
NX_TX, NX_RX = board.IO15, board.IO16
BM83_TX, BM83_RX = board.IO17, board.IO18
# Hold-and-repeat caps. The count cap and the time cap below must agree —
# VOL_REPEAT_MAX counts the initial press, so 30 = initial + 29 repeats ×
# 0.20s = 0.85s + 5.80s = 6.65s (matches VOL_HOLD_MAX_S). Picking these from
# one end without the other was
# the bug that made the button "stop working" mid-hold pre-2026-05.
VOL_REPEAT_MAX = 30
VOL_HOLD_MAX_S = 6.65

# BLE HID Consumer Control. The phone sees this as a media remote and
# moves its OS volume slider in response to VOLUME_INCREMENT/DECREMENT.
# Used for the BT-streaming case; AUX-mode volume goes via BM83 MMI
# Line-In gain commands (0x82/0x83) since the phone isn't in the AUX
# signal path.
BLE_ENABLED = True
BLE_NAME = "B's Groovy BT CTRL"

# Experimental: automatic A2DP stream-restart kick after a BT reconnect
# (AVRCP pause -> 2.5s -> play at the first "playing" status). Hardware
# trial 2026-08-02: fired exactly as designed but did NOT un-mute the
# BM83's audio path, and the uninvited pause at every reconnect is a real
# UX cost — so it ships OFF. The muted-path wedge workaround remains
# manual for now: in the source app, pause, wait ~2s, play.
STREAM_KICK_ENABLED = False

def main():
    gc.collect()

    nx_uart = busio.UART(NX_TX, NX_RX, baudrate=NX_BAUD, timeout=0.0, receiver_buffer_size=1024)
    bm_uart = busio.UART(BM83_TX, BM83_RX, baudrate=BM83_BAUD, timeout=0.0, receiver_buffer_size=8192)

    nx = Nextion(nx_uart)
    bm = Bm83(bm_uart)
    bm.stream_kick_enabled = STREAM_KICK_ENABLED

    ble = BleHid(BLE_ENABLED, BLE_NAME)
    ble.setup()

    # Local bindings for speed/low allocation on mpy
    monotonic = time.monotonic
    sleep = time.sleep
    nx_tick = nx.tick
    nx_read = nx.read
    nx_set_text = nx.set_text_active_page
    bm_poll = bm.poll
    bm_ack = bm.ack_event
    bm_tick_power = bm.tick_power
    bm_tick_notif_regs = bm.tick_notif_regs
    bm_tick_stream_kick = bm.tick_stream_kick
    bm_tick_avrcp = bm.tick_avrcp
    bm_tick_avrcp_attrs = bm.tick_avrcp_attrs
    bm_tick_heartbeat = bm.tick_heartbeat
    bm_avrcp_get_play_status = bm.avrcp_get_play_status
    bm_volume_up = bm.volume_up
    bm_volume_down = bm.volume_down
    ble_tick = ble.tick
    ble_volume = ble.volume
    eq_labels = bm.EQ_L

    def volume_step(up):
        """Route a volume button press to the right backend.

        When the UI is in AUX mode, the phone is not in the signal
        path — only the BM83's Line_In gain matters.  Otherwise (A2DP
        streaming, or before we've seen a source event), send a BLE
        HID Consumer Control code so the phone's OS volume slider
        moves, matching the Flipper-Zero-style media-remote UX.

        Uses the same ``aux_mode`` flag that drives the Nextion AUX
        indicator so the volume backend always matches what the user
        sees on screen.
        """
        if aux_mode:
            if up:
                bm_volume_up()
            else:
                bm_volume_down()
        else:
            ble_volume(up)

    print("=== ESP32-S3 BM83 + Nextion + BLE HID (smart-routed volume) ===")

    nx.boot_sync(0.9)

    desired_eq = "OFF"
    desired_meta = {}
    for k in NX_RUNTIME.keys():
        desired_meta[k] = TIME_UNKNOWN if k in ("time_cur", "time") else "—"
    desired_aux = ""
    aux_mode = False
    aux_mode_prev = False
    avrcp_notifs_registered = False

    # AVRCP polling cadence while in AUX mode (no BT link). Probes GetPlayStatus
    # every few seconds to detect BT reconnecting without spamming the BM83.
    AVRCP_PROBE_PERIOD_S = 3.0
    next_avrcp_probe_at = 0.0
    # Retained for potential future features (e.g., UI "BT silent" indicator);
    # no longer gates aux_mode because an AVRCP-silence heuristic produces too
    # many false AUX flips during paused playback or play/pause transitions.
    last_avrcp_rx_at = 0.0
    last_pos_ms = None
    last_total_ms = None
    last_play_status = None

    # Hold-and-repeat state for volume controls
    vol_hold_active = None        # None, "up", or "down"
    vol_hold_start_at = 0.0       # When the button was first pressed
    vol_last_repeat_at = 0.0      # When we last sent a repeat
    vol_repeat_count = 0          # How many steps have been sent in this hold
    vol_initial_delay_s = 0.85    # 850ms before repeat starts
    vol_repeat_interval_s = 0.20  # 200ms between repeats (snappier than 350ms)

    # EBIND (bond-wipe) UI debounce. The Nextion touch panel can repeat
    # the BT_EBIND token if the user mashes the button or sits on it,
    # and request_erase_bonds() itself has only a 30s cooldown — too
    # coarse to swallow accidental double-taps cleanly. 2s here keeps
    # the human-intended single press while filtering touch chatter.
    ebind_min_interval_s = 2.0
    last_ebind_at = 0.0

    META_UPDATE_ORDER = ("title", "artist", "album", "genre", "track_num", "total_tracks", "time_cur", "time")
    TRACK_STALE_KEYS = ("album", "genre", "track_num", "total_tracks", "time_cur", "time")
    PLAYING_STATES = (0x01, 0x03, 0x04)
    # BTM_Status codes for link teardown / AVRCP re-establishment.
    # Datasheet AudioUARTCommandSet v2.09 §7.2 (p.169): 0x00 Power OFF,
    # 0x08 A2DP link disconnected, 0x0C AVRCP link disconnected,
    # 0x0F Standby, 0x11 ACL disconnected, 0x0B AVRCP link established.
    BTM_TEARDOWN_STATES = (0x00, 0x08, 0x0C, 0x0F, 0x11)
    BTM_AVRCP_LINK_UP = 0x0B

    def flush_page(pageid):
        if pageid == 0:
            nx_set_text(EQ_OBJ_PAGE0, desired_eq)
            nx_set_text(AUX_OBJ_PAGE0, desired_aux)
        elif pageid == 1:
            nx_set_text(EQ_OBJ_PAGE1, desired_eq)
            nx_set_text(AUX_OBJ_PAGE1, desired_aux)
            for k, obj in NX_RUNTIME.items():
                nx_set_text(obj, desired_meta.get(k, "—"))

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

    def maybe_track_changed(pos_ms, total_ms):
        nonlocal last_pos_ms, last_total_ms
        if pos_ms is None:
            last_pos_ms = pos_ms
            if total_ms is not None and total_ms > 0:
                last_total_ms = total_ms
            return False
        changed = False
        if total_ms is not None and total_ms > 0 and last_total_ms and last_total_ms > 0 and total_ms != last_total_ms:
            changed = True
        if last_pos_ms is not None and (pos_ms + 2500) < last_pos_ms and pos_ms < 3000:
            changed = True
        last_pos_ms = pos_ms
        if changed:
            last_total_ms = total_ms if total_ms is not None and total_ms > 0 else None
        elif total_ms is not None and total_ms > 0:
            last_total_ms = total_ms
        return changed

    def enter_aux_mode():
        nonlocal desired_aux, last_play_status, last_pos_ms, last_total_ms
        desired_aux = "AUX IN"
        invalidate_track_meta(clear_primary=True)
        last_play_status = None
        last_pos_ms = None
        last_total_ms = None

    def exit_aux_mode():
        nonlocal desired_aux
        desired_aux = ""
        bm.schedule_play_status(0.05)
        bm.schedule_attrs(0.3)

    last_gc = monotonic()
    gc_interval_s = 4.0  # Empirically chosen: 4s strikes a balance between GC overhead and memory pressure
    # On this workload (BM83 + Nextion event floods), 8s GC caused occasional alloc failures,
    # while <=2s GC increased pause time without reducing peak usage further. Tweak if patterns change.

    while True:
        now = monotonic()
        if now - last_gc > gc_interval_s:
            gc.collect()
            last_gc = now

        nx_tick()
        tokens, page_changed = nx_read()
        if page_changed and nx.current_page is not None:
            dprint("[NX] page=", nx.current_page)
            flush_page(nx.current_page)

        ble_tick()

        # UART RX heartbeat — self-throttled (~10s), surfaces BM83 freezes
        # and USB CDC drops in the log. Pass `now` so every ticker shares
        # the same time base and we don't pay an extra time.monotonic()
        # per main-loop iteration.
        bm_tick_heartbeat(now)

        # Tick non-blocking power state machine
        bm_tick_power()

        # Service deferred AVRCP notification registrations (see the
        # CONNECTED handler below for why these are staggered), and the
        # deferred PLAY half of the stream-restart kick.
        bm_tick_notif_regs(now)
        bm_tick_stream_kick(now)

        # aux_mode is driven by the BM83's own audio-source reporting.
        # Datasheet "AudioUARTCommandSet v2.09" 7.2 BTM_Status describes
        # states 0x80/0x81/0x82 = current audio source is (none / AUX / A2DP).
        # bm.should_show_aux() returns True iff the chip says AUX is active,
        # with a fall-back to the old "powered on and not linked" heuristic
        # for the window between boot and the first source event.
        aux_mode = bm.should_show_aux()

        if aux_mode != aux_mode_prev:
            aux_mode_prev = aux_mode
            if aux_mode:
                print("[AUX] inferred -> gating AVRCP polling, showing AUX indicators")
                enter_aux_mode()
                # Kick the BM83 audio routing only when a definite AUX source
                # transition was observed (audio_source == 0x81), not when
                # aux_mode was inferred from the fallback heuristic at boot.
                if bm.audio_source == bm.AUDIO_SRC_AUX:
                    bm.kick_aux_routing()
            else:
                print("[AUX] cleared -> enabling AVRCP polling, hiding AUX indicators")
                exit_aux_mode()
            # Refresh current page to update AUX indicator
            flush_page(nx.current_page)

        if not aux_mode:
            bm_tick_avrcp()
        else:
            # Probe/attrs only when the AVRCP session is actually up —
            # avrcp_suspended covers the teardown/re-establish window where
            # bm.connected is still True but commands would land on a dead
            # or half-established channel.
            if bm.connected and not bm.avrcp_suspended:
                if now >= next_avrcp_probe_at:
                    next_avrcp_probe_at = now + AVRCP_PROBE_PERIOD_S
                    bm_avrcp_get_play_status(0)
                bm_tick_avrcp_attrs()

        # Watchdog: if the BM83 has gone silent for a long time while we still
        # think we're connected, fall back to disconnected so the UI follows.
        if bm.check_connection_watchdog(now) == "DISCONNECTED":
            print("[BTM] disconnect debounce/watchdog -> marking DISCONNECTED")
            avrcp_notifs_registered = False
            last_play_status = None

        for op, params in bm_poll():
            bm_ack(op)
            if op == bm.EVT_BTM_STATUS and params:
                state = params[0]
                print("[BTM_Status] state=0x%02X" % state)
                change = bm.note_btm_state(state)
                # AVRCP notification registrations live on the AVRCP session,
                # not the BT bond: a quick BT off/on on the central tears the
                # session down and back up faster than the disconnect debounce
                # flips bm.connected, so `change` stays None and the old code
                # never re-registered — the new session then delivered no
                # PlaybackStatusChanged / TrackChanged events. Observed live
                # on b-intel 2026-08-02 (0x0C 0x08 0x11 0x0F 0x01 → 0x15 0x06
                # 0x0B with no re-registration). Clear the flag on teardown
                # states and re-arm when the AVRCP channel comes (back) up;
                # re-registering on a live session is harmless (TG replies
                # INTERIM again).
                if state in BTM_TEARDOWN_STATES and avrcp_notifs_registered:
                    print("[BTM] link teardown (0x%02X) -> will re-register on next AVRCP link" % state)
                    avrcp_notifs_registered = False
                if (change == "CONNECTED" or state == BTM_AVRCP_LINK_UP) and not avrcp_notifs_registered:
                    print("[BTM] Connected -> register notifications + request metadata")
                    # Stagger the initial registrations instead of sending all
                    # three back-to-back. Some BM83 firmware revs choke on
                    # rapid register-notification bursts during CT-side
                    # establishment and silently drop the A2DP profile while
                    # leaving the BT link up (same failure mode the
                    # reregister throttles in bm83.py guard against; this is
                    # the initial-burst counterpart). Suspected trigger for
                    # "first play after a fresh (re)connect stalls after a
                    # few seconds" on the Windows / Apple Music central.
                    bm.schedule_avrcp_notifications((
                        (0.25, 0x01, 0),   # PlaybackStatusChanged
                        (0.75, 0x02, 0),   # TrackChanged
                        (1.25, 0x05, 1),   # PlaybackPositionChanged, 1s interval
                    ))
                    bm.schedule_play_status(1.6)
                    bm.schedule_attrs(2.0)
                    avrcp_notifs_registered = True
                elif change == "DISCONNECTED":
                    avrcp_notifs_registered = False
                    last_play_status = None
            elif op == bm.EVT_EQ_MODE_IND and params:
                mode = params[0]
                if mode in bm.EQ_SEQ:
                    for i, value in enumerate(bm.EQ_SEQ):
                        if value == mode:
                            bm.eq_index = i
                            break
                desired_eq = eq_labels.get(mode, "OFF")
                dprint("[EQ_IND] mode=%d label=%s" % (mode, desired_eq))
                if nx.current_page is not None:
                    flush_page(nx.current_page)
            elif op == bm.EVT_AVC_VENDOR_RSP:
                parsed = bm.parse_avc_vendor_rsp(params)
                if not parsed:
                    continue
                _db, pdu, pkt_type, avp = parsed
                if pkt_type != 0x00:
                    continue
                last_avrcp_rx_at = time.monotonic()
                if pdu == 0x30 and len(avp) >= 9:
                    total_ms = _normalize_track_time_ms(int.from_bytes(avp[0:4], "big"))
                    pos_ms = _normalize_track_time_ms(int.from_bytes(avp[4:8], "big"))
                    last_play_status = avp[8]
                    if last_play_status in PLAYING_STATES:
                        # First "playing" after an AVRCP resume fires the
                        # one-shot muted-path stream kick (no-op otherwise).
                        bm.maybe_stream_kick()
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
                elif pdu == 0x31 and len(avp) >= 1:
                    event_id = avp[0]
                    if event_id == 0x01 and len(avp) >= 2:
                        # PlaybackStatusChanged: keep local status cache fresh
                        # between GetPlayStatus polling intervals.
                        prev_status = last_play_status
                        last_play_status = avp[1]
                        if last_play_status in PLAYING_STATES:
                            bm.maybe_stream_kick()
                        bm.avrcp_reregister_status_changed()
                        bm.schedule_play_status(0.05)
                        if last_play_status in PLAYING_STATES and (
                            primary_metadata_missing()
                            or (prev_status != last_play_status and desired_meta.get("time") == TIME_UNKNOWN)
                        ):
                            dprint("[META] playback start -> request metadata")
                            # 1.0s (was 0.15s): keep the heavyweight, often
                            # fragmented GetElementAttributes exchange out of
                            # the A2DP stream-start window. AVRCP churn right
                            # at stream start is the other suspected trigger
                            # for the first-play stall — the title just shows
                            # ~1s later, which the eye barely notices.
                            # Protect this as a hard floor: GetPlayStatus and
                            # TrackChanged handlers may also schedule metadata,
                            # but must not pull it back into stream startup.
                            bm.defer_attrs(1.0)
                            bm.schedule_attrs(1.0, force=True)
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
                        bm.avrcp_reregister_position_changed()
            elif op == bm.EVT_AVRCP_VENDOR_DEP_RSP:
                gea = bm.parse_gea_0x5d(params)
                if gea:
                    last_avrcp_rx_at = time.monotonic()
                    _resp, attrs = gea
                    print("[META] GetElementAttributes received:", sorted(attrs.keys()))
                    changed = []
                    if 1 in attrs:
                        meta_set("title", _sanitize_text(attrs[1]), changed)
                    if 2 in attrs:
                        meta_set("artist", _sanitize_text(attrs[2]), changed)
                    if 3 in attrs:
                        meta_set("album", _sanitize_text(attrs[3]), changed)
                    if 6 in attrs:
                        meta_set("genre", _sanitize_text(attrs[6]), changed)
                    if 4 in attrs:
                        meta_set("track_num", _sanitize_text(attrs[4], max_len=8), changed)
                    if 5 in attrs:
                        meta_set("total_tracks", _sanitize_text(attrs[5], max_len=8), changed)
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

        for tok in tokens:
            dprint("[NX] Token:", tok)
            if tok == b"BT_POWER":
                bm.power_toggle()
            elif tok == b"BT_POWEROFF":
                bm.power_off_cmd()
            elif tok == b"BT_PAIR":
                bm.pair()
            elif tok == b"BT_PLAY":
                if aux_mode:
                    print("[AUX] Ignoring BT_PLAY while AUX IN is active")
                else:
                    bm.play_pause()
            elif tok == b"BT_PREV":
                if aux_mode:
                    print("[AUX] Ignoring BT_PREV while AUX IN is active")
                else:
                    bm.prev()
            elif tok == b"BT_NEXT":
                if aux_mode:
                    print("[AUX] Ignoring BT_NEXT while AUX IN is active")
                else:
                    bm.next()
            elif tok == b"BT_EQ":
                mode = bm.next_eq()
                next_label = bm.EQ_L.get(mode, "OFF")
                if next_label != desired_eq:
                    desired_eq = next_label
                    print("[EQ] set to", desired_eq)
                    if nx.current_page is not None:
                        flush_page(nx.current_page)
            elif tok in EQ_MAP:
                # Direct EQ_* buttons are part of Nextion's accepted token
                # contract; dispatch them instead of silently swallowing them.
                mode = bm.set_eq(EQ_MAP[tok])
                if mode is not None:
                    next_label = bm.EQ_L.get(mode, "OFF")
                    if next_label != desired_eq:
                        desired_eq = next_label
                        print("[EQ] set to", desired_eq)
                        if nx.current_page is not None:
                            flush_page(nx.current_page)
            elif tok == b"BT_VOLUP_P":
                # Volume up pressed - smart-route to BLE HID (BT streaming)
                # or BM83 Line_In gain (AUX mode), then start hold tracking.
                volume_step(True)
                vol_hold_active = "up"
                vol_hold_start_at = now
                vol_last_repeat_at = now
                vol_repeat_count = 1
            elif tok == b"BT_VOLUP_R":
                # Volume up released - stop hold-and-repeat
                if vol_hold_active == "up":
                    vol_hold_active = None
                    vol_repeat_count = 0
            elif tok == b"BT_VOLDN_P":
                # Volume down pressed - smart-route and start hold tracking
                volume_step(False)
                vol_hold_active = "down"
                vol_hold_start_at = now
                vol_last_repeat_at = now
                vol_repeat_count = 1
            elif tok == b"BT_VOLDN_R":
                # Volume down released - stop hold-and-repeat
                if vol_hold_active == "down":
                    vol_hold_active = None
                    vol_repeat_count = 0
            elif tok == b"BT_VOLUP":
                # Legacy single-shot volume up (no press/release pair).
                volume_step(True)
            elif tok == b"BT_VOLDN":
                # Legacy single-shot volume down (no press/release pair).
                volume_step(False)
            elif tok == b"BT_EBIND":
                # Bond-store wipe. The heavy lifting (stop adv, GC,
                # settle, erase via adafruit_ble OR _bleio.adapter,
                # name-cycle to defeat Windows' cached-handle reconnect
                # loop, restart adv) lives in BleHid.request_erase_bonds
                # which defers execution to the disconnected window.
                # We refuse while a central is still connected because
                # erase_bonding under an active link is what destabilised
                # NimBLE in earlier hardware runs; the right flow is
                # Forget-Device-then-EBIND, not EBIND-then-disconnect.
                if (now - last_ebind_at) >= ebind_min_interval_s:
                    last_ebind_at = now
                    if ble.is_connected():
                        print("[BLE] EBIND denied: disconnect the central first "
                              "(Forget Device on phone / PC / Pi), then press EBIND.")
                    else:
                        ble.request_erase_bonds()
                # else: swallow Nextion touch chatter silently

        # Handle volume hold-and-repeat
        if vol_hold_active is not None:
            # How long this button has been considered "held"
            hold_elapsed = now - vol_hold_start_at
            # Only start repeating after the initial delay has passed
            if hold_elapsed >= vol_initial_delay_s:
                # Safety cap: stop repeating after a maximum hold duration.
                # VOL_HOLD_MAX_S and VOL_REPEAT_MAX are tuned to expire at
                # roughly the same moment — see top of file.
                if hold_elapsed > VOL_HOLD_MAX_S or vol_repeat_count >= VOL_REPEAT_MAX:
                    vol_hold_active = None
                    vol_repeat_count = 0
                else:
                    # Check if it's time for another repeat step
                    if (now - vol_last_repeat_at) >= vol_repeat_interval_s:
                        if vol_hold_active == "up":
                            volume_step(True)
                        elif vol_hold_active == "down":
                            volume_step(False)
                        vol_last_repeat_at = now
                        vol_repeat_count += 1

        sleep(0.005)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            import traceback
            print("[FATAL]", e)
            traceback.print_exception(e)
        except Exception:
            print("[FATAL]", e)
        while True:
            time.sleep(1)

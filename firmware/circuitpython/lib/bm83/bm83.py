import time
import gc
from utils.common import dprint
from utils import common as _utils_common
from utils.compat import const

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
class Bm83:
    __slots__ = (
        "uart",
        "_rx",
        "_rx_head",
        "_rx_max",
        "power_on",
        "eq_index",
        "connected",
        "_last_connected_seen",
        "_disconnect_hold_s",
        "_disconnect_deadline",
        "_next_playstatus_at",
        "_playstatus_period_s",
        "_next_attrs_at",
        "_attrs_not_before",
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
        "_last_status_changed_reg_at",
        "_status_reg_throttle_s",
        "_last_pos_changed_reg_at",
        "_pos_reg_throttle_s",
        "_pending_notif_regs",
        "_last_notif_reg_at",
        "_notif_reg_min_gap_s",
        "_avrcp_suspended",
        "_avrcp_suspend_at",
        "_avrcp_suspend_max_s",
        "_source_ever_seen",
        "_link_probe_at",
        "_link_probe_period_s",
        "_link_probe_misses",
        "_link_dead_warned",
        "_explicit_off",
        "_relinked",
        "_power_confirm_deadline",
        "_hb_idle_next_at",
        "_hb_idle_period_s",
        "_boot_init_at",
        "stream_kick_enabled",
        "_kick_armed",
        "_kick_state",
        "_kick_next_at",
        "_kick_gap_s",
        "_btm_silence_timeout_s",
        "audio_source",
        # UART RX heartbeat — used by tick_heartbeat() to surface freezes that
        # would otherwise be invisible (e.g. when serial console has died but
        # the display is still alive). _last_rx_byte_at is refreshed on every
        # non-empty UART read in poll(), independent of frame parsing.
        "_last_rx_byte_at",
        "_hb_next_at",
        "_hb_period_s",
        "_hb_silence_warn_s",
        # DEGRADED tier — gap is short enough that the radio is alive, but
        # long enough that traffic is later than the steady-state cadence
        # explains (see the threshold comment in __init__). We also
        # track the *max* gap seen during each heartbeat window so a brief
        # stall between 10s prints isn't lost to instantaneous sampling.
        "_hb_degraded_warn_s",
        "_hb_max_gap_window",
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

    EVT_CMD_ACK = const(0x00)
    EVT_BTM_STATUS = const(0x01)
    EVT_EQ_MODE_IND = const(0x10)
    EVT_AVC_VENDOR_RSP = const(0x1A)
    EVT_AVRCP_VENDOR_DEP_RSP = const(0x5D)

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

    MC_PLAY = const(0x05)
    MC_PAUSE = const(0x06)
    MC_PLAY_PAUSE = const(0x07)
    MC_NEXT = const(0x09)
    MC_PREV = const(0x0A)

    EQ_SEQ = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11)
    EQ_L = {
        0: "OFF", 1: "SOFT", 2: "BASS", 3: "TREBLE", 4: "CLASSICAL",
        5: "ROCK", 6: "JAZZ", 7: "POP", 8: "DANCE", 9: "RNB", 11: "USER"
    }
    EQ_LABELS = EQ_L  # Alias for test compatibility
    CONNECTED_STATES = (0x06, 0x0B, 0x82, 0x64, 0x65, 0x66)
    # BTM_Status codes that mean the AVRCP session (or the whole link) is
    # down: 0x00 Power OFF, 0x08 A2DP link disconnected,
    # 0x0C AVRCP link disconnected, 0x0F Standby, 0x11 ACL disconnected
    # (datasheet v2.09 §7.2, p.169). Seeing one of
    # these suspends AVRCP polling until a connected-state event arrives —
    # commands sent into a half-torn-down or half-established AVRCP channel
    # are the suspected trigger for the BM83 silently dropping A2DP
    # (observed live on the b-intel reconnect capture, 2026-08-02).
    AVRCP_DOWN_STATES = (0x00, 0x08, 0x0C, 0x0F, 0x11)
    # Hard link-down debounce is armed ONLY by ACL-level teardown codes.
    # Profile-level drops (0x08 A2DP disconnected, 0x0C AVRCP disconnected)
    # happen routinely while the ACL stays up — the source app releasing
    # A2DP when idle, or AUX taking over as the active source — and must
    # suspend AVRCP TX but never demote the link. Arming the debounce on
    # 0x08 caused the 2026-08-23 hardware regression: spurious firmware-side
    # disconnects during AUX sessions that wiped audio_source and flapped
    # aux_mode (repeated Line-In gain kicks -> gain pegged at max, beeps).
    LINK_DOWN_STATES = (0x00, 0x0F, 0x11)

    def __init__(self, uart=None):
        self.uart = uart
        # Head-index buffer: advance _rx_head past consumed bytes, compact
        # lazily. Avoids per-frame bytearray slice-reassignment on CP.
        self._rx = bytearray()
        self._rx_head = 0
        self._rx_max = 4096  # Max *active* (unconsumed) bytes before trim
        self.power_on = False
        self.eq_index = 0
        self.connected = False
        self._last_connected_seen = 0.0
        self._disconnect_hold_s = 2.0
        # Explicit teardown events arm this deadline. Unlike
        # _last_connected_seen it is not refreshed by unrelated AVRCP
        # traffic, so a final link-down event cannot leave connected=True.
        self._disconnect_deadline = 0.0
        self._next_playstatus_at = 0.0
        self._playstatus_period_s = 1.0
        self._next_attrs_at = 0.0
        # Hard floor used to protect the A2DP stream-start quiet window.
        # No metadata scheduler is allowed to pull a request before it.
        self._attrs_not_before = 0.0
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
        # PlaybackStatusChanged / PlaybackPositionChanged re-registration throttles.
        # Some BM83 firmware revs choke on rapid AVRCP register-notification calls
        # during CT-side establishment and silently drop the A2DP profile while
        # leaving the BT link nominally up. Tighter than TrackChanged (2.0 s) since
        # status/position re-arms fire more frequently in steady state.
        self._last_status_changed_reg_at = 0.0
        self._status_reg_throttle_s = 0.5
        self._last_pos_changed_reg_at = 0.0
        self._pos_reg_throttle_s = 0.5
        # Deferred AVRCP register-notification queue, serviced by
        # tick_notif_regs(). Filled by schedule_avrcp_notifications() at the
        # CONNECTED edge so the initial registrations go out spaced apart
        # instead of back-to-back — some BM83 firmware revs choke on rapid
        # register-notification bursts during CT-side establishment and
        # silently drop the A2DP profile while leaving the BT link up (the
        # reregister throttles above exist for the same reason; this applies
        # the same medicine to the *initial* burst on connect).
        self._pending_notif_regs = []
        self._last_notif_reg_at = 0.0
        self._notif_reg_min_gap_s = 0.45
        # True while a teardown state (AVRCP_DOWN_STATES) has been seen and
        # no connected state has arrived since. Gates tick_avrcp /
        # tick_avrcp_attrs / tick_notif_regs so we stop sending AVRCP
        # commands into a dead or re-establishing session — the quick
        # BT off/on reconnect path where the disconnect debounce keeps
        # self.connected True throughout. Cleared with a settle grace in
        # note_btm_state when a connected state returns.
        self._avrcp_suspended = False
        # Bound the suspension. A profile-level blip (0x08/0x0C) suspends AVRCP
        # TX, but if the chip never emits another connected-state event the
        # suspension used to last forever: polling stopped, metadata froze, and
        # with no inbound traffic the silence watchdog eventually demoted a
        # perfectly healthy link. Auto-resume after this long.
        self._avrcp_suspend_at = 0.0
        self._avrcp_suspend_max_s = 6.0
        # True once ANY audio-source event (0x80/0x81/0x82) has been observed.
        # should_show_aux()'s link-state fallback is a BOOT-WINDOW heuristic
        # only; without this flag, _mark_disconnected() clearing audio_source
        # re-created the "never seen a source" condition, and the fallback then
        # asserted AUX in the middle of live A2DP playback (2026-08-26 field
        # failure: phantom AUX IN, metadata cleared, transport controls dead).
        self._source_ever_seen = False
        # Recovery probe. Once `connected` is False nothing polls the chip, so
        # a FALSE disconnect could never heal itself — the firmware sat in
        # phantom-AUX until a reboot. Probe gently while powered but unlinked.
        self._link_probe_at = 0.0
        self._link_probe_period_s = 5.0
        # Consecutive probes with no reply of any kind. The datasheet (§4.5.1)
        # requires the BM83 to ACK every command within 200ms, so sustained
        # silence means the module is off, asleep, or unwired — a condition
        # the firmware previously could not distinguish from "idle".
        self._link_probe_misses = 0
        self._link_dead_warned = False
        # True from an explicit host-commanded power-off until the chip is seen
        # running again. Without it, the recovery probe fires immediately after
        # power_off_cmd() and a late ACK / shutdown-time reply is mistaken for
        # "the module is powered", so power_on flips back to True and the next
        # BT_POWER press sends OFF again instead of ON.
        self._explicit_off = False
        # Set when poll() proves a live AVRCP session while we believed the link
        # was down. main.py consumes it and re-arms the session-scoped AVRCP
        # registrations: this recovery path bypasses note_btm_state(), so
        # without it a healed session would never register PlaybackStatus /
        # TrackChanged / Position notifications and metadata would stay frozen.
        self._relinked = False
        # Non-zero while a host-commanded power-ON awaits confirmation from
        # the chip's own reporting. The old code set power_on=True the moment
        # the press/release sequence finished, purely on faith; whenever the
        # chip failed to complete power-up (LEDs flash, then silence) the
        # toggle went out of phase with reality and the next BT_POWER press
        # sent power-OFF to an off module. Field report 2026-08-29: "several
        # attempts / double tapping on" required. power_on now flips True
        # only on chip evidence; if this deadline expires silent, the belief
        # reverts and the next press retries ON — in phase.
        self._power_confirm_deadline = 0.0
        # Idle heartbeat cadence. Never go completely silent: a board printing
        # nothing at all is indistinguishable from a crashed one (that cost
        # ~20 min of misdiagnosis on 2026-08-26).
        self._hb_idle_next_at = 0.0
        self._hb_idle_period_s = 30.0
        # One-shot boot handshake. The ESP32 reboots far more often than the
        # BM83 does (USB auto-reload, code edits, resets) and the chip keeps
        # running across those reboots. Without re-sending the event-mask
        # setup, a chip that is powered, linked and streaming can sit there
        # reporting NOTHING to the host MCU: the firmware then shows no
        # metadata, no link state, and every transport control is a no-op
        # while audio keeps playing. Fires ~1.5s after boot (settle first).
        self._boot_init_at = time.monotonic() + 1.5
        # A2DP stream-restart kick. After a link bounce the BM83's audio
        # path can come back MUTED while it still reports source=A2DP and
        # AVRCP works fine — observed live 2026-08-02 on b-intel: app
        # playing, metadata/track time updating on the display, zero sound,
        # chip pinned at 0x82 the whole time. The only recovery that works
        # is a clean source-side stream restart with a real gap (manual
        # pause → ~2s → play; a QUICK pause/play does NOT recover it — the
        # gap is the active ingredient). This one-shot state machine
        # automates that: armed when AVRCP resumes after a suspension,
        # fired at the first "playing" status via maybe_stream_kick():
        # AVRCP PAUSE, wait _kick_gap_s, AVRCP PLAY (datasheet §5.2.4
        # Music_Control actions 0x06/0x05).
        #
        # DISABLED BY DEFAULT after the 2026-08-02 hardware trial: the kick
        # executed exactly as designed (serial log: pause sent at first
        # playing, play sent 2.5s later) but did NOT un-mute the audio
        # path — sink-initiated AVRCP pause/play is evidently not
        # equivalent to the manual app-side pause → 2s → play that does
        # recover it. Until a working chip-side re-engage is found, the
        # uninvited pause at every reconnect isn't worth it. main.py can
        # opt back in via STREAM_KICK_ENABLED.
        self.stream_kick_enabled = False
        self._kick_armed = False
        self._kick_state = None     # None, or "paused" while waiting to send PLAY
        self._kick_next_at = 0.0
        self._kick_gap_s = 2.5
        # If no BTM_Status (or other connection-refreshing event) arrives for this
        # many seconds while we think we're connected, assume the radio went silent
        # and flip to disconnected. The AVRCP-silence heuristic in main.py alone
        # can't clear self.connected, so without this the state sticks forever.
        # Bumped from 30.0s to 90.0s: paused playback on some BM83 firmwares emits
        # no BTM_Status / AVRCP traffic for minutes at a time. The new value still
        # trips on a hung radio (crash, brown-out, UART wedge) but tolerates idle
        # pauses without falsely demoting self.connected.
        self._btm_silence_timeout_s = 90.0

        # Current audio source reported by BTM_Status (state 0x80/0x81/0x82).
        # None until the first source event arrives. 0x81 means AUX jack is the
        # active source; UI gates "AUX IN" indicators on this. See AUDIO_SRC_*
        # constants and should_show_aux().
        self.audio_source = None

        # UART RX heartbeat. tick_heartbeat() prints periodic status so a
        # silent BM83 link is visible in the log immediately, instead of being
        # inferred only from missing BTM_Status events. Initialised to "now"
        # at boot so the first silence window is measured from boot, not from
        # the epoch.
        now = time.monotonic()
        self._last_rx_byte_at = now
        self._hb_next_at = now + 10.0   # First heartbeat 10s after boot
        self._hb_period_s = 10.0        # Print state at most every 10s
        self._hb_silence_warn_s = 3.0   # Mark RX as SILENT after this gap
        # DEGRADED threshold. Must sit ABOVE the steady-state traffic
        # cadence: while connected we poll GetPlayStatus once per second
        # (_playstatus_period_s), so a healthy window's max inter-byte gap
        # is ~1.0s by construction. The original 0.2s threshold predated
        # the 1 Hz poll and flagged every healthy playback window as
        # DEGRADED (observed on hardware 2026-08-02). 1.4s = poll period
        # + 0.4s grace; a genuinely late response still trips this well
        # before the 3.0s SILENT tier.
        self._hb_degraded_warn_s = 1.4  # Mark RX as DEGRADED after this gap
        self._hb_max_gap_window = 0.0   # Max inter-byte gap in current window

    @property
    def avrcp_suspended(self):
        """True while AVRCP traffic is paused during a link teardown/re-establish window."""
        return self._avrcp_suspended

    @property
    def last_rx_at(self):
        """Timestamp (time.monotonic) of the most recent BM83 UART RX byte.

        Used by BleHid to gate c.pair() on a BM83-quiet window. Calling
        c.pair() while the BM83 UART is mid-AVRCP-handshake has been
        observed to hard-crash NimBLE on ESP32-S3, so the BLE module
        waits for `now - bm.last_rx_at` to exceed a small threshold
        before driving pairing from the peripheral side.
        """
        return self._last_rx_byte_at

    @staticmethod
    def _checksum(hi, lo, body):
        return (-((hi + lo + sum(body)) & 0xFF)) & 0xFF

    @staticmethod
    def _checksum_range(hi, lo, buf, start, end):
        """Checksum buf[start:end] via memoryview (no allocation on CP)."""
        view = memoryview(buf)[start:end]
        return (-((hi + lo + sum(view)) & 0xFF)) & 0xFF

    def _frame(self, op, params=b""):
        body = bytes([op]) + params
        ln = len(body)
        hi, lo = (ln >> 8) & 0xFF, ln & 0xFF
        chk = self._checksum(hi, lo, body)
        return bytes([0xAA, hi, lo]) + body + bytes([chk])

    # Public alias for testing
    def frame(self, op, params=b""):
        return self._frame(op, params)

    def _checksum_valid(self, body_with_checksum):
        if len(body_with_checksum) < 2:
            return False
        body = body_with_checksum[:-1]
        chk = body_with_checksum[-1]
        ln = len(body)
        hi, lo = (ln >> 8) & 0xFF, ln & 0xFF
        expected = self._checksum(hi, lo, body)
        return chk == expected

    def send(self, op, params=b""):
        pkt = self._frame(op, params)
        # Avoid hex formatting when DEBUG is off (hot path, allocates)
        if _utils_common.DEBUG:
            dprint("[BM83 TX]", " ".join("%02X" % b for b in pkt))
        try:
            self.uart.write(pkt)
        except Exception as e:
            print("[BM83] write err:", e)

    def ack_event(self, event_op):
        if event_op == 0x00:
            return
        self.send(self.OP_EVENT_ACK, bytes([event_op & 0xFF]))

    def poll(self, max_read=768, max_events=8):
        """Drain UART, return up to max_events parsed (op, params) tuples.

        Uses _rx_head index to avoid per-frame bytearray reallocation.
        """
        out = []
        try:
            n = getattr(self.uart, "in_waiting", 0) or 0
            chunk = self.uart.read(min(max_read, n)) if n else None
        except Exception as e:
            dprint("[BM83] read err:", e)
            return out
        if chunk:
            self._rx.extend(chunk)
            _now = time.monotonic()
            _gap_since_last = _now - self._last_rx_byte_at
            if _gap_since_last > self._hb_max_gap_window:
                self._hb_max_gap_window = _gap_since_last
            self._last_rx_byte_at = _now

        rx = self._rx
        head = self._rx_head
        active = len(rx) - head
        if active > self._rx_max:
            keep = 256
            dprint("[BM83] buffer overflow, trimming head, keeping", keep, "bytes")
            self._rx = bytearray(rx[-keep:])
            rx = self._rx
            head = 0

        while len(out) < max_events:
            if (len(rx) - head) < 4:
                break
            sof = rx.find(b"\xAA", head)
            if sof < 0:
                head = len(rx)
                break
            if sof > head:
                head = sof
            if (len(rx) - head) < 4:
                break
            hi, lo = rx[head + 1], rx[head + 2]
            ln = (hi << 8) | lo
            # A valid BM83 body always contains at least the opcode, and
            # cannot be larger than the active RX buffer we are willing to
            # retain. Reject impossible lengths immediately so one noisy
            # 0xAA FF FF prefix cannot wedge parsing until buffer overflow.
            if ln < 1 or ln > self._rx_max:
                dprint("[BM83] invalid frame length", ln, "-> resync")
                head += 1
                continue
            total = 3 + ln + 1
            if (len(rx) - head) < total:
                break
            body_start = head + 3
            body_end = body_start + ln
            chk = rx[body_end]
            if chk != self._checksum_range(hi, lo, rx, body_start, body_end):
                head += 1
                continue
            op = rx[body_start]
            params = bytes(rx[body_start + 1 : body_end])
            if _utils_common.DEBUG:
                dprint("[BM83 EVT] op=0x%02X len=%d data=" % (op, len(params)),
                       " ".join("%02X" % b for b in params))
            out.append((op, params))
            if self.connected and op != self.EVT_BTM_STATUS:
                # NB: BTM_Status is deliberately excluded — stamping it here
                # would make note_btm_state's _disconnect_hold_s check
                # always-false and a real teardown event could never demote
                # the link. Radio liveness for the silence watchdog comes from
                # _last_rx_byte_at instead (see check_connection_watchdog).
                self._last_connected_seen = time.monotonic()
            if not self.connected:
                # A non-ACK frame proves the module's BT stack is running --
                # unless we just commanded it off, in which case this is
                # shutdown-time chatter and must not resurrect power_on.
                # Command_ACKs are deliberately excluded: the BM83's UART
                # front-end ACKs commands even from soft-off (hardware-
                # captured 2026-08-29 -- the power-on press ACK arrived at
                # +0.02s, before the chip could possibly have booted). In a
                # failed boot (LEDs light, then silence) the init_link ACKs
                # would otherwise "confirm" a dead chip, pin power_on=True,
                # and re-invert the BT_POWER toggle -- the original field bug.
                if (not self._explicit_off) and op != self.EVT_CMD_ACK:
                    if self._power_confirm_deadline:
                        self._power_confirm_deadline = 0.0
                        print("[POWER] ON confirmed by chip reporting")
                    self.power_on = True
                self._link_probe_misses = 0
                if self._link_dead_warned:
                    self._link_dead_warned = False
                    print("[BM83] responding again")
            if (not self.connected) and (not self._explicit_off) and op in (
                    self.EVT_AVC_VENDOR_RSP, self.EVT_AVRCP_VENDOR_DEP_RSP):
                # NB: gated on _explicit_off too (Copilot + Codex, PR #133):
                # an AVRCP response arriving as shutdown-time chatter must not
                # fake a session recovery — it would re-arm registrations into
                # a dying module and leave avrcp_notifs_registered=True for a
                # dead session, so the next real 0x0B would skip re-arming.
                # Positive proof of a live AVRCP session while we believed the
                # link was down: a false disconnect. Heal instead of waiting
                # for a spontaneous BTM_Status that may never come.
                self.connected = True
                self._disconnect_deadline = 0.0
                self._last_connected_seen = time.monotonic()
                # Tell main.py to re-arm the session-scoped registrations: this
                # path never produces note_btm_state()'s "CONNECTED" edge, and
                # in the silent-BTM case it is meant to recover no later 0x0B
                # may ever arrive.
                self._relinked = True
                print("[BTM] AVRCP traffic while disconnected -> relinking")
            head = body_end + 1

        # Compact lazily once head has consumed enough to be worth shifting.
        if head >= 256 and head >= (len(rx) - head):
            self._rx = bytearray(rx[head:])
            rx = self._rx
            head = 0
        self._rx_head = head
        return out

    def tick_heartbeat(self, now=None):
    # tick_heartbeat prints a periodic line so a wedged BM83 UART RX shows
    # up in the log within a few seconds, instead of being inferred silently
    # from missing BTM_Status events. Safe to call every loop iteration —
    # it self-throttles to _hb_period_s.
        if now is None:
            now = time.monotonic()
        if now < self._hb_next_at:
            return
        self._hb_next_at = now + self._hb_period_s
        instantaneous_gap = now - self._last_rx_byte_at
        # effective_gap = max of (current silence, largest stall seen in
        # window). This catches brief degradations that recover before the
        # next 10s print would otherwise sample them as "healthy".
        window_max = self._hb_max_gap_window
        effective_gap = instantaneous_gap if instantaneous_gap > window_max else window_max
        # Reset window tracker for the next heartbeat period.
        self._hb_max_gap_window = 0.0
        # gc.mem_free() is a fast inspection on CircuitPython (no collect),
        # safe to call every heartbeat. Trending toward 0 over time = leak.
        try:
            free = gc.mem_free()
        except Exception:
            free = -1
        # Gate SILENT on *instantaneous* gap, not effective_gap. A single
        # transient stall earlier in the window (e.g., boot -> first RX,
        # or a 4s AVRCP lull that already recovered) would otherwise
        # produce a misleading "SILENT" line while bytes are actively
        # flowing now. window_max is still included in the message for
        # context when it exceeds the instantaneous reading.
        # SILENT/DEGRADED only meaningful when connected. Otherwise idle
        # silence is normal — demote to dprint so DEBUG=True still shows it.
        if instantaneous_gap >= self._hb_silence_warn_s:
            if self.connected:
                if window_max > instantaneous_gap:
                    print("[BM83 RX] SILENT for %.1fs (window max %.2fs) | free=%d"
                          % (instantaneous_gap, window_max, free))
                else:
                    print("[BM83 RX] SILENT for %.1fs | free=%d"
                          % (instantaneous_gap, free))
            else:
                self._print_idle_hb(now, "idle, RX silent %.1fs" % instantaneous_gap, free)
        elif effective_gap >= self._hb_degraded_warn_s:
            if self.connected:
                print("[BM83 RX] DEGRADED: max %.2fs in last %.0fs window (now %.2fs) | free=%d"
                      % (effective_gap, self._hb_period_s, instantaneous_gap, free))
            else:
                self._print_idle_hb(
                    now, "idle, max gap %.2fs" % effective_gap, free)
        else:
            # Also print during healthy operation so "log went silent" is
            # itself a diagnostic signal (serial CDC dropped, not radio).
            print("[BM83 RX] alive: %.2fs since last byte | free=%d" % (instantaneous_gap, free))

    def _print_idle_hb(self, now, detail, free):
        """Low-rate liveness line for the disconnected/idle case.

        Idle silence is normal and must not spam every 10s, but going
        COMPLETELY quiet is worse: a board printing nothing is
        indistinguishable from a crashed one over a serial console. Print a
        compact line every _hb_idle_period_s so absence of output always
        means something is actually wrong.
        """
        if now < self._hb_idle_next_at:
            return
        self._hb_idle_next_at = now + self._hb_idle_period_s
        print("[BM83 RX] %s | power_on=%d src=%s aux=%d | free=%d"
              % (detail, 1 if self.power_on else 0,
                 "--" if self.audio_source is None else "%02X" % self.audio_source,
                 1 if self.should_show_aux() else 0, free))

    def tick_boot_init(self, now=None):
        """Send the one-shot boot handshake once the radio has settled."""
        if self._boot_init_at == 0.0:
            return False
        if self._power_state is not None:
            # Defer (do not cancel) while a power press/release is mid-flight.
            return False
        if now is None:
            now = time.monotonic()
        if now < self._boot_init_at:
            return False
        self._boot_init_at = 0.0
        print("[BM83] boot handshake -> enabling event reporting")
        self.init_link()
        return True

    def init_link(self):
        self.send(self.OP_READ_BD_ADDR)
        self.send(self.OP_EVENT_FILTER, b"\x00\x00\x00\x00")
        self.send(self.OP_BTM_UTILITY_FUNC, b"\x03\x01")
        print("[BM83] Link initialized")

    def power_on_cmd(self):
        """Begin the non-blocking power-on sequence (press now, release via tick_power())."""
        # Ignore if state machine already in progress to prevent inconsistent state
        if self._power_state is not None or self._power_confirm_deadline:
            return
        now = time.monotonic()
        self._power_state = "on_press"
        self._explicit_off = False
        self._power_next_at = now + 0.2  # Wait 0.2s before sending release
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_POWER_ON_PRESS]))

    def power_off_cmd(self):
        """Begin the non-blocking power-off sequence (press now, release via tick_power())."""
        # Ignore if state machine already in progress to prevent inconsistent state
        if self._power_state is not None or self._power_confirm_deadline:
            return
        now = time.monotonic()
        self._power_state = "off_press"
        self._power_next_at = now + 1.5  # Wait 1.5s before sending release
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_POWER_OFF_PRESS]))

    def tick_power(self):
        """Advance the non-blocking power press/release state machine."""
        # Service the ON-confirmation deadline even when no press is active.
        if self._power_confirm_deadline:
            _now = time.monotonic()
            if _now >= self._power_confirm_deadline:
                self._power_confirm_deadline = 0.0
                if not self.power_on:
                    print("[POWER] ON not confirmed - chip stayed silent.")
                    print("        Check module power; press BT_POWER to retry.")
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
            # Do NOT claim power_on yet — wait for the chip's own reporting
            # (any BTM_Status or inbound frame clears this deadline via the
            # normal inference paths). See _power_confirm_deadline.
            self._power_confirm_deadline = now + 6.0
            self._power_state = None
            print("[POWER] ON requested (awaiting chip confirmation)")
        elif self._power_state == "off_press":
            # 1.5s elapsed since press, now send release
            self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_POWER_OFF_RELEASE]))
            self.power_on = False
            # Latch the intent so neither the recovery probe nor frame-based
            # power inference can resurrect power_on while the chip shuts down.
            self._explicit_off = True
            self._mark_disconnected()
            self._power_state = None
            print("[POWER] OFF (UART)")

    def power_toggle(self):
        self.power_off_cmd() if self.power_on else self.power_on_cmd()

    def pair(self):
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_ENTER_PAIRING]))
        print("[PAIR] Enter pairing")

    def play_pause(self):
        # Guard: MC_PLAY_PAUSE is an AVRCP transport command. Sending it
        # while the BM83 is routing AUX IN (audio_source == 0x81) nudges
        # the chip's source state machine toward A2DP and interrupts
        # Line-In audio. main.py's aux_mode gate covers the steady state,
        # but this guard closes the race window between a fresh AUX
        # plug-in and the first 0x81 BTM_Status — during which main.py
        # still thinks we're in A2DP mode but the chip is playing Line-In.
        # Deliberately narrow: AUDIO_SRC_NONE and unknown (None) are left
        # as pass-through so that pressing Play from an idle state can
        # still kick A2DP resume, which is the common "resume playback"
        # intent.
        if self.audio_source == self.AUDIO_SRC_AUX:
            print("[PLAY/PAUSE] suppressed (AUX source active)")
            return
        self.send(self.OP_MUSIC_CONTROL, bytes([0x00, self.MC_PLAY_PAUSE]))
        print("[PLAY/PAUSE] toggled")

    def prev(self):
        self.send(self.OP_MUSIC_CONTROL, bytes([0x00, self.MC_PREV]))
        print("[PREV] triggered")

    def next(self):
        self.send(self.OP_MUSIC_CONTROL, bytes([0x00, self.MC_NEXT]))
        print("[NEXT] triggered")

    def maybe_stream_kick(self):
        """Fire the one-shot A2DP stream-restart kick if armed.

        Call whenever a "playing" play-status is observed. No-op unless the
        kick was armed by an AVRCP resume (see note_btm_state). Sends AVRCP
        PAUSE now; tick_stream_kick() sends PLAY after _kick_gap_s. The gap
        matters: a quick pause/play does not re-engage the BM83's muted
        audio path, a ~2s+ gap does (hardware-observed 2026-08-02).
        """
        if (not self._kick_armed) or (self._kick_state is not None):
            return False
        if self.audio_source == self.AUDIO_SRC_AUX:
            # AUX routing active — never inject AVRCP transport commands
            # (same rationale as the play_pause() guard).
            return False
        self._kick_armed = False
        self._kick_state = "paused"
        self._kick_next_at = time.monotonic() + self._kick_gap_s
        self.send(self.OP_MUSIC_CONTROL, bytes([0x00, self.MC_PAUSE]))
        print("[KICK] stream restart: pause sent, play in %.1fs" % self._kick_gap_s)
        return True

    def tick_stream_kick(self, now=None):
        """Send the deferred PLAY half of the stream kick when due."""
        if self._kick_state is None:
            return
        if now is None:
            now = time.monotonic()
        if now < self._kick_next_at:
            return
        self._kick_state = None
        if (not self.connected) or self._avrcp_suspended:
            print("[KICK] aborted (link state changed)")
            return
        self.send(self.OP_MUSIC_CONTROL, bytes([0x00, self.MC_PLAY]))
        print("[KICK] stream restart: play sent")

    def set_eq(self, mode):
        """Set one explicit EQ preset; return None when invalid or throttled."""
        if mode not in self.EQ_SEQ:
            return None
        now = time.monotonic()
        if (now - self._last_eq_cmd_at) < self._eq_throttle_s:
            return None
        self._last_eq_cmd_at = now
        for i, value in enumerate(self.EQ_SEQ):
            if value == mode:
                self.eq_index = i
                break
        self.send(self.OP_EQ_MODE_SETTING, bytes([mode, 0x00]))
        return mode

    def next_eq(self):
        """Advance to the next EQ preset; throttled to avoid UART command floods."""
        mode = self.EQ_SEQ[(self.eq_index + 1) % len(self.EQ_SEQ)]
        sent = self.set_eq(mode)
        # Preserve the existing API: a throttled next_eq() reports the actual
        # current mode rather than pretending the requested step occurred.
        return self.EQ_SEQ[self.eq_index] if sent is None else sent

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

    def _mark_disconnected(self):
        """Clear session-scoped state and return the public transition marker."""
        self.connected = False
        self._disconnect_deadline = 0.0
        # Clear the cached source ONLY when it is not live AUX. The clear
        # exists for the stale-0x82 case (should_show_aux() must fall back
        # to the link-state heuristic after a BT drop); a live 0x81 must
        # survive a firmware-side disconnect because the chip will not
        # re-announce it — clearing it made the AUX indicator vanish and
        # re-triggered kick_aux_routing()'s gain step on every flap.
        if self.audio_source != self.AUDIO_SRC_AUX:
            self.audio_source = None
        self._kick_armed = False
        self._kick_state = None
        self._pending_notif_regs = []
        self._next_attrs_at = 0.0
        self._attrs_not_before = 0.0
        return "DISCONNECTED"

    def note_btm_state(self, state):
        now = time.monotonic()
        # The chip talking at all proves it is powered. `power_on` used to
        # track only whether WE had powered it, so after an ESP32-only reboot
        # it stayed False against a live, streaming module — and
        # should_show_aux()/tick_link_recovery() both gate on it, leaving the
        # UI inert. Trust the chip's own reporting instead.
        if state == 0x00:
            self.power_on = False
            self._explicit_off = True
        else:
            # Authoritative: the chip is demonstrably running (this also covers
            # the user powering it back on with the module's own button).
            if self._power_confirm_deadline:
                self._power_confirm_deadline = 0.0
                print("[POWER] ON confirmed by chip reporting")
            self.power_on = True
            self._explicit_off = False
        # Audio-source tracking. States 0x80/0x81/0x82 report which audio
        # source the BM83 is currently routing (none / AUX / A2DP). They are
        # orthogonal to link-state codes like 0x06 (A2DP link established),
        # so we record them separately. If a firmware value overlaps with a
        # connected-state code (for example 0x82 on some firmware builds),
        # keep tracking the source but do not return early before the
        # connection-state update runs.
        is_audio_src_state = state in self.AUDIO_SRC_STATES
        if is_audio_src_state:
            self.audio_source = state
            # Latch: the boot-window fallback in should_show_aux() must never
            # re-engage after we have had real source reporting.
            self._source_ever_seen = True
            if state not in self.CONNECTED_STATES:
                return None
        # AVRCP session suspend/resume. A quick BT off/on on the central
        # tears the session down and back up faster than the disconnect
        # debounce below flips self.connected, so without this gate the
        # 1 Hz GetPlayStatus polling keeps firing straight through AVRCP
        # re-establishment — commands landing on a half-established channel
        # are the suspected trigger for the BM83 silently dropping A2DP at
        # the first play after reconnect (b-intel capture, 2026-08-02:
        # 0x0C 0x08 0x11 0x0F 0x01 then 0x15 0x06 0x0B).
        if state in self.AVRCP_DOWN_STATES:
            if not self._avrcp_suspended:
                self._avrcp_suspended = True
                # Registrations queued for the old session are meaningless
                # now; main.py re-arms a fresh staggered set on 0x0B. An
                # in-flight stream kick is aborted too — never send its
                # PLAY into a dead link.
                self._avrcp_suspend_at = now
                print("[BTM] AVRCP down (0x%02X) -> pausing AVRCP polling" % state)
            # Session-scoped work is invalid on every teardown indication,
            # even when an earlier teardown code already set the suspend flag.
            self._pending_notif_regs = []
            self._next_attrs_at = 0.0
            self._attrs_not_before = 0.0
            self._kick_state = None
            # Arm once at the first ACL-level teardown event. Later teardown
            # chatter must not keep pushing the debounce window forward, and
            # profile-level drops (0x08/0x0C) never arm it — see
            # LINK_DOWN_STATES.
            if (
                self.connected
                and self._disconnect_deadline == 0.0
                and state in self.LINK_DOWN_STATES
            ):
                self._disconnect_deadline = now + self._disconnect_hold_s
        if state in self.CONNECTED_STATES:
            self._disconnect_deadline = 0.0
            self._last_connected_seen = now
            self._hb_idle_next_at = 0.0
            if self._avrcp_suspended:
                self._avrcp_suspended = False
                # Resume only after the link settles; polling the instant
                # the channel reappears is the burst we're avoiding. If the
                # experimental stream kick is enabled, arm it: the first
                # play after a link bounce is where the muted-path wedge
                # lives.
                self._next_playstatus_at = now + 1.5
                if self.stream_kick_enabled:
                    self._kick_armed = True
                    print("[BTM] AVRCP link back -> resume polling in 1.5s, stream kick armed")
                else:
                    print("[BTM] AVRCP link back -> resume polling in 1.5s")
            if not self.connected:
                self.connected = True
                return "CONNECTED"
            return None
        if self.connected and (now - self._last_connected_seen) > self._disconnect_hold_s:
            # Preserve the legacy "stale then teardown event" fast path.
            return self._mark_disconnected()
        return None

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
        # audio_source is None here. That means one of two very different
        # things, and conflating them was the 2026-08-26 field failure:
        #
        #   a) We have never seen a source event (fresh boot). The old
        #      link-state heuristic is a reasonable guess: no BT link on a
        #      powered unit usually does mean the user is on the AUX jack.
        #   b) We HAD source reporting and _mark_disconnected() cleared it.
        #      Here "not connected" is NOT evidence of AUX — and asserting
        #      AUX mid-A2DP wipes the metadata and disables every transport
        #      control while the phone/PC keeps happily streaming.
        #
        # Only (a) may use the heuristic. In (b) we require positive evidence
        # (a real 0x81) before claiming AUX.
        if self._source_ever_seen:
            return False
        return not self.connected

    def check_connection_watchdog(self, now=None):
        """Return "DISCONNECTED" if the BM83 has gone completely silent.

        ``_last_connected_seen`` is refreshed on successful inbound non-BTM
        frames in ``poll()`` while ``self.connected`` is True (for example,
        AVRCP notifications, metadata responses, and play-status replies).
        Connected-state BTM_Status events refresh it via ``note_btm_state()``.
        This watchdog only trips when the radio emits nothing at all for
        ``_btm_silence_timeout_s`` (e.g., crash, brown-out, UART wedged).
        Steady-state playback that triggers only AVRCP traffic (no BTM state
        transitions) must NOT trip this, otherwise the UI will flap into AUX.
        """
        if not self.connected:
            return None
        if now is None:
            now = time.monotonic()
        # Explicit teardown debounce has priority over the long silence
        # watchdog. It is intentionally independent of _last_connected_seen:
        # inbound AVRCP traffic from a dying session cannot cancel link-down.
        if self._disconnect_deadline and now >= self._disconnect_deadline:
            return self._mark_disconnected()
        # Demote only when BOTH clocks are stale: no "connected evidence" AND
        # no bytes at all from the chip. A radio that is still sending frames
        # we happen not to count as evidence (bare source events, acks) is
        # alive, and demoting it stranded the UI in phantom AUX with every
        # control dead while audio kept playing (2026-08-26).
        if ((now - self._last_connected_seen) > self._btm_silence_timeout_s
                and (now - self._last_rx_byte_at) > self._btm_silence_timeout_s):
            return self._mark_disconnected()
        return None

    @staticmethod
    def _avc_payload(pdu, params):
        return bytes([pdu, 0x00]) + len(params).to_bytes(2, "big") + params

    def avrcp_get_play_status(self, db=0):
        self.send(self.OP_AVC_VENDOR_CMD, bytes([db]) + self._avc_payload(0x30, b""))

    def avrcp_register_notification(self, event_id, interval_s=0, db=0):
        params = bytes([event_id]) + int(interval_s).to_bytes(4, "big")
        self.send(self.OP_AVC_VENDOR_CMD, bytes([db]) + self._avc_payload(0x31, params))

    def schedule_avrcp_notifications(self, specs):
        """Queue register-notification calls to go out later, spaced apart.

        ``specs`` is an iterable of ``(delay_s, event_id, interval_s)``.
        Replaces any previously queued registrations. Serviced by
        tick_notif_regs() from the main loop; self-clears if the link drops
        so a pending registration is never fired into a dead link.
        """
        now = time.monotonic()
        self._pending_notif_regs = [
            (now + d, event_id, interval_s) for (d, event_id, interval_s) in specs
        ]
        # Allow the first due registration immediately; subsequent sends are
        # paced from their actual transmit time, not only their planned time.
        self._last_notif_reg_at = now - self._notif_reg_min_gap_s

    def tick_notif_regs(self, now=None):
        """Send any due deferred notification registrations.

        Cheap no-op while the queue is empty (the common case). Call every
        main-loop iteration, like the other tick_* methods.
        """
        pending = self._pending_notif_regs
        if not pending:
            return
        if not self.connected:
            # Link went away while registrations were queued — drop them.
            # The next CONNECTED edge schedules a fresh set.
            self._pending_notif_regs = []
            return
        if self._avrcp_suspended:
            # AVRCP session is down/re-establishing; the suspend path in
            # note_btm_state already dropped the queue, but guard anyway.
            return
        if now is None:
            now = time.monotonic()
        # Never "catch up" several overdue registrations in one loop.
        # A delayed main loop must preserve the spacing this queue exists for.
        if (now - self._last_notif_reg_at) < self._notif_reg_min_gap_s:
            return
        item = pending[0]
        if now < item[0]:
            return
        self.avrcp_register_notification(item[1], interval_s=item[2])
        self._last_notif_reg_at = now
        self._pending_notif_regs = pending[1:]

    def avrcp_reregister_track_changed(self, db=0):
        """Throttled re-registration for TrackChanged to prevent feedback loops."""
        now = time.monotonic()
        if (now - self._last_track_changed_reg_at) < self._track_changed_reg_throttle_s:
            return False  # Throttled
        self._last_track_changed_reg_at = now
        self.avrcp_register_notification(0x02, interval_s=0, db=db)
        return True

    def avrcp_reregister_status_changed(self, db=0):
        """Throttled re-registration for PlaybackStatusChanged.

        Some BM83 firmware revs choke on rapid register-notification calls
        during AVRCP CT-side establishment, silently dropping the A2DP
        profile while keeping the link up. Throttle to ~0.5 s.
        """
        now = time.monotonic()
        if (now - self._last_status_changed_reg_at) < self._status_reg_throttle_s:
            return False
        self._last_status_changed_reg_at = now
        self.avrcp_register_notification(0x01, interval_s=0, db=db)
        return True

    def avrcp_reregister_position_changed(self, interval_s=1, db=0):
        """Throttled re-registration for PlaybackPositionChanged. See above."""
        now = time.monotonic()
        if (now - self._last_pos_changed_reg_at) < self._pos_reg_throttle_s:
            return False
        self._last_pos_changed_reg_at = now
        self.avrcp_register_notification(0x05, interval_s=interval_s, db=db)
        return True

    def avrcp_get_element_attributes(self, db=0):
        self.send(self.OP_AVRCP_VENDOR_DEP_CMD, bytes([db, 0x20]) + _AVRCP_ATTR_PAYLOAD)

    def schedule_play_status(self, delay_s=0.05):
        """Request the next AVRCP GetPlayStatus poll after ``delay_s`` seconds.

        Use this from callers (e.g., the main loop) instead of poking
        ``_next_playstatus_at`` directly.
        """
        self._next_playstatus_at = time.monotonic() + delay_s

    def defer_attrs(self, delay_s):
        """Protect a quiet window in which no metadata request may be sent."""
        t = time.monotonic() + delay_s
        if t > self._attrs_not_before:
            self._attrs_not_before = t
        if self._next_attrs_at and self._next_attrs_at < self._attrs_not_before:
            self._next_attrs_at = self._attrs_not_before
        return self._attrs_not_before

    def schedule_attrs(self, delay_s=0.35, force=False):
        now = time.monotonic()
        if (not force) and (now - self._last_attrs_req_at) < self._attrs_throttle_s:
            return False
        t = now + delay_s
        if t < self._attrs_not_before:
            t = self._attrs_not_before
        if self._next_attrs_at == 0.0 or t < self._next_attrs_at:
            self._next_attrs_at = t
            return True
        return False

    def consume_relink(self):
        """Return True once per self-healed relink, clearing the flag."""
        if not self._relinked:
            return False
        self._relinked = False
        return True

    def tick_avrcp_resume(self, now=None):
        """Lift a stale AVRCP suspension so polling cannot stall forever.

        The suspension is meant to cover a teardown/re-establish window of a
        second or two. If the chip never sends another connected-state event
        (routine after a profile-level 0x08/0x0C blip) the old code stayed
        suspended indefinitely: no polling, frozen metadata, and no inbound
        traffic to keep the silence watchdog fed.
        """
        if not self._avrcp_suspended:
            return False
        if now is None:
            now = time.monotonic()
        if (now - self._avrcp_suspend_at) < self._avrcp_suspend_max_s:
            return False
        self._avrcp_suspended = False
        self._next_playstatus_at = now
        print("[BTM] AVRCP suspension timed out -> resuming polling")
        return True

    def tick_link_recovery(self, now=None):
        """Gently probe the chip whenever we believe the link is down.

        Deliberately NOT gated on ``power_on``: that flag is inferred from the
        chip's own reporting, so a silent module pins it False and gating here
        would make the dead state permanent. It IS skipped after an explicit
        host-commanded power-off, where silence is the intended outcome.

        Without this, a false disconnect is terminal: tick_avrcp() returns
        early when not connected, so nothing is ever sent, so the chip never
        replies, so `connected` can never come back on its own.

        Each probe sends ``Read_Local_BD_Address`` (answerable in any link
        state, no AVRCP side effects), plus a GetPlayStatus only when the chip
        is already known alive, and re-asserts ``init_link()`` every ~6th
        probe. A reply lets poll()'s relink path recover the session.
        """
        if (self.connected or self._avrcp_suspended or self._explicit_off
                or self._power_state is not None or self._power_confirm_deadline):
            # The last two give the module a QUIET boot window: probe traffic
            # and init_link bursts landing mid power-up are exactly the kind
            # of UART activity this chip is documented to dislike.
            return False
        if now is None:
            now = time.monotonic()
        if now < self._link_probe_at:
            return False
        self._link_probe_at = now + self._link_probe_period_s
        self._link_probe_misses += 1
        # Read_Local_BD_Address is the ideal liveness probe: the chip must
        # answer it in any link state, and it has no AVRCP side effects.
        # NOTE: deliberately NOT gated on power_on. power_on is inferred from
        # the chip's own reporting, so a silent module would otherwise pin it
        # False forever and this recovery path could never run.
        self.send(self.OP_READ_BD_ADDR)
        if self.power_on:
            # Chip is known alive: also nudge AVRCP so a false disconnect can
            # be proven wrong by a real response (see poll()).
            self.avrcp_get_play_status(0)
        # Every ~6th probe, re-assert event reporting. The chip can come back
        # (re-powered, woken) with its event mask stale after an MCU-only
        # reboot; without this the link would look dead forever.
        if (self._link_probe_misses % 6) == 0:
            self.init_link()
        if self._link_probe_misses == 4 and not self._link_dead_warned:
            self._link_dead_warned = True
            print("[BM83] NOT RESPONDING after %d probes — module unpowered,"
                  % self._link_probe_misses)
            print("       asleep, or UART unwired. Check BM83 power and the")
            print("       IO17(TX)/IO18(RX) link; audio may still play since")
            print("       the chip streams A2DP without the host MCU.")
        return True

    def tick_avrcp(self):
        if (not self.connected) or self._avrcp_suspended:
            return
        now = time.monotonic()
        if now >= self._next_playstatus_at:
            self.avrcp_get_play_status(0)
            self._next_playstatus_at = now + self._playstatus_period_s
        self.tick_avrcp_attrs(now)

    def tick_avrcp_attrs(self, now=None):
        if (not self.connected) or self._avrcp_suspended or (self._next_attrs_at == 0.0):
            return False
        if now is None:
            now = time.monotonic()
        if now >= self._next_attrs_at:
            self._last_attrs_req_at = now
            self._next_attrs_at = 0.0
            self._attrs_not_before = 0.0
            self.avrcp_get_element_attributes(0)
            return True
        return False

    @staticmethod
    def parse_avc_vendor_rsp(params):
        if len(params) < 1 + 10:
            return None
        db = params[0]
        p = params[1:]
        pdu = p[6]
        pkt_type = p[7]
        plen = int.from_bytes(p[8:10], "big")
        if len(p) < 10 + plen:
            return None
        return db, pdu, pkt_type, p[10 : 10 + plen]

    def parse_gea_0x5d(self, params):
        if len(params) < 2:
            return None
        pdu_id = params[0]
        payload = params[2:]
        if pdu_id != 0x20 or len(payload) < 5:
            return None
        resp = payload[0]
        is_end = payload[1]
        attr_num = payload[2]
        total_len = int.from_bytes(payload[3:5], "big")
        part = payload[5:]
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
        if is_end != 0x01:
            return None
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
        for _ in range(attr_num):
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
            try:
                s = val.decode("utf-8", "replace").strip()
            except UnicodeError:
                s = "".join(chr(b) if 32 <= b <= 126 else " " for b in val).strip()
            attrs[aid] = s
        return resp, attrs

    @staticmethod
    def parse_avrcp_metadata(data):
        """Simplified single-attribute AVRCP parser used only by host tests."""
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

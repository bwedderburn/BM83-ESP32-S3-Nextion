"""Minimal BLE HID Consumer Control shim for volume/mute.

This is a slimmed-down rewrite of the previous BleHid module. The
soft-reload dance was dropped (fragile under Thonny), but the
bond-wipe pipeline was kept and rebuilt to be NimBLE-safe: erase is
deferred to the disconnected/quiet window, GC + settle delays around
the call, name-cycling after success so Windows treats us as a new
device instead of looping on a cached handle.

Pairing is **passive-only**: this module never calls c.pair() from
the peripheral side. Every previous attempt to drive pairing (timed
grace period, BM83-quiet-window gate) reliably hard-crashed NimBLE
on ESP32-S3 when the BM83 UART was active. iOS / Android auto-pair
within ~1-2s on their own; Windows / Linux users must initiate pair
from the central's Bluetooth settings. The module logs a one-shot
hint after a few unpaired seconds explaining the manual step.

Responsibilities kept:
    * Stand up a BLE HID service with a ConsumerControl device
    * Auto-advertise when not connected, back off on Nimble OOM
    * Passively observe c.paired and log encryption when it lands
    * Send VOLUME_INCREMENT / VOLUME_DECREMENT / MUTE on demand
    * Deferred erase_bonds (via request_erase_bonds, staged across ticks)
    * BLE name counter cycling on successful bond wipe
    * NVM/filesystem persistence of the bond counter

Responsibilities dropped:
    * Soft-reload dance after erase_bonds
    * Peripheral-driven c.pair() (NimBLE crash on ESP32-S3 + BM83)

The public surface used by main.py is:
    setup()                -- initialise BLE radio, HID service, start advertising
    tick()                 -- call every loop to service connect/disconnect edges
    volume(up: bool)       -- send VOLUME_INCREMENT (True) or DECREMENT (False)
    mute()                 -- send the HID MUTE code
    is_connected()         -- bool: True when a central is connected
    request_pause()        -- disconnect without erasing bonds; stay unavailable
    request_enable()       -- allow connections again, retaining bonds and name
    snapshot_status()      -- observed BLE state and queued-operation result
    request_erase_bonds()  -- queue a bond-store wipe (runs while disconnected)
"""
import time
import gc
from utils.common import dprint
from utils.ticks import ticks_add, ticks_less, ticks_ms, ticks_recent


# NimBLE on ESP32-S3 can hard-crash if heavy BLE operations run back to
# back without letting the stack settle. A short settle between stop_adv,
# GC, erase_bonding, and start_adv avoids "out of memory" and "stack
# busy" failures observed during bond-wipe. The settles used to be
# time.sleep() calls inside tick(), stalling the UART/display loop for
# ~150 ms; they are now non-blocking stage deadlines (issue #149, R-02).
# Each gap is still at least this long -- never shorter.
_BLE_STABILIZE_MS = 50

# Public wire/status enums. ENABLED means connections are allowed; it does
# not promise which bonded host will connect to undirected advertising.
MODE_ENABLED = 0
MODE_PAUSING = 1
MODE_PAUSED = 2
MODE_ERROR = 3
ERROR_NONE = 0
ERROR_NOT_READY = 1
ERROR_STOP_ADV = 2
ERROR_DISCONNECT = 3
ERROR_TIMEOUT = 4
ERROR_WORKFLOW = 5
ERROR_OBSERVATION = 6
ERROR_BUSY = 7
_PAUSE_TIMEOUT_MS = 5000
_MAX_PAUSE_CONNECTIONS = 8


def _disable_workflow():
    """Stop the supervisor from independently restarting BLE advertisements.

    boot.py does this before workflow startup. Repeat the capability check
    here for existing installations and soft reloads. No adapter reset or
    bond-store operation is involved. On host Python there is no workflow.
    """
    try:
        import supervisor
    except ImportError:
        return True
    try:
        supervisor.runtime.ble_workflow = False
        return not supervisor.runtime.ble_workflow
    except Exception:
        return False

# Keep the existing two-byte Consumer Control report (ID 3), without the
# default HIDService keyboard and mouse collections. Advertising a keyboard
# makes iOS treat this volume remote as a physical typing device and can hide
# its onscreen keyboard. No keyboard, mouse, LED or boot-keyboard reports are
# needed for the volume/mute controls used by this unit.
_CONSUMER_ONLY_HID_DESCRIPTOR = bytes((
    0x05, 0x0C,        # Usage Page (Consumer)
    0x09, 0x01,        # Usage (Consumer Control)
    0xA1, 0x01,        # Collection (Application)
    0x85, 0x03,        # Report ID (3), as in the existing consumer report
    0x75, 0x10,        # Report Size (16 bits)
    0x95, 0x01,        # Report Count (1)
    0x15, 0x01,        # Logical Minimum (1)
    0x26, 0x8C, 0x02,  # Logical Maximum (0x028C)
    0x19, 0x01,        # Usage Minimum (1)
    0x2A, 0x8C, 0x02,  # Usage Maximum (0x028C)
    0x81, 0x00,        # Input (Data, Array, Absolute)
    0xC0,              # End Collection
))

# Bond-erase stages, advanced at most one per tick() and only once the
# previous stage's settle deadline has passed. 0 = idle.
_ERASE_IDLE = 0
_ERASE_GC = 1        # stop_adv done; next: GC x2
_ERASE_WIPE = 2      # GC done; next: erase_bonding + name cycle
_ERASE_READV = 3     # erase done; next: GC + restart advertising


# Persistent counter file for BLE name cycling.
#
# Windows caches BLE HID devices aggressively: after Forget Device from
# Settings it may still hold a cached bond / resolved-address entry for
# the device name, then silently attempt a stale-key reconnect when the
# device reappears. That reconnect fails in ~1s because our NVS bond
# store was wiped by EBIND, but Windows never re-prompts for pairing
# -- it just loops. The cleanest exit is to give the device a NEW name
# after every bond wipe so Windows sees it as a brand-new device with
# no cached state, forcing a clean "Add device -> Pair" flow.
#
# CIRCUITPY is RO to the board when USB is mounted RW to the host, so
# writes can fail silently. In that case we still bump the in-memory
# counter for the life of the session -- cycling still works until
# power-cycle. Persist-on-next-boot is fine because EBIND-then-power-
# cycle is not a meaningful real-world workflow.
_BLE_COUNTER_FILE = "/ble_counter.txt"


def _read_ble_counter():
    try:
        with open(_BLE_COUNTER_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return 0


def _write_ble_counter(count):
    try:
        with open(_BLE_COUNTER_FILE, "w") as f:
            f.write(str(count))
        return True
    except Exception as e:
        dprint("[BLE] counter write err:", e)
        return False


class BleHid:
    __slots__ = (
        "enabled",
        "base_name",
        "name",
        "_memory_counter",
        "_counter_persisted",
        "_ble",
        "_adv",
        "_hid",
        "_cc",
        "_CCC",
        "_ready",
        "_was_connected",
        "_adv_inhibit_until",
        "_adv_oom_count",
        "_adv_kick_period_s",
        "_last_adv_kick_at",
        "_last_cc_at",
        "_cc_min_interval_ms",
        "_need_pairing_check",
        "_last_pair_try_at",
        "_pair_retry_s",
        "_pair_attempts",
        "_pair_attempt_limit",
        "_erase_pending",
        "_erase_stage",
        "_erase_due",
        "_last_erase_at",
        "_erase_cooldown_s",
        "_connected_at",
        "_pair_auto_after_s",
        "_pair_drive_tried",
        "_ever_paired_this_conn",
        "_fast_disconnect_s",
        "_peer_logged",
        "_manual_pair_hint_after_s",
        "_manual_pair_hint_logged",
        "_intent_enabled",
        "_handoff_mode",
        "_handoff_error",
        "_pause_deadline",
        "_pause_due",
        "_pause_attempted",
        "_intentional_disconnect_at",
        "_enable_pending",
    )

    def __init__(self, enabled, name):
        self.enabled = enabled
        # base_name is the immutable identifier from main.py; the
        # cycling counter is appended to it to form self.name, which
        # is what actually gets advertised. If the counter file says
        # 7, advertised name is "<base>_7". Base stays the same so
        # the "erase counter" story is: always build name from base
        # + counter, never mutate base.
        self.base_name = name
        self.name = name
        # Counter state. _memory_counter is the source of truth for
        # the current session; _counter_persisted tracks whether we
        # were able to write it to CIRCUITPY (fails when USB is
        # mounted RW to the host, which is common during development).
        # When persistence fails the in-memory value still advances
        # so naming within a single session still cycles; we just
        # don't survive a reboot in that case, which is fine.
        self._memory_counter = 0
        self._counter_persisted = False
        self._ble = None
        self._adv = None
        self._hid = None
        self._cc = None
        self._CCC = None
        self._ready = False
        self._was_connected = False
        self._intent_enabled = bool(enabled)
        self._handoff_mode = MODE_ENABLED
        self._handoff_error = ERROR_NONE
        self._pause_deadline = None
        self._pause_due = None
        self._pause_attempted = []
        self._intentional_disconnect_at = None
        self._enable_pending = False

        # Advertising backoff — Nimble can fail with out-of-memory under
        # pressure; hold off for a bit when that happens and grow the
        # backoff if it keeps failing, so we don't spin a tight retry loop.
        self._adv_inhibit_until = 0.0
        self._adv_oom_count = 0
        self._adv_kick_period_s = 6.0
        self._last_adv_kick_at = 0.0

        # Minimum gap between Consumer Control sends — the HID pipe on
        # iOS can drop very fast bursts. 60 ms matches the repeat cadence
        # of a held hardware volume key.
        #
        # Kept on wrap-safe ms ticks rather than time.monotonic(): after a
        # few days of uptime the float clock's step exceeds 60 ms, which
        # would quantise this limiter (issue #149, R-03). None = never sent.
        self._last_cc_at = None
        self._cc_min_interval_ms = 60

        # Pairing state — passive observer only. See _ensure_paired
        # for why we no longer call c.pair() from the peripheral side.
        self._need_pairing_check = False
        self._last_pair_try_at = 0.0
        self._pair_retry_s = 2.0
        self._pair_attempts = 0
        # 12 attempts × 2s = 24s of polling window. Covers a slow human
        # clicking "Allow" on the Windows pairing dialog — observed up to
        # ~15s in practice. The old 4-attempt (8s) budget would stop
        # polling before pairing completed, suppressing the
        # "[BLE] Paired/encrypted" log line on success. Sends still
        # worked (the BLE stack negotiated underneath) but the log was
        # misleading. See P1 #7 in docs/code-review-2026-05-26.md.
        self._pair_attempt_limit = 12

        # Bond-wipe request flag. Set by request_erase_bonds() (typically
        # from the Nextion BT_EBIND button) and serviced by tick() while
        # fully disconnected. Running erase_bonding while connected or
        # actively advertising has been observed to hard-crash NimBLE,
        # so the request is buffered until we're in a quiet state.
        self._erase_pending = False
        # Staged-erase state machine (see _tick_erase). _erase_due is a
        # ticks_ms() deadline, only meaningful while _erase_stage != idle.
        self._erase_stage = _ERASE_IDLE
        self._erase_due = 0
        # Rate-limit repeat erases. Each wipe rewrites NVS and cycles
        # the radio; doing it back-to-back is what crashed the stack in
        # earlier hardware runs. 30s between successful erases is
        # plenty for the "Forget Device -> EBIND -> re-pair" flow.
        # Initialised well in the past so the very first EBIND after
        # boot is not blocked by a "cooldown" against t=0.
        self._erase_cooldown_s = 30.0
        self._last_erase_at = -self._erase_cooldown_s - 1.0

        # Passive-only pairing model.
        #
        # We watch getattr(c, "paired") and log when the central
        # establishes encryption on its own. iOS / Android auto-initiate
        # pairing within ~1-2s of connecting to a BLE HID peripheral,
        # so phones complete here without intervention. Windows / Linux
        # centrals must initiate pairing from their own settings UI
        # (Bluetooth -> Other devices -> Pair). The peripheral does
        # NOT drive c.pair() — earlier revs of this module did, and
        # the call reliably hard-crashed NimBLE on ESP32-S3 when run
        # while the BM83 UART was mid-AVRCP-handshake. Two mitigation
        # attempts (timed grace, BM83-quiet-window gate) both still
        # crashed; passive-only is the durable fix.
        self._connected_at = 0.0
        # If a central is still unpaired after this long, print a
        # one-shot hint explaining the manual-pair step. Tuned long
        # enough that iOS auto-pair (~1-2s) and a slow Windows user
        # clicking through the pair dialog (3-6s) both complete first
        # without spamming the log.
        self._manual_pair_hint_after_s = 8.0
        self._manual_pair_hint_logged = False

        # Stale-bond diagnostics. When a central with a stale bond
        # (we wiped our NVS with EBIND but it still thinks it's
        # paired) reconnects, its stack sees the encryption mismatch
        # and drops the link within ~1s, never completing pairing.
        # We latch "did we ever see paired=True on this connection"
        # and, on disconnect, if the link went down that fast without
        # pairing, print a clear user-facing hint so the log tells
        # Brian which side needs its bond cleared.
        self._ever_paired_this_conn = False
        self._fast_disconnect_s = 2.0

        # Per-connection "did we log the peer address yet" latch.
        # On NimBLE the BLERadio.connections list is often empty at
        # the moment _on_connect fires (the peer record hasn't been
        # linked into the list yet), so iterating there silently
        # yields nothing. Instead we log peer_address during the
        # first _ensure_paired poll, one tick later, where the list
        # is reliably populated.
        self._peer_logged = False

    # ---- lifecycle ------------------------------------------------------

    def setup(self):
        if not self.enabled:
            return
        try:
            if not _disable_workflow():
                print("[BLE] Background workflow control unavailable")
            from adafruit_ble import BLERadio
            from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
            from adafruit_ble.services.standard.hid import HIDService
            from adafruit_hid.consumer_control import ConsumerControl
            from adafruit_hid.consumer_control_code import ConsumerControlCode as CCC

            self._ble = BLERadio()
            # Load persisted cycling counter and apply it to the
            # advertised name before the radio comes up. If the file
            # doesn't exist yet (fresh device) counter is 0 and the
            # name is just base_name -- no suffix until first EBIND.
            counter = _read_ble_counter()
            self._memory_counter = counter
            self._counter_persisted = True  # read succeeded; assume FS is writable
            if counter > 0:
                self.name = "%s_%d" % (self.base_name, counter)
            else:
                self.name = self.base_name
            # BLERadio uses this same name in its default scan response.
            # boot.py prevents the maintenance advertiser preceding it.
            self._ble.name = self.name
            # NOTE: We deliberately do NOT set GAP Appearance. Setting
            # it to 0x03C1 (HID Keyboard) caused Windows to key its
            # bond cache on MAC + HID-Keyboard-role and silently
            # attempt stale-LTK reconnects on every advertisement,
            # bypassing the Add-device -> Pair dialog entirely even
            # after name cycling. The pre-#113 recovered_src build
            # that Brian reported as "worked perfectly" also did not
            # set Appearance; matching that behaviour here. Windows
            # will classify the device under "Other devices" in the
            # Bluetooth settings list, which is cosmetic -- the HID
            # Consumer Control pipe still works for volume keys.
            class ConsumerOnlyHIDService(HIDService):
                # Service eagerly binds inherited Characteristic descriptors.
                # A report-map change alone would leave keyboard boot reports
                # and boot/report switching advertised in the GATT service.
                boot_keyboard_in = None
                boot_keyboard_out = None
                protocol_mode = None

            self._hid = ConsumerOnlyHIDService(hid_descriptor=_CONSUMER_ONLY_HID_DESCRIPTOR)
            self._adv = ProvideServicesAdvertisement(self._hid)
            self._cc = ConsumerControl(self._hid.devices)
            self._CCC = CCC
            self._ready = True
            print("[BLE] Ready:", self.name)
            self._start_adv(force=True)
        except Exception as e:
            print("[BLE] Disabled:", e)
            self._ready = False

    def is_connected(self):
        if not self._ready or not self._ble:
            return False
        try:
            return bool(self._ble.connected)
        except Exception:
            return False

    def request_pause(self):
        """Queue a bond-preserving release; never call the stack from a UI callback."""
        if self._erase_stage != _ERASE_IDLE:
            self._handoff_mode = MODE_ERROR
            self._handoff_error = ERROR_BUSY
            return False
        if not self._ready or not self._ble:
            self._intent_enabled = False
            self._handoff_fail(ERROR_NOT_READY)
            return False
        if not self._intent_enabled:
            return self._handoff_mode != MODE_ERROR
        self._intent_enabled = False
        self._enable_pending = False
        # A previous queued wipe must not be triggered by this disconnect.
        self._erase_pending = False
        self._pause_deadline = None
        self._pause_due = None
        self._pause_attempted = []
        self._handoff_mode = MODE_PAUSING
        self._handoff_error = ERROR_NONE
        return True

    def request_enable(self):
        """Queue normal advertising; the previous host may reconnect first."""
        if self._erase_stage != _ERASE_IDLE:
            self._handoff_mode = MODE_ERROR
            self._handoff_error = ERROR_BUSY
            return False
        if not self._ready or not self._ble or not self.enabled:
            self._handoff_fail(ERROR_NOT_READY)
            return False
        if self._intent_enabled and self._handoff_mode == MODE_ENABLED:
            return True
        self._intent_enabled = bool(self.enabled)
        self._enable_pending = True
        self._pause_deadline = None
        self._pause_due = None
        self._pause_attempted = []
        self._handoff_mode = MODE_ENABLED
        self._handoff_error = ERROR_NONE
        return True

    def _observed_state(self):
        try:
            return bool(self._ble.connected), bool(self._ble.advertising)
        except Exception:
            return None

    def snapshot_status(self):
        """Return actual observations, never a radio-ACK-based success claim."""
        state = self._observed_state() if self._ready and self._ble else None
        mode, error = self._handoff_mode, self._handoff_error
        if state is None:
            mode = MODE_ERROR
            error = ERROR_OBSERVATION if self._ready else ERROR_NOT_READY
            state = False, False
        elif mode == MODE_PAUSED and (state[0] or state[1]):
            # A late native callback can arrive between tick and publication.
            mode = MODE_PAUSING
        return {"ready": self._ready, "intent_enabled": self._intent_enabled,
                "connected": state[0], "advertising": state[1],
                "mode": mode, "error": error}

    def _handoff_fail(self, error):
        changed = self._handoff_mode != MODE_ERROR or self._handoff_error != error
        self._handoff_mode = MODE_ERROR
        self._handoff_error = error
        self._pause_deadline = None
        self._pause_due = None
        if changed:
            print("[BLE] Pause/enable failed:", error)

    def _tick_pause(self):
        """One native termination per tick, then observe completion across ticks."""
        if self._handoff_mode == MODE_ERROR:
            return
        state = self._observed_state()
        if state is None:
            self._handoff_fail(ERROR_OBSERVATION)
            return
        if self._handoff_mode == MODE_PAUSED and not any(state):
            return
        now = ticks_ms()
        if self._pause_deadline is None:
            self._handoff_mode = MODE_PAUSING
            self._pause_deadline = ticks_add(now, _PAUSE_TIMEOUT_MS)
            if not _disable_workflow():
                self._handoff_fail(ERROR_WORKFLOW)
                return
            if not self._stop_adv():
                self._handoff_fail(ERROR_STOP_ADV)
                return
            self._pause_due = ticks_add(now, _BLE_STABILIZE_MS)
            return
        if ticks_less(now, self._pause_due):
            return
        connected, advertising = state
        if not connected and not advertising:
            self._handoff_mode = MODE_PAUSED
            self._handoff_error = ERROR_NONE
            self._pause_deadline = None
            self._pause_due = None
            print("[BLE] Volume remote paused; bonds retained")
            return
        if not ticks_less(now, self._pause_deadline):
            self._handoff_fail(ERROR_TIMEOUT)
            return
        if advertising:
            # An advertiser outside our ownership must not be called paused.
            self._handoff_fail(ERROR_STOP_ADV)
            return
        try:
            connections = self._ble.connections
            for connection in connections:
                if any(connection is previous for previous in self._pause_attempted):
                    continue
                if len(self._pause_attempted) >= _MAX_PAUSE_CONNECTIONS:
                    self._handoff_fail(ERROR_DISCONNECT)
                    return
                self._pause_attempted.append(connection)
                # On ESP32 CP10.3.1 this queues ble_gap_terminate, without a
                # busy wait. Never retry the same native connection object.
                connection.disconnect()
                # Keep this across Enable: termination completes asynchronously,
                # possibly after advertising has been requested again.
                self._intentional_disconnect_at = now
                return
        except Exception:
            self._handoff_fail(ERROR_DISCONNECT)

    # ---- advertising ----------------------------------------------------

    def _is_advertising(self):
        try:
            return bool(getattr(self._ble, "advertising", False))
        except Exception:
            return False

    def _stop_adv(self):
        if not self._ready or not self._ble:
            return False
        try:
            if getattr(self._ble, "advertising", False):
                self._ble.stop_advertising()
            return not bool(self._ble.advertising)
        except Exception as e:
            dprint("[BLE] stop adv err:", e)
            return False

    def _start_adv(self, force=False):
        if not self._intent_enabled or not self._ready or not self._ble or not self._adv:
            return
        now = time.monotonic()
        if now < self._adv_inhibit_until:
            return
        if getattr(self._ble, "connected", False):
            return
        if self._is_advertising() and not force:
            return
        if force:
            self._stop_adv()
        gc.collect()
        try:
            self._ble.start_advertising(self._adv)
            self._adv_oom_count = 0
            self._adv_inhibit_until = 0.0
            self._last_adv_kick_at = now
        except Exception as e:
            msg = str(e).lower()
            # Distinguish "Nimble out of memory" from generic failures so
            # OOM can grow a longer backoff while other errors get a flat 4s.
            if "nimble" in msg and "memory" in msg:
                self._adv_oom_count += 1
                backoff = min(20.0, 4.0 + 4.0 * self._adv_oom_count)
            else:
                backoff = 4.0
            self._adv_inhibit_until = now + backoff
            self._last_adv_kick_at = now + backoff
            dprint("[BLE] adv err (backoff %.1fs):" % backoff, e)

    # ---- connect / disconnect -----------------------------------------

    def _on_connect(self):
        print("[BLE] Connected")
        # An intentional release of the previous link must not hide a genuine
        # fast pairing failure on this new connection.
        self._intentional_disconnect_at = None
        # Peer address is logged from _ensure_paired one tick later,
        # because NimBLE's connections list is frequently still empty
        # at the moment this callback fires.
        #
        # ConsumerControl is intentionally NOT reinstantiated on every
        # connect anymore. The HID device pipe (self._hid.devices) is
        # stable across reconnects in practice on adafruit_ble; the
        # previous reinit was a defensive hedge against a theoretical
        # device swap that doesn't actually happen. If _cc is missing
        # (setup() failed earlier) we still create it once here as a
        # late-bound fallback. See P2 #14 in
        # docs/code-review-2026-05-26.md.
        if self._cc is None:
            try:
                from adafruit_hid.consumer_control import ConsumerControl
                self._cc = ConsumerControl(self._hid.devices)
            except Exception as e:
                print("[BLE] ConsumerControl init fail:", e)
        self._need_pairing_check = True
        self._pair_attempts = 0
        self._last_pair_try_at = 0.0
        self._connected_at = time.monotonic()
        self._ever_paired_this_conn = False
        self._peer_logged = False
        self._manual_pair_hint_logged = False

    def _on_disconnect(self):
        # Measure how long we stayed up and whether pairing ever
        # completed. If a central connects and drops within
        # _fast_disconnect_s without ever encrypting, that is the
        # classic stale-bond symptom: the central still has a bond
        # we no longer have (e.g. we ran EBIND after it had paired),
        # its stack sees the SMP mismatch and tears the link down
        # before pairing can start. The only fix is on the central:
        # Forget Device, then reconnect. Surface this in the log so
        # the user isn't left guessing which side is stale.
        try:
            uptime = time.monotonic() - self._connected_at
        except Exception:
            uptime = 0.0
        print("[BLE] Disconnected (uptime %.2fs, paired=%s)"
              % (uptime, self._ever_paired_this_conn))
        intentional = ticks_recent(ticks_ms(), self._intentional_disconnect_at,
                                   _PAUSE_TIMEOUT_MS)
        self._intentional_disconnect_at = None
        if (not intentional and uptime < self._fast_disconnect_s
                and not self._ever_paired_this_conn):
            print("[BLE] Fast disconnect without pairing — likely stale bond on")
            print("      the central (phone / PC / Pi). Fix on the central:")
            print("      Forget Device. Then on this unit: press EBIND. Then")
            print("      reconnect from the central's OTHER DEVICES list.")
        self._need_pairing_check = False
        self._pair_attempts = 0
        self._ever_paired_this_conn = False
        self._manual_pair_hint_logged = False
        # Kick advertising immediately so the phone can re-find us.
        self._start_adv(force=True)

    def _ensure_paired(self):
        # Passive-only pairing observer.
        #
        # We watch getattr(c, "paired") on each poll and log when the
        # central completes encryption on its own. iOS and Android
        # auto-initiate pairing within ~1-2s of connecting to a BLE
        # HID peripheral, so phones complete here without intervention.
        # Windows and Linux centrals must initiate pairing from their
        # own settings UI — if the central is still unpaired after
        # _manual_pair_hint_after_s seconds we print a one-shot hint
        # explaining the manual step.
        #
        # The peripheral does NOT call c.pair() — every prior attempt
        # to drive pairing from this side has hard-crashed NimBLE on
        # ESP32-S3 when the BM83 UART was active. Passive-only is the
        # durable fix; see the constructor comment for history.
        if not self._ble or not getattr(self._ble, "connected", False):
            return
        if self._pair_attempts >= self._pair_attempt_limit:
            self._need_pairing_check = False
            return
        now = time.monotonic()
        if (now - self._last_pair_try_at) < self._pair_retry_s:
            return
        self._last_pair_try_at = now
        try:
            conns = list(getattr(self._ble, "connections", []))
        except Exception:
            conns = []
        since_connect = now - self._connected_at
        # Log the peer address on the first poll where we can read it.
        # Two traps stacked here:
        #   1. NimBLE often populates the connections list a tick or
        #      two before it resolves the peer address, so on the very
        #      first non-empty poll the address may still be None.
        #      Only latch _peer_logged once we've actually printed
        #      something — otherwise we silently miss the line for the
        #      whole connection.
        #   2. adafruit_ble 10.1.3's BLEConnection wrapper does NOT
        #      expose `peer_address` directly (verified by dumping the
        #      .mpy string table — the wrapper has paired/pair/peer/
        #      connection_interval but no peer_address). The address
        #      lives on the underlying _bleio.Connection. Probe a few
        #      likely attribute paths in priority order and use the
        #      first one that yields a real address. This survives
        #      both old wrappers (peer_address present) and new
        #      wrappers (must dig through _bleio_connection or peer).
        # Useful for telling iPhone (random resolvable address,
        # different each reconnect) from Windows (stable public
        # address) in the serial log.
        if (not self._peer_logged) and conns:
            for c in conns:
                addr = None
                for path in ("peer_address",
                             "_bleio_connection.peer_address",
                             "_bleio_connection.address",
                             "peer.address"):
                    try:
                        obj = c
                        for part in path.split("."):
                            obj = getattr(obj, part, None)
                            if obj is None:
                                break
                        if obj is not None:
                            addr = obj
                            break
                    except Exception:
                        pass
                if addr is not None:
                    print("[BLE] peer:", addr)
                    self._peer_logged = True
        for c in conns:
            try:
                paired = getattr(c, "paired", None)
                if paired:
                    self._need_pairing_check = False
                    self._pair_attempts = 0
                    self._ever_paired_this_conn = True
                    print("[BLE] Paired/encrypted")
                    continue
                # Not paired yet. After the hint deadline, print a
                # one-shot message telling the user how to pair from
                # the central's side. iOS/Android auto-pair in 1-2s
                # so the hint fires only for Windows/Linux/stuck flows.
                if (not self._manual_pair_hint_logged) and since_connect >= self._manual_pair_hint_after_s:
                    self._manual_pair_hint_logged = True
                    print("[BLE] Not paired after %.0fs. iOS/Android auto-pair;"
                          % since_connect)
                    print("      for Windows: Settings -> Bluetooth & devices ->")
                    print("      Other devices -> '%s' -> Pair." % self.name)
                    print("      For Linux: bluetoothctl pair <mac>.")
                    print("      If the central still won't pair: Forget Device on")
                    print("      the central, then press EBIND on this unit, then")
                    print("      retry from the central's settings.")
                # Bump counter so we eventually stop polling if this
                # connection never encrypts. With _pair_attempt_limit=12
                # and _pair_retry_s=2.0 that's ~24s of polling — long
                # enough for a human to click through the Windows pair
                # dialog after seeing the hint above.
                self._pair_attempts += 1
                dprint("[BLE] pair poll %d/%d: paired=%r since_connect=%.1fs"
                       % (self._pair_attempts, self._pair_attempt_limit,
                          paired, since_connect))
            except Exception as e:
                self._pair_attempts += 1
                dprint("[BLE] pair poll err (attempt %d):" % self._pair_attempts, e)

    def tick(self):
        if not self._ready or not self._ble:
            return
        if self._erase_stage != _ERASE_IDLE:
            # A staged bond wipe owns the radio until it finishes: no
            # advertising kicks and no edge handling mid-sequence. Edges
            # are level-compared against _was_connected, so one that
            # arrives meanwhile is processed on the first tick after.
            self._tick_erase()
            return
        now = time.monotonic()
        state = self._observed_state()
        if state is None:
            self._handoff_fail(ERROR_OBSERVATION)
            return
        connected = state[0]
        if connected != self._was_connected:
            self._was_connected = connected
            if connected:
                self._on_connect()
            else:
                self._on_disconnect()
        if not self._intent_enabled:
            self._tick_pause()
            if self._handoff_mode == MODE_PAUSED and self._erase_pending:
                self._begin_erase()
            return
        if self._enable_pending:
            self._enable_pending = False
            if not _disable_workflow():
                self._handoff_fail(ERROR_WORKFLOW)
                return
            self._adv_inhibit_until = 0.0
            self._last_adv_kick_at = now
        if not connected:
            # Start a pending bond wipe in the disconnected/quiet window
            # before re-kicking advertising. The staged sequence restarts
            # advertising itself on the way out.
            if self._erase_pending:
                self._begin_erase()
                return
            if not self._is_advertising():
                self._start_adv(force=False)
            elif (now - self._last_adv_kick_at) > self._adv_kick_period_s:
                self._start_adv(force=True)
        else:
            if self._need_pairing_check:
                self._ensure_paired()

    # ---- bond management ------------------------------------------------

    def request_erase_bonds(self):
        """Request a bond-store wipe.

        Pure flag-setter. The actual erase runs from tick() once the
        link is down and the radio is quiet — erase_bonding is brittle
        on NimBLE under active connections / advertising, and a
        synchronous c.disconnect() from this callsite was observed to
        hard-crash the stack when the BM83 UART was mid-handshake (the
        AVRCP metadata exchange right after reconnect is a common
        trigger).

        If the user wants to wipe bonds while BLE is connected, they
        should drop the link from the central side (Forget Device, or
        Disconnect) first, or just leave the flag set and walk out of
        range — tick() will service the request as soon as the link
        is down.
        """
        if not self._ready:
            print("[BLE] erase_bonds: BLE not ready")
            return
        if self._erase_pending:
            print("[BLE] erase_bonds: already pending")
            return
        now = time.monotonic()
        if (now - self._last_erase_at) < self._erase_cooldown_s:
            remaining = self._erase_cooldown_s - (now - self._last_erase_at)
            print("[BLE] erase_bonds: on cooldown (%.1fs left)" % remaining)
            return
        self._erase_pending = True
        if getattr(self._ble, "connected", False):
            print("[BLE] erase_bonds: queued — disconnect central first, then it'll run")
        else:
            print("[BLE] erase_bonds: queued — will run on next tick")

    def _begin_erase(self):
        """Start the staged bond-store wipe. tick() only, while disconnected.

        Sequence is modelled on the recovered_source flow that worked on
        this hardware: stop advertising, settle, GC, settle, attempt the
        erase via adafruit_ble first then _bleio.adapter as fallback,
        settle, GC, kick advertising back up. The order and the >= 50 ms
        settles are unchanged from the old synchronous version; only the
        waiting moved out of time.sleep() and into per-tick deadlines,
        so the BM83/Nextion UARTs keep being serviced in between.
        Every step is wrapped because any of them can throw on NimBLE
        under memory pressure.
        """
        self._erase_pending = False
        self._last_erase_at = time.monotonic()
        print("[BLE] erase_bonds: running")
        # 1. Stop advertising so the radio isn't actively pumping
        try:
            self._stop_adv()
        except Exception as e:
            dprint("[BLE] erase_bonds stop_adv err:", e)
        self._erase_next(_ERASE_GC)

    def _erase_next(self, stage):
        self._erase_stage = stage
        self._erase_due = ticks_add(ticks_ms(), _BLE_STABILIZE_MS)

    def _tick_erase(self):
        """Advance the staged bond wipe by at most one step."""
        if ticks_less(ticks_ms(), self._erase_due):
            return
        stage = self._erase_stage
        if stage == _ERASE_GC:
            # 2. Settle + GC so the NVS write has headroom
            gc.collect()
            gc.collect()
            self._erase_next(_ERASE_WIPE)
        elif stage == _ERASE_WIPE:
            if getattr(self._ble, "connected", False):
                # Advertising was stopped, so this should not happen; but
                # erase_bonding with a live link has hard-crashed NimBLE,
                # so never run it here. Re-queue for the next quiet window.
                print("[BLE] erase_bonds: central connected mid-sequence, re-queued")
                self._erase_stage = _ERASE_IDLE
                self._erase_pending = True
                return
            self._erase_wipe()
            self._erase_next(_ERASE_READV)
        else:
            # 5. Settled after the erase: GC and re-advertise so the next
            # central sees a clean radio.
            self._erase_stage = _ERASE_IDLE
            gc.collect()
            try:
                self._start_adv(force=True)
            except Exception as e:
                dprint("[BLE] erase_bonds restart adv err:", e)

    def _erase_wipe(self):
        """Steps 3-4: erase the bond store, then cycle the advertised name."""
        # 3. Attempt the erase. Try adafruit_ble's wrapper first; if
        # it doesn't exist on this build, fall back to the underlying
        # _bleio.adapter call.
        ok = False
        try:
            if hasattr(self._ble, "erase_bonding"):
                self._ble.erase_bonding()
                ok = True
        except Exception as e:
            dprint("[BLE] erase_bonding (adafruit_ble) err:", e)
        if not ok:
            try:
                import _bleio
                if hasattr(_bleio.adapter, "erase_bonding"):
                    _bleio.adapter.erase_bonding()
                    ok = True
            except Exception as e:
                dprint("[BLE] erase_bonding (_bleio.adapter) err:", e)
        print("[BLE] erase_bonds:", "OK" if ok else "Unavailable on this build")
        # 4. If the erase succeeded, bump the cycling counter and
        # update the advertised name. This is the key mechanism for
        # rescuing Windows' stale-handle auto-reconnect loop -- a
        # new name means Windows sees a new device with no cached
        # state, forcing a clean "Add device -> Pair" flow.
        if ok:
            try:
                # max() guards against a corrupted / stale persisted
                # value dragging the counter backwards relative to
                # our in-memory view.
                persisted = _read_ble_counter() if self._counter_persisted else 0
                counter = max(persisted, self._memory_counter) + 1
                self._memory_counter = counter
                self._counter_persisted = _write_ble_counter(counter)
                if not self._counter_persisted:
                    dprint("[BLE] counter: in-memory only (FS read-only)")
                self._update_ble_name(counter)
            except Exception as e:
                dprint("[BLE] name-cycle err:", e)

    def _update_ble_name(self, counter):
        """Rewrite the advertised BLE name to base_name + counter.

        Called right after a successful bond wipe so the next
        advertising cycle presents a fresh identity to any central
        that still has a cached handle for the old name. The counter
        suffix format is "_%d" so the first cycled name is
        "<base>_1", second "<base>_2", etc. ConsumerControl bonds
        from the central's perspective are keyed on device name, so
        this is sufficient to look like a new device.

        Known limitation — iPhone re-pair after rename:
            Once the advertised name has cycled to "<base>_N", iPhones
            do not re-pair until the ESP32 is power-cycled. The iOS
            BLE stack seems to cache the new name as "seen, paired
            before" against the unit's MAC after the first successful
            pair in that boot session, and subsequent EBIND -> rename
            cycles in the same boot session don't shake it loose. A
            power-cycle clears whatever in-memory state iOS is holding
            and the next pair works cleanly. Android and Windows do
            not show this behaviour. Documented rather than fixed
            because the workaround (power-cycle) is one button press
            and the alternative is to chase iOS-specific bond/cache
            quirks that we have limited visibility into.
        """
        self.name = "%s_%d" % (self.base_name, counter)
        try:
            self._ble.name = self.name
            print("[BLE] Name updated to:", self.name)
        except Exception as e:
            dprint("[BLE] name update err:", e)

    # ---- HID sends ------------------------------------------------------

    def _send_ccc(self, code):
        if not self._intent_enabled or not self._ready or not self._ble or not self._cc:
            return
        if not getattr(self._ble, "connected", False):
            return
        now = ticks_ms()
        if ticks_recent(now, self._last_cc_at, self._cc_min_interval_ms):
            return
        self._last_cc_at = now
        if self._need_pairing_check:
            self._ensure_paired()
        try:
            self._cc.send(code)
        except Exception as e:
            print("[BLE] send fail:", e)

    def volume(self, up):
        if not self._CCC:
            return
        self._send_ccc(self._CCC.VOLUME_INCREMENT if up else self._CCC.VOLUME_DECREMENT)

    def mute(self):
        if not self._CCC:
            return
        self._send_ccc(self._CCC.MUTE)

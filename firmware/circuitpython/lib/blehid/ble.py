"""Minimal BLE HID Consumer Control shim for volume/mute.

This is a deliberately slimmed-down rewrite of the previous BleHid module.
The bonding/erase_bonds/name-cycling machinery was removed because the
soft-reload path it relied on was fragile under Thonny and because
bonds can be cleared cleanly from the phone side (Forget Device)
followed by an ESP32 power-cycle.

Responsibilities kept:
    * Stand up a BLE HID service with a ConsumerControl device
    * Auto-advertise when not connected, back off on Nimble OOM
    * Re-pair on (re)connect when the central didn't auto-encrypt
    * Send VOLUME_INCREMENT / VOLUME_DECREMENT / MUTE on demand

Responsibilities dropped:
    * erase_bonds / request_erase_bonds / soft-reload dance
    * BLE name counter cycling
    * NVM/filesystem persistence of bond counter

The public surface used by main.py is:
    setup()           -- initialise BLE radio, HID service, start advertising
    tick()            -- call every loop to service connect/disconnect edges
    volume(up: bool)  -- send VOLUME_INCREMENT (True) or DECREMENT (False)
    mute()            -- send the HID MUTE code
    is_connected()    -- bool: True when a central is connected
"""
import time
import gc
from utils.common import dprint


# Nimble on ESP32-S3 can hard-crash if heavy BLE operations run back to
# back without letting the stack settle. A short sleep between stop_adv,
# disconnect, erase_bonding, and start_adv avoids "out of memory" and
# "stack busy" failures observed during bond-wipe.
_BLE_STABILIZE_S = 0.05


class BleHid:
    __slots__ = (
        "enabled",
        "name",
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
        "_cc_min_interval_s",
        "_need_pairing_check",
        "_last_pair_try_at",
        "_pair_retry_s",
        "_pair_attempts",
        "_pair_attempt_limit",
        "_erase_pending",
        "_last_erase_at",
        "_erase_cooldown_s",
    )

    def __init__(self, enabled, name):
        self.enabled = enabled
        self.name = name
        self._ble = None
        self._adv = None
        self._hid = None
        self._cc = None
        self._CCC = None
        self._ready = False
        self._was_connected = False

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
        self._last_cc_at = 0.0
        self._cc_min_interval_s = 0.06

        # Pairing state — passive observer only. See _ensure_paired
        # for why we no longer call c.pair() from the peripheral side.
        self._need_pairing_check = False
        self._last_pair_try_at = 0.0
        self._pair_retry_s = 2.0
        self._pair_attempts = 0
        self._pair_attempt_limit = 4

        # Bond-wipe request flag. Set by request_erase_bonds() (typically
        # from the Nextion BT_EBIND button) and serviced by tick() while
        # fully disconnected. Running erase_bonding while connected or
        # actively advertising has been observed to hard-crash NimBLE,
        # so the request is buffered until we're in a quiet state.
        self._erase_pending = False
        # Rate-limit repeat erases. Each wipe rewrites NVS and cycles
        # the radio; doing it back-to-back is what crashed the stack in
        # earlier hardware runs. 30s between successful erases is
        # plenty for the "Forget Device -> EBIND -> re-pair" flow.
        self._last_erase_at = 0.0
        self._erase_cooldown_s = 30.0

    # ---- lifecycle ------------------------------------------------------

    def setup(self):
        if not self.enabled:
            return
        try:
            from adafruit_ble import BLERadio
            from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
            from adafruit_ble.services.standard.hid import HIDService
            from adafruit_hid.consumer_control import ConsumerControl
            from adafruit_hid.consumer_control_code import ConsumerControlCode as CCC

            self._ble = BLERadio()
            self._ble.name = self.name
            self._hid = HIDService()
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

    # ---- advertising ----------------------------------------------------

    def _is_advertising(self):
        try:
            return bool(getattr(self._ble, "advertising", False))
        except Exception:
            return False

    def _stop_adv(self):
        if not self._ready or not self._ble:
            return
        try:
            if getattr(self._ble, "advertising", False):
                self._ble.stop_advertising()
        except Exception as e:
            dprint("[BLE] stop adv err:", e)

    def _start_adv(self, force=False):
        if not self._ready or not self._ble or not self._adv:
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
        # Re-init ConsumerControl on the new device to avoid a stale
        # binding if adafruit_ble swapped the HID device out.
        try:
            from adafruit_hid.consumer_control import ConsumerControl
            self._cc = ConsumerControl(self._hid.devices)
        except Exception as e:
            print("[BLE] ConsumerControl init fail:", e)
        self._need_pairing_check = True
        self._pair_attempts = 0
        self._last_pair_try_at = 0.0

    def _on_disconnect(self):
        print("[BLE] Disconnected")
        self._need_pairing_check = False
        self._pair_attempts = 0
        # Kick advertising immediately so the phone can re-find us.
        self._start_adv(force=True)

    def _ensure_paired(self):
        # Passive pairing observer.
        #
        # We deliberately do NOT call c.pair() from the peripheral side.
        # c.pair() sends an LL Security Request and then BLOCKS the main
        # loop until pairing completes, times out (~30s), or the link
        # drops. On recent iOS, the peer-initiated Security Request can
        # be interpreted as a key mismatch against any stale bond and
        # triggers an immediate disconnect — which then leaves us hung
        # in pair() for the full connection supervision timeout. During
        # that block the BM83 UART FIFO overruns and events are lost
        # (the heartbeat exposes this as 30-50s [BM83 RX] silences).
        #
        # iOS / Android / Windows all auto-initiate pairing when they
        # access an encrypted HID characteristic. Our job is just to
        # notice when encryption has been established and stop polling,
        # which this loop does via getattr(c, "paired").
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
        for c in conns:
            try:
                paired = getattr(c, "paired", None)
                if paired:
                    self._need_pairing_check = False
                    self._pair_attempts = 0
                    print("[BLE] Paired/encrypted")
                else:
                    # Not encrypted yet — bump attempt counter so we
                    # eventually stop polling even if the central never
                    # initiates pairing on its own.
                    self._pair_attempts += 1
                    dprint("[BLE] pair poll %d/%d: paired=%r"
                           % (self._pair_attempts, self._pair_attempt_limit, paired))
            except Exception as e:
                self._pair_attempts += 1
                dprint("[BLE] pair poll err (attempt %d):" % self._pair_attempts, e)

    def tick(self):
        if not self._ready or not self._ble:
            return
        now = time.monotonic()
        connected = bool(getattr(self._ble, "connected", False))
        if connected != self._was_connected:
            self._was_connected = connected
            if connected:
                self._on_connect()
            else:
                self._on_disconnect()
        if not connected:
            # Service a pending bond wipe in the disconnected/quiet
            # window before re-kicking advertising. _do_erase_bonds
            # handles its own start_adv on the way out.
            if self._erase_pending:
                self._do_erase_bonds()
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

    def _do_erase_bonds(self):
        """Perform the actual bond-store wipe. tick() only.

        Sequence is modelled on the recovered_source flow that worked
        on this hardware: stop advertising, GC, sleep, attempt erase
        via adafruit_ble first then _bleio.adapter as fallback, sleep,
        kick advertising back up. Every step is wrapped because any
        of them can throw on Nimble under memory pressure.
        """
        self._erase_pending = False
        self._last_erase_at = time.monotonic()
        print("[BLE] erase_bonds: running")
        # 1. Stop advertising so the radio isn't actively pumping
        try:
            self._stop_adv()
        except Exception as e:
            dprint("[BLE] erase_bonds stop_adv err:", e)
        # 2. Settle + GC so NVS write has headroom
        time.sleep(_BLE_STABILIZE_S)
        gc.collect()
        gc.collect()
        time.sleep(_BLE_STABILIZE_S)
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
        # 4. Settle again before re-advertising so the next central
        # sees a clean radio.
        time.sleep(_BLE_STABILIZE_S)
        gc.collect()
        try:
            self._start_adv(force=True)
        except Exception as e:
            dprint("[BLE] erase_bonds restart adv err:", e)

    # ---- HID sends ------------------------------------------------------

    def _send_ccc(self, code):
        if not self._ready or not self._ble or not self._cc:
            return
        if not getattr(self._ble, "connected", False):
            return
        now = time.monotonic()
        if (now - self._last_cc_at) < self._cc_min_interval_s:
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

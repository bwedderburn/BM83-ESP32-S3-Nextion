import time
import gc
from utils.common import dprint

# endregion
# Class: BleHid - Represents the BleHid class.
class BleHid:
# region BleHid
# BleHid class encapsulates functionality related to blehid. #
    # Loop through items
# Function: __init__ - Defines the behavior for `__init__`.
    def __init__(self, enabled, name):
# region __init__
    # __init__ handles   init   logic. #
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
    # setup handles setup logic. #
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
    # _stop_adv handles  stop adv logic. #
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
    # _start_adv handles  start adv logic. #
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
    # _on_connect handles  on connect logic. #
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
    # _on_disconnect handles  on disconnect logic. #
        print("[BLE] Disconnected")
        self._need_pairing_check = False
        self._pair_attempts = 0
        self._start_adv(force=True)

# endregion
    # Loop through items
# Function: _ensure_paired - Defines the behavior for `_ensure_paired`.
    def _ensure_paired(self):
# region _ensure_paired
    # _ensure_paired handles  ensure paired logic. #
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
    # erase_bonds handles erase bonds logic. #
        print("[BLE] Erase bonding requested")
    # Conditional check
        if not self._ready or not self._ble:
            print("[BLE] erase_bonding: Not ready or BLE not initialized")
            return
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
    # tick handles tick logic. #
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
    # _send_ccc handles  send ccc logic. #
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
    # volume handles volume logic. #
    # Conditional check
        if not self._CCC:
            return
        self._send_ccc(self._CCC.VOLUME_INCREMENT if up else self._CCC.VOLUME_DECREMENT)

# endregion
    # Loop through items
# Function: mute - Defines the behavior for `mute`.
    def mute(self):
# region mute
    # mute handles mute logic. #
    # Conditional check
        if not self._CCC:
            return
        self._send_ccc(self._CCC.MUTE)
import time
import gc
from utils.common import dprint

BLE_COUNTER_FILE = "/ble_counter.txt"


def _read_ble_counter():
    """Read the BLE counter from persistent storage."""
    try:
        with open(BLE_COUNTER_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return 0


def _write_ble_counter(count):
    """Write the BLE counter to persistent storage.
    Returns True if successful, False otherwise."""
    try:
        with open(BLE_COUNTER_FILE, "w") as f:
            f.write(str(count))
        return True
    except Exception as e:
        dprint("[BLE] counter write err:", e)
        return False
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
        self.base_name = name
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
        self._erase_pending = False
        self._erase_requested_at = 0.0
        self._erase_pending_since = 0.0
        self._last_erase_at = 0.0
        self._erase_cooldown_s = 3.0
        self._erase_debounce_s = 0.15
        self._erase_min_idle_s = 1.0
        self._erase_max_wait_s = 8.0
        self._last_conn_change_at = time.monotonic() - self._erase_min_idle_s

# endregion
        # Counter state for BLE name cycling on erase_bonds:
        # _memory_counter: Current counter value, always kept up-to-date regardless of persistence
        # _counter_persisted: True if last write to persistent storage succeeded
        # When filesystem is read-only, _memory_counter continues to increment while _counter_persisted=False
        self._memory_counter = 0
        self._counter_persisted = False
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
            # Initialize counter state from persistent storage if available
            counter = _read_ble_counter()
            self._memory_counter = counter
            # Assume filesystem is writable initially; will detect read-only on first erase_bonds
            self._counter_persisted = True

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
        self._last_conn_change_at = time.monotonic()
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
        self._last_conn_change_at = time.monotonic()
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
# Function: _update_ble_name - Defines the behavior for `_update_ble_name`.
    def _update_ble_name(self, counter):
# region _update_ble_name
    # _update_ble_name handles updating BLE name with counter.
    # Formats counter as 2-digit zero-padded number (e.g., 01, 02, ..., 99, 100).
    # For counters > 99, the full number is used without padding.
    # Conditional check
        if not self._ready or not self._ble:
            return
        self.name = "%s%02d" % (self.base_name, counter)
    # Try block to catch exceptions
        try:
            self._ble.name = self.name
            print("[BLE] Name updated to:", self.name)
    # Handle exceptions
        except Exception as e:
            dprint("[BLE] name update err:", e)

# endregion
# Function: _is_ble_idle - Defines the behavior for `_is_ble_idle`.
    def _is_ble_idle(self, now):
# region _is_ble_idle
        """Return True when BLE is idle enough for erase operations.

        Args:
            now: Current monotonic timestamp used for idle timing.
        """
        connected = bool(getattr(self._ble, "connected", False))
        advertising = bool(getattr(self._ble, "advertising", False))
        idle_wait_sufficient = (now - self._last_conn_change_at) >= self._erase_min_idle_s
        return (not connected) and idle_wait_sufficient and (not advertising)

# endregion
# Function: erase_bonds - Defines the behavior for `erase_bonds`.
    def erase_bonds(self):
# region erase_bonds
    # erase_bonds handles erase bonds logic. #
        print("[BLE] Erase bonding requested")
    # Conditional check
        if not self._ready or not self._ble:
            print("[BLE] erase_bonding: Not ready or BLE not initialized")
            return

        # Stop advertising first to reduce memory pressure
        self._stop_adv()

        # Aggressive GC before heavy operations
        # Two consecutive gc.collect() calls ensure thorough cleanup: the first pass may leave
        # objects in a "finalizing" state, and the second pass ensures those finalizers have
        # run and freed their memory. This is critical before memory-intensive BLE operations.
        gc.collect()
        gc.collect()

        # Disconnect all connections with individual error handling
    # Try block to catch exceptions
        try:
            conns = list(getattr(self._ble, "connections", []))
    # Loop through items
            for c in conns:
    # Try block to catch exceptions
                try:
                    c.disconnect()
    # Handle exceptions
                except Exception as e:
                    dprint("[BLE] disconnect err:", e)
    # Handle exceptions
        except Exception as e:
            dprint("[BLE] connections list err:", e)

# endregion
        # Another GC pass after disconnections
        gc.collect()

        ok = False
    # Try block to catch exceptions
        try:
    # Conditional check
            if hasattr(self._ble, "erase_bonding"):
                self._ble.erase_bonding()
                ok = True
    # Handle exceptions
        except Exception as e:
            dprint("[BLE] erase_bonding err:", e)
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
            except Exception as e:
                dprint("[BLE] _bleio.adapter.erase_bonding err:", e)
                ok = False

# endregion
    # Conditional check
        print("[BLE] erase_bonding:", "OK" if ok else "Unavailable on this build")

        # Increment counter and update BLE name only if erase succeeded
        if ok:
            # Read counter from appropriate source and increment
            # Use max() to prevent counter regression if persistent value is stale/corrupt
            if self._counter_persisted:
                persisted_counter = _read_ble_counter()
                counter = max(persisted_counter, self._memory_counter) + 1
            else:
                counter = self._memory_counter + 1

            # Always update memory counter to keep it in sync
            self._memory_counter = counter

            # Attempt to persist counter and track success
            self._counter_persisted = _write_ble_counter(counter)
            if not self._counter_persisted:
                print("[BLE] Using in-memory counter (filesystem read-only)")

            # Update BLE name with new counter value
            self._update_ble_name(counter)

        # Final GC pass before restarting advertising
        gc.collect()

        # Reset state
        self._adv_inhibit_until = 0.0
        self._adv_oom_count = 0
        self._need_pairing_check = False
        self._pair_attempts = 0

        # Restart advertising
        self._start_adv(force=True)

# endregion
    # Loop through items
# Function: request_erase_bonds - Defines the behavior for `request_erase_bonds`.
    def request_erase_bonds(self):
    # region request_erase_bonds
    # request_erase_bonds defers erase_bonds to the tick loop with cooldown. #
        now = time.monotonic()
    # Conditional check
        if (now - self._last_erase_at) < self._erase_cooldown_s:
            dprint("[BLE] erase_bonds throttled")
            return False
        # Prevent re-entry while an erase is already pending
        if self._erase_pending:
            return False
        self._erase_pending = True
        self._erase_requested_at = now
        self._erase_pending_since = now
        return True

# endregion
    # Loop through items
# Function: tick - Defines the behavior for `tick`.
    def tick(self):
# region tick
    # tick handles tick logic. #
    # Conditional check
        if not self._ready or not self._ble:
            return
        now = time.monotonic()
    # Conditional check
        if self._erase_pending and (now - self._erase_requested_at) >= self._erase_debounce_s:
            if self._is_ble_idle(now):
                self._erase_pending = False
                self._last_erase_at = now
                # Run erase inside try to avoid propagating BLE stack crashes
                try:
                    self.erase_bonds()
                except Exception as e:
                    dprint("[BLE] erase_bonds crash:", e)
            else:
                if (now - self._erase_pending_since) >= self._erase_max_wait_s:
                    reasons = []
                    if getattr(self._ble, "connected", False):
                        reasons.append("connected")
                    if getattr(self._ble, "advertising", False):
                        reasons.append("advertising")
                    if (now - self._last_conn_change_at) < self._erase_min_idle_s:
                        reasons.append("recent-conn")
                    dprint(
                        "[BLE] erase_bonds deferred too long, cancelling:",
                        ",".join(reasons)
                    )
                    self._erase_pending = False
        connected = bool(getattr(self._ble, "connected", False))
    # Conditional check
        if connected != self._was_connected:
            self._was_connected = connected
    # Conditional check
            if connected:
                self._on_connect()
            else:
                self._on_disconnect()
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

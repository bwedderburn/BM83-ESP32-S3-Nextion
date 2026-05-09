"""Name-cycling pattern — defeat Windows stale-handle reconnect.

The advertised BLE device name is rebuilt every boot from a base name
plus a counter persisted in /ble_counter.txt on the CIRCUITPY drive.
Each successful bond wipe bumps the counter, so the next advertisement
presents a brand-new identity to any central that may still hold a
cached MAC + role bond entry.

CIRCUITPY is read-only to the board when USB is mounted RW to the host
(typical during development). We handle that gracefully: the in-memory
counter still increments, name cycling still works for the rest of the
session, and persistence resumes the next time the FS is writable. We
also use max(persisted, in_memory) + 1 on bump so a corrupted persisted
value can never drag the counter backwards.

Naming format is base + "_" + decimal counter. First boot has counter
0, advertised name is just base. After first EBIND, counter is 1,
advertised name is "<base>_1". Etc.
"""
import time
from utils.common import dprint  # replace with your project's debug-print

_BLE_COUNTER_FILE = "/ble_counter.txt"


def read_ble_counter():
    try:
        with open(_BLE_COUNTER_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return 0


def write_ble_counter(count):
    try:
        with open(_BLE_COUNTER_FILE, "w") as f:
            f.write(str(count))
        return True
    except Exception as e:
        dprint("[BLE] counter write err:", e)
        return False


# Inside your BleHid.__init__:
#
#     self.base_name = name           # immutable, never reassigned
#     self.name = name                # rebuilt at setup() with suffix
#     self._memory_counter = 0
#     self._counter_persisted = False


# Inside BleHid.setup(), AFTER creating BLERadio() but BEFORE start_advertising:
def apply_persisted_counter(self):
    counter = read_ble_counter()
    self._memory_counter = counter
    self._counter_persisted = True
    if counter > 0:
        self.name = "%s_%d" % (self.base_name, counter)
    else:
        self.name = self.base_name
    self._ble.name = self.name


# Call this from _do_erase_bonds AFTER erase_bonding() succeeded
# and BEFORE you restart advertising:
def bump_counter_and_rename(self):
    persisted = read_ble_counter() if self._counter_persisted else 0
    counter = max(persisted, self._memory_counter) + 1
    self._memory_counter = counter
    self._counter_persisted = write_ble_counter(counter)
    if not self._counter_persisted:
        dprint("[BLE] counter: in-memory only (FS read-only)")
    self.name = "%s_%d" % (self.base_name, counter)
    try:
        self._ble.name = self.name
        print("[BLE] Name updated to:", self.name)
    except Exception as e:
        dprint("[BLE] name update err:", e)

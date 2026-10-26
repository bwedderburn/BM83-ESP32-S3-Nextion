# Preserve BLE bonds when updating the CircuitPython runtime

Normal `.py`/`.mpy` deployments to CIRCUITPY update application files. They do
not inherently erase the separate NimBLE NVS bond store. Runtime replacement
is different: CircuitPython's combined `firmware.bin` contains `0xFF` padding
between the bootloader, partition table and app. Writing it at address zero
overwrites the NVS region even without `erase-flash`/`--erase-all`.

The stock ESP32-S3 N8R8 CircuitPython 10.3.1 configuration retains three BLE
bonds and eight CCCD records. Adding hosts can evict an older bond. The reviewed
custom runtime raises these capacities to eight and 24. Increasing capacity
cannot recover previously evicted/erased keys; an affected host may need one
normal, target-specific repair. Do not erase every host's bonds or increment
the BLE name for ordinary disconnect/reconnect.

The pinned source/configuration recipe, constraints snapshot and reference
package versions are in [tools/circuitpython-runtime](../tools/circuitpython-runtime/README.md).
The recipe reproduces the reviewed configuration; it does not promise identical
image bytes across build hosts or timestamps.

## Validate an artifact without accessing hardware

```sh
python3 tools/update_circuitpython_runtime.py /absolute/artifacts/artifact-manifest.json
```

This is the default and launches no subprocess or serial access. The manifest
must declare `schema_version: 1`, kind `circuitpython-app-only`, the exact board
`espressif_esp32s3_devkitc_1_n8r8`, reviewed source pins, configuration 8/24,
8 MiB flash, `circuitpython-firmware.bin` plus SHA256, and
`partition-table.bin` plus SHA256. Extra provenance fields are allowed.
Required layout sections are:

```json
{
  "flash_size": 8388608,
  "app": {"file": "circuitpython-firmware.bin", "sha256": "...", "offset": 65536, "partition_size": 2097152},
  "partition_table": {"file": "partition-table.bin", "sha256": "...", "offset": 32768},
  "nvs": {"offset": 36864, "size": 20480},
  "otadata": {"offset": 57344, "size": 8192}
}
```

Validation checks the stock partition entries/MD5, file hashes, ESP32-S3 image
header, app descriptor, segment bounds, checksum and appended digest. Combined
images, bootloader images, unknown boards/layouts and oversized apps are refused.
Manifest provenance is not a cryptographic attestation: review the pinned build,
configuration and artifact manifest before approving a write.

## Explicit app-only write

First finish the artifact review, stop processes using the target serial port,
and place the expected unit in its ROM download loader manually. The tool does
not enter/reset the loader automatically. Use the observed chip **base MAC**
from the verified unit, not its derived BLE address.

```sh
python3 tools/update_circuitpython_runtime.py /absolute/artifacts/artifact-manifest.json \
  --write --esptool /absolute/reviewed/environment/bin/esptool \
  --port /dev/cu.EXACT-ROM-PORT --expected-mac AA:BB:CC:DD:EE:FF \
  --backup-dir /absolute/private/bm83-runtime-backups
```

The operator must substitute the observed port, base MAC and reviewed official
esptool 5.6.0 executable. The tool uses fixed argument lists without a shell,
no hard reset or automatic application boot, and bounded command timeouts.
Esptool may soft-return its RAM stub to the ROM loader between commands.
It permits esptool's packaged
temporary RAM stub for efficient bulk transfers; loading that stub does not
erase flash. ROM-only reads use small transactions and are unsuitable for the
two full 8 MiB reads. Before writing it checks the MAC, saves all 8 MiB
in a new private `0700` directory with `0600` files, compares the candidate's
partition-table prefix byte-for-byte with the device, and examines OTA metadata.
Only erased OTA metadata or CRC-valid, nontransitional metadata selecting
`ota_0` is accepted. Other slots/unknown states are refused; the tool never
rewrites OTA metadata or changes slot selection. It rechecks the MAC immediately
before the write and flashes a private copy of the previously validated bytes.
An erased record permits the
existing bootloader's fallback behavior, not a new boot-selection guarantee.

The sole flash write is the app at `0x10000`, within its 2 MiB partition. A
second full read verifies the app's SHA256 and every byte outside the app
partition, including NVS, bootloader, OTA data and CIRCUITPY/user filesystem.
Backups contain bonding keys and other private data: keep them private and
never commit/upload them. `report.json` records verification without exposing
their contents.

On a pre-write guard failure there is no app write. A write/readback failure retains
the private backup for review and does not attempt an automatic restore.
The unit remains in download-loader mode (possibly running the RAM stub);
after successful verification, use the
physical RESET button and verify the runtime/version and BLE reconnection.
Do not substitute the combined `firmware.bin`, erase flash, rewrite address
zero, or change the partition layout.

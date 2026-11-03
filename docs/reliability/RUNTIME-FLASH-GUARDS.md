# Guarded native runtime application write

`tools/update_circuitpython_runtime.py` still defaults to offline validation.
Nothing here establishes physical deployment authorization, device acceptance,
or radio reliability. A live write requires the owner's specific runtime
approval, a manually selected ROM-loader target, `--write`, and a private scoped
`--approval-file`. The tool never enters the loader, resets, erases all flash,
changes eFuses, rewrites the partition table, or automatically restores firmware.

## Scope record

The operator prepares this JSON **outside Git**, using the exact reviewed
artifact manifest, application bytes, absolute esptool executable and target.
The approval file must belong to the operator and have no group/other access
(`0600` is recommended). Values below are a schema example, not approval:

```json
{
  "schema_version": 1,
  "kind": "bm83-runtime-app-only-approval",
  "approved": true,
  "board": "espressif_esp32s3_devkitc_1_n8r8",
  "manifest_sha256": "<SHA256 of the exact artifact-manifest.json bytes>",
  "app_sha256": "<SHA256 of circuitpython-firmware.bin>",
  "port": "<verified explicit ROM-loader port>",
  "expected_mac": "<verified uppercase chip base MAC>",
  "flash_size": 8388608,
  "app_offset": 65536,
  "app_partition_size": 2097152,
  "preserve_outside_app": true,
  "no_reset": true,
  "esptool": {
    "path": "<absolute reviewed executable path>",
    "version": "5.6.0",
    "sha256": "<SHA256 of that executable>"
  }
}
```

Pass its absolute path with `--approval-file` alongside the existing explicit
`--esptool`, `--port`, `--expected-mac`, `--backup-dir` and `--write` arguments.
Before the sole write attempt, the updater exclusively creates a private
`<approval filename>.used` marker. Success or failure consumes that record;
review the retained evidence and obtain a newly scoped record for another
attempt. Never delete a marker to bypass this gate.

The executable file SHA256 and actual `esptool version` output must both match
the record and version 5.6.0. A standalone official executable provides a useful
single-file fingerprint. A Python launcher hash alone does not attest to all
its imported packages; its environment still needs independent provenance.

## Pre-write and readback gates

1. Preserve existing app-only manifest/image, board, source, partition and OTA
   checks. Use fixed argument lists, no shell, no force/erase flags, and
   `--before no-reset --after no-reset` on every device command.
2. Read the chip base MAC, `flash-id`, and `get-security-info`. Require exactly
   8 MB, ESP32-S3 chip ID 9, Secure Boot disabled and Flash Encryption disabled.
   Missing, contradictory, enabled or unknown results refuse the write.
3. Read all 8 MiB **twice in independent invocations** into separate new private
   files. Require both full lengths and byte-for-byte equality before writing.
   Validate the device partition-table prefix and active OTA selection.
4. Extract the original app image from its 2 MiB partition, validate its ESP
   header, descriptor, bounds, checksum and appended SHA256, and require the
   remaining partition bytes to be erased (`0xFF`). Save both that exact
   validated image and the entire original app partition, each with hashes.
   An invalid/unavailable rollback image refuses deployment.
5. Make and reread a private copy of the already validated candidate. Recheck
   executable hash/version, chip MAC, flash size and security immediately before
   consuming approval and attempting the app-only write at `0x10000`.
6. Read all 8 MiB again. Require the written app hash and **every byte outside
   the complete 2 MiB app partition** to match the pre-write backup. This covers
   bootloader, partition table, NVS/bonds, OTA metadata, other slots and user FAT.

All backups, rollback files, marker and report stay private. Full backups contain
bonding keys and device data and must not be committed or uploaded. The tool
leaves the unit in download-loader mode (possibly using the packaged RAM stub)
and never automatically boots it. Owner-controlled reset, unchanged device-file
verification, native-heap diagnostics, fresh metadata/control checks and the
30-minute stability run are separate gates after a successful readback.

The security/flash output parsing follows the official
[esptool 5.6.0 implementation](https://github.com/espressif/esptool/blob/v5.6.0/esptool/cmds.py).

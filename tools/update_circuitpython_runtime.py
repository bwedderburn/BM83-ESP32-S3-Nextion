#!/usr/bin/env python3
"""Offline validation by default; guarded app-only ESP32-S3 runtime update."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import tempfile
import zlib


BOARD = "espressif_esp32s3_devkitc_1_n8r8"
FLASH_SIZE = 0x800000
APP_OFFSET, APP_SIZE = 0x10000, 0x200000
TABLE_OFFSET = 0x8000
NVS_OFFSET, NVS_SIZE = 0x9000, 0x5000
OTA_OFFSET, OTA_SIZE = 0xE000, 0x2000
PINS = {
    "circuitpython": "c9dee12beed76e4ffa11d2d6d99ff104fc976c3a",
    "esp_idf": "2b900d1222cfce5dfa340ed99375af69ec1ee192",
    "esp_nimble": "7075927f97c648af650a288e94a8c80dd7f00c27",
}
PARTITIONS = [
    ("nvs", 1, 2, NVS_OFFSET, NVS_SIZE),
    ("otadata", 1, 0, OTA_OFFSET, OTA_SIZE),
    ("ota_0", 0, 0x10, APP_OFFSET, APP_SIZE),
    ("ota_1", 0, 0x11, 0x210000, 0x200000),
    ("uf2", 0, 0, 0x410000, 0x40000),
    ("user_fs", 1, 0x81, 0x450000, 0x3B0000),
]


class ValidationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def validate_partition_table(data):
    """Accept only the reviewed stock 8MiB layout and its MD5 entry."""
    require(32 <= len(data) <= 0x1000 and len(data) % 32 == 0,
            "Invalid partition-table length")
    entries = []
    digest_at = None
    for offset in range(0, len(data), 32):
        row = data[offset:offset + 32]
        if row[:2] == b"\xeb\xeb":
            require(row[2:16] == b"\xff" * 14, "Invalid partition MD5 marker")
            require(hashlib.md5(data[:offset], usedforsecurity=False).digest() == row[16:],
                    "Partition-table MD5 mismatch")
            digest_at = offset
            break
        require(row[:2] == b"\xaa\x50", "Missing/invalid partition entry")
        _, kind, subtype, start, size, label, flags = struct.unpack("<HBBII16sI", row)
        try:
            name = label.split(b"\0", 1)[0].decode("ascii")
        except UnicodeError as exc:
            raise ValidationError("Invalid partition name") from exc
        require(flags == 0 and size > 0 and start + size <= FLASH_SIZE,
                "Unsupported partition flags or bounds")
        entries.append((name, kind, subtype, start, size))
    require(digest_at is not None, "Partition-table MD5 entry required")
    require(data[digest_at + 32:] == b"\xff" * (len(data) - digest_at - 32),
            "Unexpected partition-table trailing bytes")
    require(entries == PARTITIONS, "Partition layout is not the reviewed stock N8R8 layout")
    for left, right in zip(entries, entries[1:]):
        require(left[3] + left[4] <= right[3], "Overlapping partitions")
    return entries


def validate_app_image(data):
    """Check an unsigned ESP32-S3 application image, not a merged flash image."""
    require(24 <= len(data) <= APP_SIZE, "Application image exceeds its 2MiB partition")
    require(data[0] == 0xE9 and 1 <= data[1] <= 16, "Invalid ESP application header")
    require(struct.unpack_from("<H", data, 12)[0] == 9, "Image is not for ESP32-S3")
    require(data[3] >> 4 == 3, "Image header does not declare 8MiB flash")
    require(data[23] == 1, "Appended ESP image SHA256 required")
    position, checksum = 24, 0xEF
    for index in range(data[1]):
        require(position + 8 <= len(data), "Truncated image segment header")
        _, size = struct.unpack_from("<II", data, position)
        position += 8
        require(size > 0 and position + size <= len(data), "Image segment outside file bounds")
        segment = data[position:position + size]
        if index == 0:
            require(size >= 256 and segment[:4] == b"\x32\x54\xcd\xab",
                    "Application descriptor missing; bootloader/full image rejected")
        for value in segment:
            checksum ^= value
        position += size
    checksum_at = ((position + 16) // 16) * 16 - 1
    require(checksum_at + 33 == len(data), "Trailing/padded/merged image is not app-only")
    require(data[position:checksum_at] == b"\0" * (checksum_at - position),
            "Unexpected image checksum padding")
    require(data[checksum_at] == checksum, "ESP image checksum mismatch")
    require(hashlib.sha256(data[:checksum_at + 1]).digest() == data[checksum_at + 1:],
            "ESP image appended SHA256 mismatch")


def artifact_file(folder, section, filename):
    require(isinstance(section, dict) and section.get("file") == filename,
            "Expected app-only artifact filename: " + filename)
    path = folder / filename
    require(path.is_file() and not path.is_symlink(), "Artifact must be a regular local file")
    data = path.read_bytes()
    require(section.get("sha256") == sha256(data), "Artifact SHA256 mismatch: " + filename)
    return path, data


def validate_manifest(path):
    path = Path(path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(manifest, dict), "Manifest must be a JSON object")
    require(type(manifest.get("schema_version")) is int and manifest["schema_version"] == 1 and
            manifest.get("kind") == "circuitpython-app-only", "Unsupported manifest kind/version")
    require(manifest.get("board") == BOARD, "Unknown/unreviewed board")
    require(manifest.get("sources") == PINS, "Source pins do not match the reviewed runtime")
    require(manifest.get("flash_size") == FLASH_SIZE, "Flash size must be 8MiB")
    config = manifest.get("configuration", {})
    require(isinstance(config, dict), "Invalid configuration section")
    require(config.get("CONFIG_BT_NIMBLE_MAX_BONDS") == 8 and
            config.get("CONFIG_BT_NIMBLE_MAX_CCCDS") == 24, "Expected 8 bonds and 24 CCCDs")
    app = manifest.get("app", {})
    table = manifest.get("partition_table", {})
    require(isinstance(app, dict) and isinstance(table, dict), "Invalid artifact sections")
    require(app.get("offset") == APP_OFFSET and app.get("partition_size") == APP_SIZE,
            "Only the reviewed app partition at 0x10000 may be written")
    require(table.get("offset") == TABLE_OFFSET, "Unexpected partition-table offset")
    require(manifest.get("nvs") == {"offset": NVS_OFFSET, "size": NVS_SIZE},
            "Unexpected NVS layout")
    require(manifest.get("otadata") == {"offset": OTA_OFFSET, "size": OTA_SIZE},
            "Unexpected OTA metadata layout")
    app_path, image = artifact_file(path.parent, app, "circuitpython-firmware.bin")
    _, partition_table = artifact_file(path.parent, table, "partition-table.bin")
    validate_partition_table(partition_table)
    validate_app_image(image)
    return manifest, app_path, image, partition_table


def validate_ota_metadata(data):
    """Conservatively allow erased metadata or confirmed selection of ota_0."""
    require(len(data) == OTA_SIZE, "Truncated OTA metadata")
    sequences = []
    for offset in (0, 0x1000):
        sector = data[offset:offset + 0x1000]
        if sector == b"\xff" * 0x1000:
            continue
        require(sector[32:] == b"\xff" * (0x1000 - 32), "Unknown OTA sector contents")
        sequence, label, state, crc = struct.unpack("<I20sII", sector[:32])
        require(label in (b"\0" * 20, b"\xff" * 20), "Unknown OTA label")
        require(0 < sequence < 0xFFFFFFFF and state in (2, 0xFFFFFFFF),
                "Unknown/transitional/invalid OTA state")
        require(zlib.crc32(sector[:4], 0xFFFFFFFF) & 0xFFFFFFFF == crc,
                "OTA selection CRC mismatch")
        sequences.append(sequence)
    if not sequences:
        return "erased"
    require((max(sequences) - 1) % 2 == 0, "Active OTA slot is not ota_0; refusing write")
    return "known-ota_0"


def normalize_mac(value):
    require(isinstance(value, str) and re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", value),
            "Expected chip base MAC must use six colon-separated bytes")
    return value.upper()


def execute(argv, timeout):
    # Operator-supplied absolute esptool executable, fixed argv, no shell.
    result = subprocess.run(argv, check=True, stdout=subprocess.PIPE,  # nosec B603
                            stderr=subprocess.STDOUT, text=True, timeout=timeout)
    return result.stdout


def private_backup_directory(parent):
    parent = Path(parent).expanduser().absolute()
    require(not parent.is_symlink(), "Backup parent must not be a symlink")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(parent.is_dir() and stat.S_IMODE(parent.stat().st_mode) & 0o077 == 0,
            "Backup parent must be private (0700)")
    require(not hasattr(os, "getuid") or parent.stat().st_uid == os.getuid(),
            "Backup parent must belong to the current user")
    return Path(tempfile.mkdtemp(prefix="bm83-runtime-", dir=str(parent)))


def private_file(folder, name):
    path = folder / name
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    return path


def check_device_mac(base, run, expected_mac):
    identity = run(base + ["read-mac"], timeout=30)
    matches = set(re.findall(r"(?mi)^\s*(?:Base )?MAC:\s*((?:[0-9a-f]{2}:){5}[0-9a-f]{2})\b", identity))
    require({value.upper() for value in matches} == {expected_mac}, "Connected chip base MAC mismatch")


def update_runtime(manifest_path, esptool, port, expected_mac, backup_parent, runner=None):
    _, _, image, table = validate_manifest(manifest_path)
    expected_mac = normalize_mac(expected_mac)
    tool = Path(esptool).expanduser()
    require(tool.is_absolute() and tool.is_file() and os.access(str(tool), os.X_OK),
            "An explicitly reviewed absolute esptool executable is required")
    require(isinstance(port, str) and port and not port.startswith("-") and
            not any(char.isspace() or ord(char) < 32 for char in port), "Invalid explicit serial port")
    run = runner or execute
    base = [str(tool), "--chip", "esp32s3", "--port", port, "--baud", "921600",
            "--before", "no-reset", "--after", "no-reset"]
    check_device_mac(base, run, expected_mac)
    folder = private_backup_directory(backup_parent)
    before_path = private_file(folder, "flash-before.bin")
    after_path = private_file(folder, "flash-after.bin")
    report_path = private_file(folder, "report.json")
    report = {"board": BOARD, "expected_mac": expected_mac, "app_sha256": sha256(image),
              "write_attempted": False, "verified": False}
    try:
        run(base + ["read-flash", "0x0", "0x800000", str(before_path),
                    "--flash-size", "8MB"], timeout=240)
        before_path.chmod(0o600)
        before = before_path.read_bytes()
        require(len(before) == FLASH_SIZE, "Full 8MiB backup incomplete")
        require(before[TABLE_OFFSET:TABLE_OFFSET + len(table)] == table,
                "Device partition-table prefix differs from candidate; no write performed")
        report["ota_guard"] = validate_ota_metadata(before[OTA_OFFSET:OTA_OFFSET + OTA_SIZE])
        report["before_sha256"] = sha256(before)
        # Flash the bytes validated above, not an artifact that another build
        # could replace between validation and this write.
        app_copy = private_file(folder, "app-validated.bin")
        app_copy.write_bytes(image)
        check_device_mac(base, run, expected_mac)
        report["write_attempted"] = True
        run(base + ["write-flash", "--flash-size", "8MB", "0x10000", str(app_copy)], timeout=180)
        run(base + ["read-flash", "0x0", "0x800000", str(after_path),
                    "--flash-size", "8MB"], timeout=240)
        after_path.chmod(0o600)
        after = after_path.read_bytes()
        require(len(after) == FLASH_SIZE, "Full post-write readback incomplete")
        require(sha256(after[APP_OFFSET:APP_OFFSET + len(image)]) == sha256(image),
                "Application readback SHA256 mismatch")
        require(before[:APP_OFFSET] == after[:APP_OFFSET] and
                before[APP_OFFSET + APP_SIZE:] == after[APP_OFFSET + APP_SIZE:],
                "Flash outside the app partition changed; keep backups for review")
        report.update(verified=True, after_sha256=sha256(after), outside_app_unchanged=True)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report["failure"] = str(exc)
        raise ValidationError(str(exc) + "; private backup retained at " + str(folder)) from exc
    finally:
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return {"mode": "app-only-write", "backup_directory": str(folder),
            "verified": True, "physical_reset_required": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--write", action="store_true", help="Explicitly authorize the guarded app-only write")
    parser.add_argument("--esptool", help="Reviewed absolute executable path; required with --write")
    parser.add_argument("--port", help="Explicit ROM-loader serial port; required with --write")
    parser.add_argument("--expected-mac", help="Expected chip BASE MAC, not its BLE-derived address")
    parser.add_argument("--backup-dir", type=Path, default=Path.home() / ".bm83-runtime-backups")
    args = parser.parse_args(argv)
    try:
        manifest, _, image, _ = validate_manifest(args.manifest)
        if args.write:
            require(args.esptool and args.port and args.expected_mac,
                    "--write requires --esptool, --port and --expected-mac")
            result = update_runtime(args.manifest, args.esptool, args.port,
                                    args.expected_mac, args.backup_dir)
        else:
            result = {"mode": "offline-validation", "board": manifest["board"],
                      "app_bytes": len(image), "app_sha256": sha256(image), "write_performed": False}
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print("Runtime update refused/failed: " + str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

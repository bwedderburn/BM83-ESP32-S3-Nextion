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
ESPTOOL_VERSION = "5.6.0"
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


def approval_record(path, manifest_path, image, tool, port, expected_mac):
    """Bind a private, explicit approval to these exact bytes and target/tool."""
    require(path is not None, "An explicit private --approval-file is required")
    path = Path(path).expanduser()
    require(path.is_file() and not path.is_symlink(), "Approval must be a regular local file")
    require(stat.S_IMODE(path.stat().st_mode) & 0o077 == 0,
            "Approval file must be private (0600)")
    require(not hasattr(os, "getuid") or path.stat().st_uid == os.getuid(),
            "Approval file must belong to the current user")
    require(not path.with_name(path.name + ".used").exists(), "Approval already consumed by a write attempt")
    approval = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(approval, dict) and type(approval.get("schema_version")) is int
            and approval["schema_version"] == 1
            and approval.get("kind") == "bm83-runtime-app-only-approval"
            and approval.get("approved") is True, "Explicit scoped approval missing")
    expected = {"board": BOARD, "manifest_sha256": sha256(Path(manifest_path).read_bytes()),
                "app_sha256": sha256(image), "port": port, "expected_mac": expected_mac,
                "flash_size": FLASH_SIZE, "app_offset": APP_OFFSET, "app_partition_size": APP_SIZE,
                "preserve_outside_app": True, "no_reset": True}
    require(all(approval.get(name) == value and type(approval.get(name)) is type(value)
                for name, value in expected.items()), "Approval scope/target/artifact mismatch")
    tool_approval = approval.get("esptool")
    require(isinstance(tool_approval, dict) and tool_approval.get("path") == str(tool)
            and tool_approval.get("version") == ESPTOOL_VERSION
            and tool_approval.get("sha256") == sha256(tool.read_bytes()),
            "Approval esptool path/version/SHA256 mismatch")
    return approval


def check_tool(tool, run, expected_hash):
    require(not tool.is_symlink() and sha256(tool.read_bytes()) == expected_hash,
            "Reviewed esptool executable changed")
    version = run([str(tool), "version"], timeout=15)
    versions = re.findall(r"(?mi)^\s*(?:esptool(?:\.py)?\s+v)?(\d+\.\d+\.\d+)\s*$", version)
    require(bool(versions) and set(versions) == {ESPTOOL_VERSION},
            "Actual esptool version must be exactly 5.6.0")


def check_chip_security(base, run):
    """Read-only checks; absent/ambiguous security information fails closed."""
    flash = run(base + ["flash-id"], timeout=30)
    sizes = re.findall(r"(?mi)^\s*Detected flash size:\s*(\S+)\s*$", flash)
    require(sizes == ["8MB"], "Connected chip must report exactly 8MB flash")
    security = run(base + ["get-security-info"], timeout=30)
    for label, expected in (("Chip ID", "9"), ("Secure Boot", "Disabled"),
                            ("Flash Encryption", "Disabled")):
        values = re.findall(r"(?mi)^\s*" + re.escape(label) + r":\s*(\S+)\s*$", security)
        require(values == [expected], "Unsupported/unknown chip security state: " + label)
    return {"chip_id": 9, "flash_size": FLASH_SIZE, "secure_boot": False, "flash_encryption": False}


def extract_original_app(partition):
    """Extract an exact validated unsigned rollback image from its partition."""
    require(len(partition) == APP_SIZE, "Original app partition incomplete")
    require(partition[0] == 0xE9 and 1 <= partition[1] <= 16,
            "Original app header invalid; rollback unavailable")
    position = 24
    for _ in range(partition[1]):
        require(position + 8 <= APP_SIZE, "Original app segment header truncated")
        size = struct.unpack_from("<I", partition, position + 4)[0]
        position += 8 + size
        require(size > 0 and position <= APP_SIZE, "Original app segment exceeds partition")
    end = ((position + 16) // 16) * 16 - 1 + 33
    require(end <= APP_SIZE, "Original app digest exceeds partition")
    image = partition[:end]
    validate_app_image(image)
    require(partition[end:] == b"\xff" * (APP_SIZE - end),
            "Original app has unsupported trailing data; rollback refused")
    return image


def update_runtime(manifest_path, esptool, port, expected_mac, backup_parent, runner=None, approval_path=None):
    _, _, image, table = validate_manifest(manifest_path)
    expected_mac = normalize_mac(expected_mac)
    tool = Path(esptool).expanduser()
    require(tool.is_absolute() and tool.is_file() and not tool.is_symlink() and os.access(str(tool), os.X_OK),
            "An explicitly reviewed absolute esptool executable is required")
    require(isinstance(port, str) and port and not port.startswith("-") and
            not any(char.isspace() or ord(char) < 32 for char in port), "Invalid explicit serial port")
    run = runner or execute
    approval = approval_record(approval_path, manifest_path, image, tool, port, expected_mac)
    tool_hash = approval["esptool"]["sha256"]
    check_tool(tool, run, tool_hash)
    base = [str(tool), "--chip", "esp32s3", "--port", port, "--baud", "921600",
            "--before", "no-reset", "--after", "no-reset"]
    check_device_mac(base, run, expected_mac)
    security = check_chip_security(base, run)
    folder = private_backup_directory(backup_parent)
    before_path = private_file(folder, "flash-before.bin")
    confirm_path = private_file(folder, "flash-before-confirm.bin")
    after_path = private_file(folder, "flash-after.bin")
    report_path = private_file(folder, "report.json")
    report = {"board": BOARD, "expected_mac": expected_mac, "app_sha256": sha256(image),
              "write_attempted": False, "verified": False, "chip_security": security,
              "esptool_version": ESPTOOL_VERSION, "esptool_sha256": tool_hash,
              "approval_sha256": sha256(Path(approval_path).read_bytes())}
    try:
        run(base + ["read-flash", "0x0", "0x800000", str(before_path),
                    "--flash-size", "8MB"], timeout=240)
        before_path.chmod(0o600)
        before = before_path.read_bytes()
        require(len(before) == FLASH_SIZE, "Full 8MiB backup incomplete")
        run(base + ["read-flash", "0x0", "0x800000", str(confirm_path),
                    "--flash-size", "8MB"], timeout=240)
        confirm_path.chmod(0o600)
        confirmed = confirm_path.read_bytes()
        require(len(confirmed) == FLASH_SIZE and confirmed == before,
                "Independent full pre-write backups differ/incomplete; no write performed")
        report["independent_backups_identical"] = True
        require(before[TABLE_OFFSET:TABLE_OFFSET + len(table)] == table,
                "Device partition-table prefix differs from candidate; no write performed")
        report["ota_guard"] = validate_ota_metadata(before[OTA_OFFSET:OTA_OFFSET + OTA_SIZE])
        report["before_sha256"] = sha256(before)
        rollback = extract_original_app(before[APP_OFFSET:APP_OFFSET + APP_SIZE])
        rollback_path = private_file(folder, "rollback-app-validated.bin")
        rollback_path.write_bytes(rollback)
        require(rollback_path.read_bytes() == rollback, "Original app rollback copy verification failed")
        report["rollback_app"] = {"file": rollback_path.name, "sha256": sha256(rollback),
                                  "bytes": len(rollback), "offset": APP_OFFSET,
                                  "offline_validated": True}
        original_partition = before[APP_OFFSET:APP_OFFSET + APP_SIZE]
        rollback_partition_path = private_file(folder, "rollback-app-partition.bin")
        rollback_partition_path.write_bytes(original_partition)
        require(rollback_partition_path.read_bytes() == original_partition,
                "Original full app partition copy verification failed")
        report["rollback_app_partition"] = {"file": rollback_partition_path.name, "bytes": APP_SIZE,
                                            "sha256": sha256(original_partition), "offset": APP_OFFSET}
        # Flash the bytes validated above, not an artifact that another build
        # could replace between validation and this write.
        app_copy = private_file(folder, "app-validated.bin")
        app_copy.write_bytes(image)
        require(app_copy.read_bytes() == image, "Private candidate copy verification failed")
        check_tool(tool, run, tool_hash)
        check_device_mac(base, run, expected_mac)
        require(check_chip_security(base, run) == security, "Chip security changed before write")
        # A failed write/readback still needs review and a fresh scoped approval.
        approval_marker = Path(approval_path).with_name(Path(approval_path).name + ".used")
        marker_fd = os.open(str(approval_marker), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(marker_fd, "w", encoding="utf-8") as handle:
            json.dump({"approval_sha256": report["approval_sha256"], "backup_directory": str(folder),
                       "app_sha256": sha256(image)}, handle)
            handle.flush()
            os.fsync(handle.fileno())
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
    parser.add_argument("--approval-file", type=Path, help="Private approval binding exact artifact, tool and target")
    parser.add_argument("--backup-dir", type=Path, default=Path.home() / ".bm83-runtime-backups")
    args = parser.parse_args(argv)
    try:
        manifest, _, image, _ = validate_manifest(args.manifest)
        if args.write:
            require(args.esptool and args.port and args.expected_mac and args.approval_file,
                    "--write requires --esptool, --port, --expected-mac and --approval-file")
            result = update_runtime(args.manifest, args.esptool, args.port,
                                    args.expected_mac, args.backup_dir, approval_path=args.approval_file)
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

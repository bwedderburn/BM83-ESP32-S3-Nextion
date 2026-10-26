"""Offline updater guards and a fake flash round trip; never access hardware."""
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import struct
from unittest import mock
import zlib

import pytest


PATH = Path(__file__).parents[1] / "tools/update_circuitpython_runtime.py"
SPEC = importlib.util.spec_from_file_location("runtime_updater", PATH)
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)
MAC = "AA:BB:CC:DD:EE:FF"


def app_image():
    header = bytearray(24)
    header[0], header[1], header[3], header[12], header[23] = 0xE9, 1, 0x3F, 9, 1
    segment = bytearray(256)
    segment[:4] = b"\x32\x54\xcd\xab"
    image = bytes(header) + struct.pack("<II", 0x3C000020, len(segment)) + bytes(segment)
    checksum = 0xEF
    for value in segment:
        checksum ^= value
    image += b"\0" * ((15 - len(image)) % 16) + bytes((checksum,))
    return image + hashlib.sha256(image).digest()


def partition_table(entries=None):
    data = b""
    for name, kind, subtype, offset, size in entries or updater.PARTITIONS:
        data += struct.pack("<HBBII16sI", 0x50AA, kind, subtype, offset, size,
                            name.encode().ljust(16, b"\0"), 0)
    data += b"\xeb\xeb" + b"\xff" * 14 + hashlib.md5(data, usedforsecurity=False).digest()
    return data.ljust(0xC00, b"\xff")


@pytest.fixture
def artifact(tmp_path):
    image, table = app_image(), partition_table()
    (tmp_path / "circuitpython-firmware.bin").write_bytes(image)
    (tmp_path / "partition-table.bin").write_bytes(table)
    manifest = {
        "schema_version": 1, "kind": "circuitpython-app-only", "board": updater.BOARD,
        "sources": dict(updater.PINS), "flash_size": updater.FLASH_SIZE,
        "configuration": {"CONFIG_BT_NIMBLE_MAX_BONDS": 8, "CONFIG_BT_NIMBLE_MAX_CCCDS": 24},
        "app": {"file": "circuitpython-firmware.bin", "sha256": updater.sha256(image),
                "offset": updater.APP_OFFSET, "partition_size": updater.APP_SIZE},
        "partition_table": {"file": "partition-table.bin", "sha256": updater.sha256(table),
                            "offset": updater.TABLE_OFFSET},
        "nvs": {"offset": updater.NVS_OFFSET, "size": updater.NVS_SIZE},
        "otadata": {"offset": updater.OTA_OFFSET, "size": updater.OTA_SIZE},
    }
    path = tmp_path / "artifact-manifest.json"
    path.write_text(json.dumps(manifest))
    return path, manifest


class FakeFlasher:
    def __init__(self, table):
        self.flash = bytearray(b"\xff" * updater.FLASH_SIZE)
        self.flash[updater.TABLE_OFFSET:updater.TABLE_OFFSET + len(table)] = table
        self.flash[updater.NVS_OFFSET:updater.NVS_OFFSET + updater.NVS_SIZE] = b"\xA5" * updater.NVS_SIZE
        self.calls = []
        self.mac = MAC
        self.corrupt_after = None
        self.reads = 0

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        assert timeout <= 240
        assert argv[argv.index("--before") + 1] == "no-reset"
        assert argv[argv.index("--after") + 1] == "no-reset"
        # Bulk 8MiB operations need esptool's packaged RAM stub. ROM-only
        # reads use tiny transactions and are unsuitable for these backups.
        assert "--no-stub" not in argv
        if "read-mac" in argv:
            return "MAC: " + self.mac.lower() + "\n"
        if "read-flash" in argv:
            index = argv.index("read-flash")
            assert argv[index + 1:index + 3] == ["0x0", "0x800000"]
            destination = Path(argv[index + 3])
            assert stat.S_IMODE(destination.stat().st_mode) == 0o600
            assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
            self.reads += 1
            if self.reads == 2 and self.corrupt_after is not None:
                self.flash[self.corrupt_after] ^= 1
            destination.write_bytes(self.flash)
            return "Read complete"
        if "write-flash" in argv:
            index = argv.index("write-flash")
            assert argv[index + 1:index + 4] == ["--flash-size", "8MB", "0x10000"]
            image = Path(argv[index + 4]).read_bytes()
            self.flash[updater.APP_OFFSET:updater.APP_OFFSET + len(image)] = image
            return "Write complete"
        pytest.fail("Unexpected hardware command: " + repr(argv))


def write_args(artifact, tmp_path, fake):
    path, _ = artifact
    executable = tmp_path / "reviewed esptool"
    executable.write_text("not executed by tests")
    executable.chmod(0o700)
    return (path, executable, "/dev/cu.test-ROM", MAC, tmp_path / "private-backups", fake)


def test_default_cli_and_import_never_launch_hardware(artifact, capsys):
    with mock.patch.object(updater.subprocess, "run", side_effect=AssertionError("hardware touched")):
        assert updater.main([str(artifact[0])]) == 0
        SPEC.loader.exec_module(updater)
    assert '"write_performed": false' in capsys.readouterr().out


@pytest.mark.parametrize("field,value", [
    ("board", "unknown-s3"), ("kind", "full-flash"), ("flash_size", 0x1000000),
    ("schema_version", True), ("sources", {}),
    ("configuration", {"CONFIG_BT_NIMBLE_MAX_BONDS": 3, "CONFIG_BT_NIMBLE_MAX_CCCDS": 8}),
    ("app", {"file": "firmware.bin"}),
    ("nvs", {"offset": 0x10000, "size": 0x5000}),
])
def test_unreviewed_manifest_refused_offline(artifact, field, value):
    path, manifest = artifact
    manifest[field] = value
    path.write_text(json.dumps(manifest))
    with pytest.raises(updater.ValidationError):
        updater.validate_manifest(path)


def test_hash_and_app_offset_guards(artifact):
    path, manifest = artifact
    (path.parent / "circuitpython-firmware.bin").write_bytes(b"corrupted")
    with pytest.raises(updater.ValidationError, match="SHA256"):
        updater.validate_manifest(path)
    (path.parent / "circuitpython-firmware.bin").write_bytes(app_image())
    manifest["app"]["offset"] = 0
    path.write_text(json.dumps(manifest))
    with pytest.raises(updater.ValidationError, match="0x10000"):
        updater.validate_manifest(path)


def test_wrong_or_overlapping_partition_layout_rejected():
    entries = list(updater.PARTITIONS)
    name, kind, subtype, offset, size = entries[2]
    entries[2] = (name, kind, subtype, updater.NVS_OFFSET, size)
    with pytest.raises(updater.ValidationError, match="layout"):
        updater.validate_partition_table(partition_table(entries))
    corrupted = bytearray(partition_table())
    corrupted[20] ^= 1
    with pytest.raises(updater.ValidationError, match="MD5"):
        updater.validate_partition_table(corrupted)


@pytest.mark.parametrize("change", ["oversize", "merged", "wrong-chip", "bootloader", "checksum"])
def test_non_app_images_rejected(change):
    data = bytearray(app_image())
    if change == "oversize":
        data.extend(b"\xff" * updater.APP_SIZE)
    elif change == "merged":
        data.extend(b"\xff" * 0x10000)
    elif change == "wrong-chip":
        data[12] = 0
    elif change == "bootloader":
        data[32:36] = b"\0" * 4
    else:
        data[100] ^= 1
    with pytest.raises(updater.ValidationError):
        updater.validate_app_image(data)


def ota_sector(sequence, state=2):
    # IDF's esp_rom_crc32_le(UINT32_MAX, little-endian ota_seq, 4).
    raw = struct.pack("<I", sequence)
    return struct.pack("<I20sII", sequence, b"\xff" * 20, state,
                       zlib.crc32(raw, 0xFFFFFFFF) & 0xFFFFFFFF).ljust(0x1000, b"\xff")


def test_ota_guard_erased_known_slot_and_fail_closed_cases():
    erased = b"\xff" * 0x1000
    assert updater.validate_ota_metadata(erased * 2) == "erased"
    assert struct.unpack_from("<I", ota_sector(1), 28)[0] == 0x4743989A
    assert updater.validate_ota_metadata(ota_sector(1) + erased) == "known-ota_0"
    for data in [ota_sector(2) + erased, ota_sector(1, state=1) + erased,
                 b"\0" * 0x2000, ota_sector(1)[:-1] + b"\0" + erased]:
        with pytest.raises(updater.ValidationError):
            updater.validate_ota_metadata(data)


def test_mock_roundtrip_preserves_nvs_bootloader_and_filesystem(artifact, tmp_path):
    fake = FakeFlasher(partition_table())
    original = bytes(fake.flash)
    result = updater.update_runtime(*write_args(artifact, tmp_path, fake))
    assert result["verified"] and result["physical_reset_required"]
    assert fake.flash[:updater.APP_OFFSET] == original[:updater.APP_OFFSET]
    assert fake.flash[updater.APP_OFFSET + updater.APP_SIZE:] == original[updater.APP_OFFSET + updater.APP_SIZE:]
    assert sum("write-flash" in call for call in fake.calls) == 1
    folder = Path(result["backup_directory"])
    assert (folder / "flash-before.bin").read_bytes() == original
    report = json.loads((folder / "report.json").read_text())
    assert report["outside_app_unchanged"]
    for file in folder.iterdir():
        assert stat.S_IMODE(file.stat().st_mode) == 0o600


@pytest.mark.parametrize("guard", ["mac", "table", "ota"])
def test_device_guards_fail_before_write(artifact, tmp_path, guard):
    fake = FakeFlasher(partition_table())
    if guard == "mac":
        fake.mac = "00:11:22:33:44:55"
    elif guard == "table":
        fake.flash[updater.TABLE_OFFSET] ^= 1
    else:
        fake.flash[updater.OTA_OFFSET:updater.OTA_OFFSET + 0x1000] = ota_sector(2)
    with pytest.raises(updater.ValidationError):
        updater.update_runtime(*write_args(artifact, tmp_path, fake))
    assert not any("write-flash" in call for call in fake.calls)


def test_write_uses_private_validated_bytes_if_source_artifact_changes(artifact, tmp_path):
    fake = FakeFlasher(partition_table())
    original = app_image()

    def race(argv, timeout):
        if "read-mac" in argv:
            (artifact[0].parent / "circuitpython-firmware.bin").write_bytes(b"new unreviewed build")
        return fake(argv, timeout)

    args = list(write_args(artifact, tmp_path, fake))
    args[-1] = race
    updater.update_runtime(*args)
    assert fake.flash[updater.APP_OFFSET:updater.APP_OFFSET + len(original)] == original


def test_mac_is_rechecked_after_backup_before_any_write(artifact, tmp_path):
    fake = FakeFlasher(partition_table())

    def swap(argv, timeout):
        if "read-mac" in argv and fake.reads:
            fake.mac = "00:11:22:33:44:55"
        return fake(argv, timeout)

    args = list(write_args(artifact, tmp_path, fake))
    args[-1] = swap
    with pytest.raises(updater.ValidationError, match="MAC mismatch"):
        updater.update_runtime(*args)
    assert not any("write-flash" in call for call in fake.calls)


def test_bulk_flash_commands_allow_packaged_ram_stub_without_reset_or_erase(artifact, tmp_path):
    fake = FakeFlasher(partition_table())
    updater.update_runtime(*write_args(artifact, tmp_path, fake))
    bulk = [call for call in fake.calls if "read-flash" in call or "write-flash" in call]
    assert len(bulk) == 3
    for call in bulk:
        assert "--no-stub" not in call
        assert call[call.index("--before") + 1] == "no-reset"
        assert call[call.index("--after") + 1] == "no-reset"
        assert not any("erase" in value for value in call)
    write = next(call for call in bulk if "write-flash" in call)
    assert write[write.index("write-flash") + 3] == "0x10000"


@pytest.mark.parametrize("location", [updater.NVS_OFFSET, 0x500000, updater.APP_OFFSET])
def test_readback_detects_outside_change_or_bad_app(artifact, tmp_path, location):
    fake = FakeFlasher(partition_table())
    fake.corrupt_after = location
    with pytest.raises(updater.ValidationError, match="changed|SHA256"):
        updater.update_runtime(*write_args(artifact, tmp_path, fake))
    assert len(list((tmp_path / "private-backups").glob("*/flash-before.bin"))) == 1


def test_write_requires_all_explicit_guards(artifact, monkeypatch):
    monkeypatch.setattr(updater, "update_runtime", lambda *args: pytest.fail("guard bypassed"))
    assert updater.main([str(artifact[0]), "--write"]) == 2


def test_nonprivate_backup_directory_rejected(tmp_path):
    folder = tmp_path / "public-backups"
    folder.mkdir(mode=0o755)
    with pytest.raises(updater.ValidationError, match="private"):
        updater.private_backup_directory(folder)

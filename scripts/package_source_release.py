#!/usr/bin/env python3
"""Package a committed application source preview, without device access."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
# Only fixed Git commands run, without a shell or device operations.
import subprocess  # nosec B404
import zipfile

REPO = Path(__file__).resolve().parents[1]
GIT_EXECUTABLE = shutil.which("git")
PROJECT_URL = "https://github.com/bwedderburn/BM83-ESP32-S3-Nextion"
SOURCE_ROOT = "firmware/circuitpython/"
BASE_APPLICATION_SOURCES = frozenset({
    "boot.py", "main.py", "settings.example.toml",
    "lib/blehid/__init__.py", "lib/blehid/ble.py",
    "lib/bm83/__init__.py", "lib/bm83/bm83.py", "lib/bm83/link_probe.py",
    "lib/nextion/__init__.py", "lib/nextion/display.py",
    "lib/remote/__init__.py", "lib/remote/artwork_wifi.py", "lib/remote/badge_remote.py",
    "lib/remote/ble_status.py", "lib/remote/espnow_rx.py", "lib/remote/metadata_bridge.py",
    "lib/remote/metadata_text.py", "lib/remote/now_playing.py", "lib/remote/state_tx.py",
    "lib/utils/__init__.py", "lib/utils/common.py", "lib/utils/compat.py",
    "lib/utils/metadata_fields.py", "lib/utils/ticks.py",
})
# Older source previews predate the native host policy and badge host controls.
HOST_MANAGEMENT_SOURCES = frozenset({
    "lib/blehid/host_policy.py", "lib/remote/host_policy.py", "lib/remote/badge_hosts.py",
})
APPLICATION_SOURCES = BASE_APPLICATION_SOURCES | HOST_MANAGEMENT_SOURCES


def git(*args):
    """Read Git data with fixed verbs and argument lists; never execute a shell."""
    if GIT_EXECUTABLE is None:
        raise RuntimeError("Git is required to read committed release source")
    # Fixed Git verbs; blob reads use resolved object IDs from the commit tree.
    return subprocess.run(  # nosec B603
        [GIT_EXECUTABLE, "--no-pager", "--no-replace-objects", *args],
        cwd=REPO, check=True, capture_output=True
    ).stdout


def is_application_source(path):
    """New source files require deliberate review before entering release assets."""
    return path.startswith(SOURCE_ROOT) and path[len(SOURCE_ROOT):] in APPLICATION_SOURCES


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def package(revision, version, output):
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?", version):
        raise ValueError("Version must be a v-prefixed semantic version")
    commit = git("rev-parse", "--verify", "--end-of-options", revision + "^{commit}").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected a full Git commit SHA")
    entries = {}
    tree = git("ls-tree", "--full-tree", "-rz", commit, "--", SOURCE_ROOT, "LICENSE")
    for record in tree.split(b"\0"):
        if not record:
            continue
        metadata, path_bytes = record.split(b"\t", 1)
        path = path_bytes.decode("utf-8")
        if path != "LICENSE" and not is_application_source(path):
            continue
        mode, kind, object_id = metadata.decode("ascii").split()
        if mode not in ("100644", "100755") or kind != "blob":
            raise ValueError("Release inputs must be ordinary committed files: " + path)
        entries[path] = object_id
    required = {SOURCE_ROOT + name for name in BASE_APPLICATION_SOURCES} | {"LICENSE"}
    if not required.issubset(entries):
        raise ValueError("Commit is missing required release source: " + ", ".join(sorted(required - entries.keys())))
    selected = sorted(path for path in entries if is_application_source(path))
    members, inputs = {}, []
    for path in selected:
        data = git("cat-file", "blob", entries[path])
        relative = path[len(SOURCE_ROOT):]
        destination = "examples/" + relative if relative == "settings.example.toml" else "application/" + relative
        members[destination] = data
        inputs.append({"source": path, "archive_path": destination, "sha256": sha256(data)})
    members["LICENSE"] = git("cat-file", "blob", entries["LICENSE"])
    members["README.md"] = (
        f"# BM83 Remote {version} application-source preview\n\n"
        f"Source commit: `{commit}`. Draft prerelease; physical acceptance remains open.\n\n"
        "This archive is not an installer or native firmware image. The application/\n"
        "directory contains project source only. It excludes Adafruit libraries, private\n"
        "configuration, vendor artifacts, native images and CrowPanel binaries.\n\n"
        "Preserve existing settings, profiles and bonds. Do not copy this entire archive\n"
        "onto CIRCUITPY. The settings example under examples/ is inactive.\n\n"
        f"Read the [deployment guide]({PROJECT_URL}/blob/{commit}/docs/guides/deployment.md)\n"
        f"and [release notes]({PROJECT_URL}/blob/{commit}/docs/releases/{version}.md) before use.\n"
        "Install compatible Adafruit BLE/HID dependencies separately with their licenses.\n"
    ).encode()
    manifest = {
        "schema_version": 1, "version": version, "source_commit": commit,
        "scope": "application-source preview; no hardware deployment or acceptance",
        "inputs": inputs,
        "members": [{"path": name, "sha256": sha256(data), "bytes": len(data)}
                    for name, data in sorted(members.items())],
    }
    # The manifest describes all payload members except itself.
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    members["MANIFEST.json"] = manifest_bytes
    output = Path(output)
    # A new directory refuses existing artifacts and symlinks rather than
    # replacing an unrelated file through a previous output name.
    output.mkdir(parents=True, exist_ok=False)
    archive = output / ("BM83-Remote-" + version + "-application-source.zip")
    prefix = "BM83-Remote-" + version + "/"
    # Stored entries avoid zlib-version drift; timestamps and permissions are fixed.
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo(prefix + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, data)
    manifest_path = output / "MANIFEST.json"
    manifest_path.write_bytes(manifest_bytes)
    checksum_path = output / "SHA256SUMS.txt"
    checksum_path.write_text(
        f"{sha256(archive.read_bytes())}  {archive.name}\n"
        f"{sha256(manifest_bytes)}  {manifest_path.name}\n", encoding="utf-8", newline="\n"
    )
    return {"source_commit": commit, "archive": str(archive), "sha256": sha256(archive.read_bytes()),
            "payload_files": len(members), "manifest": str(manifest_path), "checksums": str(checksum_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="Reviewed Git commit; reads committed files only")
    parser.add_argument("--version", default="v0.1.0")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.revision, args.version, args.output), indent=2))


if __name__ == "__main__":
    main()

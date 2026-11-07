#!/usr/bin/env python3
"""Package a committed application source preview, without device access."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
# Only fixed Git commands run, without a shell or device operations.
import subprocess  # nosec B404
import tempfile
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
    "lib/utils/phase1_metrics.py",
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


def package(revision, version, output, *, scope="application-source", include_mpy=False,
            compiler=None, compiler_sha256=None):
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?", version):
        raise ValueError("Version must be a v-prefixed semantic version")
    commit = git("rev-parse", "--verify", "--end-of-options", revision + "^{commit}").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected a full Git commit SHA")
    if scope == "controller-badge-source":
        return package_controller_badge(commit, version, output, include_mpy=include_mpy,
                                        compiler=compiler, compiler_sha256=compiler_sha256)
    if scope != "application-source" or include_mpy:
        raise ValueError("Compiled assets require the controller-badge-source scope")
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
        data = checked(path, git("cat-file", "blob", entries[path]))
        relative = path[len(SOURCE_ROOT):]
        destination = "examples/" + relative if relative == "settings.example.toml" else "application/" + relative
        members[destination] = data
        inputs.append({"source": path, "archive_path": destination, "sha256": sha256(data)})
    members["LICENSE"] = checked("LICENSE", git("cat-file", "blob", entries["LICENSE"]))
    members["README.md"] = (
        f"# BM83 Remote {version} application-source preview\n\n"
        f"Source commit: `{commit}`. Draft prerelease; physical acceptance remains open.\n\n"
        "This archive is not an installer or native firmware image. The application/\n"
        "directory contains project source only. It excludes Adafruit libraries, private\n"
        "configuration, vendor artifacts, native images and CrowPanel binaries.\n\n"
        "Preserve existing settings, profiles and bonds. Do not copy this entire archive\n"
        "onto CIRCUITPY. The settings example under examples/ is inactive.\n\n"
        f"Read the [deployment guide]({PROJECT_URL}/blob/{commit}/docs/guides/deployment.md)\n"
        f"and [release preparation]({PROJECT_URL}/blob/{commit}/docs/releases/README.md) before use.\n"
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



RC_FIXED_FILES = frozenset({
    "LICENSE", "README.md", "setup.py", "build_mpy.sh",
    "docs/guides/deployment.md", "docs/guides/ble-volume-handoff.md",
    "docs/validation/hardware-test-limitations.md",
    "docs/validation/bm83-startup-artwork-validation-2026-11-01.md",
    "docs/reliability/README.md", "docs/reliability/DIRECT-MAINTENANCE.md",
    "docs/reliability/phase1-bintel-2026-11-04.md", "docs/reliability/phase2-host-selection.md",
    "docs/releases/README.md", "docs/releases/RC-PREPARATION.md",
    "scripts/fetch_mpy_cross.sh", "scripts/package_source_release.py",
    "scripts/prepare_release.py", "tools/mpy_cross_pin.env",
    "tools/bm83-windows-volume-host.py", "tools/windows_volume_app_receiver.py",
})
BADGE_ROOT = "addons/universe-badge/"
BADGE_SOURCES = frozenset({
    "README.md", "apps/bm83_remote/README.md", "apps/bm83_remote/__init__.py",
    "apps/bm83_remote/artwork.py", "apps/bm83_remote/icon.png",
    "apps/bm83_remote/models.py", "apps/bm83_remote/protocol.py",
    "apps/bm83_remote/transport.py", "apps/bm83_remote/verified_fetch.py",
    "apps/bm83_remote/artwork_trust/README.md",
    "apps/bm83_remote/artwork_trust/provenance.json",
    "apps/bm83_remote/artwork_trust/roots.der-store",
    "apps/bm83_remote/artwork_trust/cacert.pem",
    "apps/bm83_remote/artwork_trust/godaddy-root-g2.pem",
    "apps/bm83_remote/artwork_trust/LICENSE-Pimoroni-MIT.txt",
    "apps/bm83_remote/artwork_trust/LICENSE-MPL-2.0.txt",
})
PRIVATE_NAMES = frozenset({
    "secrets.py", "settings.toml", ".env", ".artwork_wifi.json",
    ".metadata_bridge.json", ".badge_remote.json", ".badge_windows_launch.key",
    ".bm83_windows_companion.json", ".bm83_windows_receiver.json",
})


def checked(path, data):
    """Reject private paths/key material even if a future allowlist adds one."""
    parts = PurePosixPath(path)
    if (parts.is_absolute() or ".." in parts.parts or "\\" in path or ":" in path
            or any(part.lower() in PRIVATE_NAMES for part in parts.parts)):
        raise ValueError("Refusing private or unsafe archive path: " + path)
    if re.search(rb"(?m)^-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----", data):
        raise ValueError("Refusing private-key content: " + path)
    return data


def rc_source_files(commit, version):
    """Every included path is individually reviewed; no directory-prefix grants."""
    selected = (RC_FIXED_FILES | {"RELEASE_NOTES-" + version + ".md"}
                | {SOURCE_ROOT + path for path in APPLICATION_SOURCES}
                | {BADGE_ROOT + path for path in BADGE_SOURCES})
    result, executable = {}, set()
    tree = git("ls-tree", "--full-tree", "-rz", commit, "--", *sorted(selected))
    for record in tree.split(b"\0"):
        if not record:
            continue
        metadata, path_bytes = record.split(b"\t", 1)
        path = path_bytes.decode("utf-8")
        if path not in selected:
            continue
        mode, kind, object_id = metadata.decode("ascii").split()
        if mode not in ("100644", "100755") or kind != "blob":
            raise ValueError("Release inputs must be ordinary committed files: " + path)
        result[path] = checked(path, git("cat-file", "blob", object_id))
        if mode == "100755":
            executable.add(path)
    if selected - result.keys():
        raise ValueError("Commit is missing required release source: "
                         + ", ".join(sorted(selected - result.keys())))
    return result, executable


def compiled_files(commit, source, compiler, compiler_sha256):
    """Verify exact-ref dist output by recompiling committed module bytes."""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", compiler_sha256 or "") or compiler is None:
        raise ValueError("--include-mpy requires --compiler and observed --compiler-sha256")
    pins = dict(line.split("=", 1) for line in source["tools/mpy_cross_pin.env"].decode().splitlines()
                if line and not line.startswith("#") and "=" in line)
    if compiler_sha256.lower() != pins["MPY_CROSS_LINUX_AMD64_SHA256"]:
        raise ValueError("Compiled release verification requires the pinned Linux amd64 compiler SHA-256")
    compiler = Path(compiler).resolve(strict=True)
    if not compiler.is_file() or sha256(compiler.read_bytes()) != compiler_sha256.lower():
        raise ValueError("Compiler file does not match the observed SHA-256")
    dist = (REPO / "dist").resolve(strict=True)
    directory = (dist / "circuitpython").resolve(strict=True)
    info_path = (dist / "BUILD_INFO.txt").resolve(strict=True)
    if (not dist.is_relative_to(REPO.resolve()) or not directory.is_relative_to(dist)
            or not info_path.is_relative_to(dist)):
        raise ValueError("Compiled output escaped this checkout's dist/ directory")
    info_bytes = info_path.read_bytes()
    info_lines = info_bytes.decode().splitlines()
    expected_fields = {"mpy_cross_pinned", "mpy_cross_version", "mpy_cross_opt_level", "source_commit"}
    if len(info_lines) != len(expected_fields) or any("=" not in line for line in info_lines):
        raise ValueError("Unexpected compiled build metadata fields")
    info = dict(line.split("=", 1) for line in info_lines)
    if info.keys() != expected_fields:
        raise ValueError("Unexpected compiled build metadata fields")
    expected_version = pins["MPY_CROSS_VERSION"]
    # mpy-cross can return nonzero for --version; its actual output is checked.
    actual_version = subprocess.run(  # nosec B603
        [str(compiler), "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False
    ).stdout.decode().strip()
    if (info.get("mpy_cross_pinned") != expected_version
            or info.get("mpy_cross_version") != actual_version
            or not actual_version.startswith("CircuitPython " + expected_version + " ")):
        raise ValueError("Compiled metadata does not match the pinned CircuitPython compiler")
    if info.get("source_commit") != commit:
        raise ValueError("Rebuild dist/ at the exact committed RC revision before packaging")
    if info.get("mpy_cross_opt_level") != "2":
        raise ValueError("RC compiled package requires the reviewed -O2 build")
    expected, modules = {}, {}
    for name, data in source.items():
        if not name.startswith(SOURCE_ROOT):
            continue
        relative = name[len(SOURCE_ROOT):]
        if relative.startswith("lib/") and relative.endswith(".py"):
            target = relative[:-3] + ".mpy"
            expected[target] = None
            modules[target] = (relative, data)
        else:
            expected[relative] = data
    actual = {path.relative_to(directory).as_posix(): path
              for path in directory.rglob("*") if path.is_file()}
    if actual.keys() != expected.keys():
        raise ValueError("Compiled tree differs from the exact allowlisted source file set")
    result = {}
    with tempfile.TemporaryDirectory(prefix="bm83-release-verify-") as temporary:
        temporary = Path(temporary)
        for name, path in sorted(actual.items()):
            if not path.resolve().is_relative_to(directory):
                raise ValueError("Compiled file escaped output directory: " + name)
            data = checked(name, path.read_bytes())
            if name in modules:
                relative, module_source = modules[name]
                input_path, output_path = temporary / "source.py", temporary / "compiled.mpy"
                input_path.write_bytes(module_source)
                subprocess.run(  # nosec B603
                    [str(compiler), "-O2", "-s", relative, "-o", str(output_path), str(input_path)],
                    check=True, capture_output=True,
                )
                if not data or data != output_path.read_bytes():
                    raise ValueError("Compiled module differs from committed source: " + name)
            elif data != expected[name]:
                raise ValueError("Entrypoint or asset differs from committed source: " + name)
            result["circuitpython/" + name] = data
    result["BUILD_INFO.txt"] = checked("BUILD_INFO.txt", info_bytes)
    result["LICENSE"] = source["LICENSE"]
    return result


def write_archive(path, files, metadata, executable=()):
    manifest = dict(metadata, members=[
        {"path": name, "bytes": len(data), "sha256": sha256(data),
         "mode": "100755" if name in executable else "100644"}
        for name, data in sorted(files.items())
    ])
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    payload = dict(files, **{"MANIFEST.json": manifest_bytes})
    prefix = "BM83-Remote-" + metadata["version"] + "/"
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_STORED) as bundle:
        for name, data in sorted(payload.items()):
            info = zipfile.ZipInfo(prefix + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100755 if name in executable else 0o100644) << 16
            bundle.writestr(info, data)
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": sha256(path.read_bytes())}, manifest_bytes


def package_controller_badge(commit, version, output, *, include_mpy=False,
                             compiler=None, compiler_sha256=None):
    source, executable = rc_source_files(commit, version)
    compiled = compiled_files(commit, source, compiler, compiler_sha256) if include_mpy else None
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    metadata = {"schema_version": 1, "version": version, "source_commit": commit,
                "scope": "controller-badge-source", "hardware_validation": "not-run-by-packaging"}
    archive = output / ("bm83-controller-badge-" + version + "-source.zip")
    record, manifest_bytes = write_archive(archive, source, metadata, executable)
    records = [record]
    manifest_path = output / "MANIFEST.json"
    manifest_path.write_bytes(manifest_bytes)
    if compiled is not None:
        compiled_metadata = dict(metadata, scope="compiled-controller-only",
                                 compiler_sha256=compiler_sha256.lower())
        record, _ = write_archive(output / ("bm83-controller-" + version + "-mpy.zip"),
                                  compiled, compiled_metadata)
        records.append(record)
    checksum_path = output / "SHA256SUMS.txt"
    checksum_path.write_text(
        "".join(item["sha256"] + "  " + item["file"] + "\n" for item in records)
        + sha256(manifest_bytes) + "  MANIFEST.json\n", encoding="utf-8", newline="\n"
    )
    return {"source_commit": commit, "archive": str(archive), "sha256": records[0]["sha256"],
            "manifest": str(manifest_path), "checksums": str(checksum_path), "artifacts": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", "--ref", dest="revision", required=True,
                        help="Reviewed Git commit; reads committed files only")
    parser.add_argument("--version", default="v1.0.0-rc.1")
    parser.add_argument("--scope", choices=("application-source", "controller-badge-source"),
                        default="application-source")
    parser.add_argument("--output", type=Path, required=True, help="New host output directory")
    parser.add_argument("--include-mpy", action="store_true", help="Verify and include exact-ref dist/ output")
    parser.add_argument("--compiler", type=Path, help="Actual mpy-cross binary for verification")
    parser.add_argument("--compiler-sha256", help="Observed SHA-256 of that compiler file")
    args = parser.parse_args()
    print(json.dumps(package(args.revision, args.version, args.output, scope=args.scope,
                             include_mpy=args.include_mpy, compiler=args.compiler,
                             compiler_sha256=args.compiler_sha256), indent=2))


if __name__ == "__main__":
    main()

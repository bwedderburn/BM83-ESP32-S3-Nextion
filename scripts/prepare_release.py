#!/usr/bin/env python3
"""Create deterministic, allowlisted local RC archives without device access."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
# Subprocess use below is limited to fixed local Git reads; no shell is used.
import subprocess  # nosec B404
import zipfile


ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.0-rc.1"
NOTES = f"RELEASE_NOTES-v{VERSION}.md"
FIXED_FILES = {
    "LICENSE", "README.md", "docs/guides/deployment.md", NOTES, "setup.py", "build_mpy.sh",
    "scripts/fetch_mpy_cross.sh", "scripts/prepare_release.py", "tools/mpy_cross_pin.env",
    "docs/validation/hardware-test-limitations.md",
    "docs/validation/bm83-startup-artwork-validation-2026-11-01.md",
    "docs/reliability/README.md", "docs/reliability/DIRECT-MAINTENANCE.md",
    "docs/releases/RC-PREPARATION.md",
}
PREFIXES = ("firmware/circuitpython/", "addons/universe-badge/")
PRIVATE_NAMES = {"secrets.py", "settings.toml", ".env", ".artwork_wifi.json",
                 ".metadata_bridge.json", ".badge_remote.json"}


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])  # nosec B603,B607


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked(name, data):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or any(part.lower() in PRIVATE_NAMES for part in path.parts):
        raise ValueError(f"Refusing private or unsafe archive path: {name}")
    if re.search(rb"(?m)^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", data):
        raise ValueError(f"Refusing private-key content: {name}")
    return data


def source_files(revision):
    names = git("ls-tree", "-r", "--name-only", revision).decode().splitlines()
    selected = [name for name in names if name in FIXED_FILES or name.startswith(PREFIXES)]
    missing = FIXED_FILES - set(selected)
    if missing:
        raise ValueError("Commit the release files before packaging: " + ", ".join(sorted(missing)))
    return {name: checked(name, git("show", f"{revision}:{name}")) for name in selected}


def executable_files(revision):
    result = set()
    for entry in git("ls-tree", "-rz", revision).split(b"\0"):
        if not entry:
            continue
        info, path = entry.split(b"\t", 1)
        if info.split()[0] == b"100755":
            result.add(path.decode("utf-8"))
    return result


def compiled_files(revision, source):
    directory = (ROOT / "dist/circuitpython").resolve()
    if not directory.is_relative_to((ROOT / "dist").resolve()):
        raise ValueError("Compiled directory escaped dist/")
    info_path = ROOT / "dist/BUILD_INFO.txt"
    info_bytes = info_path.read_bytes()
    info = dict(line.split("=", 1) for line in info_bytes.decode().splitlines() if "=" in line)
    pin = source["tools/mpy_cross_pin.env"].decode()
    expected_version = re.search(r"^MPY_CROSS_VERSION=(\S+)$", pin, re.M).group(1)
    if info.get("source_commit") != revision:
        raise ValueError("Rebuild dist/ at the exact committed RC revision before packaging")
    if info.get("mpy_cross_pinned") != expected_version or not info.get("mpy_cross_version", "").startswith(f"CircuitPython {expected_version} "):
        raise ValueError("Compiled metadata does not match the pinned CircuitPython compiler")
    if info.get("mpy_cross_opt_level") != "2":
        raise ValueError("RC compiled package requires the reviewed -O2 build")
    git("diff", "--exit-code", revision, "--", "firmware/circuitpython")
    expected = {}
    prefix = "firmware/circuitpython/"
    for name, data in source.items():
        if not name.startswith(prefix):
            continue
        relative = name[len(prefix):]
        if relative.startswith("lib/") and relative.endswith(".py"):
            expected[relative[:-3] + ".mpy"] = None
        elif relative in ("main.py", "boot.py") or not relative.endswith(".py"):
            expected[relative] = data
    actual = {path.relative_to(directory).as_posix(): path for path in directory.rglob("*") if path.is_file()}
    if set(actual) != set(expected):
        raise ValueError("Compiled tree differs from the exact allowlisted source file set")
    result = {}
    for name, path in actual.items():
        if not path.resolve().is_relative_to(directory):
            raise ValueError(f"Compiled file escapes output directory: {name}")
        data = checked(name, path.read_bytes())
        if expected[name] is not None and data != expected[name]:
            raise ValueError(f"Uncompiled entrypoint/asset differs from source: {name}")
        if name.endswith(".mpy") and not data:
            raise ValueError(f"Empty compiled module: {name}")
        result["circuitpython/" + name] = data
    result["BUILD_INFO.txt"] = info_bytes
    result["LICENSE"] = source["LICENSE"]
    result[NOTES] = source[NOTES]
    return result


def write_archive(path, files, metadata, executable=()):
    manifest = dict(metadata, files=[{"path": name, "bytes": len(data), "sha256": digest(data),
                                     "mode": "100755" if name in executable else "100644"}
                                     for name, data in sorted(files.items())])
    payload = dict(files, **{"RELEASE-MANIFEST.json": (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()})
    # Stored ZIP entries avoid compressor/version variance. Timestamps, modes,
    # entry order, JSON formatting and path separators are fixed.
    import io
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(payload.items()):
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (0o100755 if name in executable else 0o100644) << 16
            archive.writestr(entry, data)
    content = stream.getvalue()
    if path.exists() and path.read_bytes() != content:
        raise ValueError(f"Existing artifact differs; use a new output directory: {path.name}")
    path.write_bytes(content)
    return {"file": path.name, "bytes": len(content), "sha256": digest(content)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="Committed candidate revision")
    parser.add_argument("--output", default=f"dist/releases/v{VERSION}")
    parser.add_argument("--include-mpy", action="store_true", help="Include an exact-revision dist/ build")
    parser.add_argument("--compiler-sha256", help="Observed compiler SHA-256 for compiled-artifact provenance")
    args = parser.parse_args()
    revision = git("rev-parse", "--verify", "--end-of-options", f"{args.ref}^{{commit}}").decode().strip()
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to((ROOT / "dist").resolve()):
        parser.error("Output must remain inside this checkout's ignored dist/ directory")
    if args.include_mpy and not re.fullmatch(r"[0-9a-fA-F]{64}", args.compiler_sha256 or ""):
        parser.error("--include-mpy requires the observed --compiler-sha256")
    source = source_files(revision)
    output.mkdir(parents=True, exist_ok=True)
    metadata = {"version": VERSION, "source_commit": revision, "scope": "controller-and-badge-source",
                "hardware_validation": "not-run-by-packaging", "published": False}
    records = [write_archive(output / f"bm83-controller-badge-v{VERSION}-source.zip", source, metadata,
                             executable_files(revision))]
    if args.include_mpy:
        compiled = compiled_files(revision, source)
        records.append(write_archive(output / f"bm83-controller-v{VERSION}-mpy.zip", compiled,
                                     dict(metadata, scope="compiled-controller-only", compiler_sha256=args.compiler_sha256.lower())))
    checksums = "".join(f"{record['sha256']}  {record['file']}\n" for record in records)
    (output / "SHA256SUMS.txt").write_text(checksums, encoding="utf-8", newline="\n")
    print(json.dumps({"source_commit": revision, "output": str(output), "artifacts": records}, indent=2))


if __name__ == "__main__":
    main()

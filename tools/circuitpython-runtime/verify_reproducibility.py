#!/usr/bin/env python3
"""Compare two offline native builds without normalizing metadata or using devices.

Matching manifests establish equality of recorded provenance, not its truth or
agreement with approved pins. Validate those inputs and the image separately.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys


MANIFEST = "build-manifest.json"
MANIFEST_LIMIT = 65536
CHUNK_BYTES = 1024 * 1024
SOURCE_KEYS = {"circuitpython", "esp_idf", "esp_nimble"}
TOOL_KEYS = {"python", "cmake", "ninja", "gcc", "cryptography", "builder_image"}
HASH_INPUTS = {"constraints_sha256", "requirements_sha256", "patch_sha256",
               "idf_tools_json_sha256", "web_assets_patch_sha256", "hashlib_close_patch_sha256",
               "host_policy_patch_sha256"}
NIMBLE_HASH_INPUTS = {"nimble_legacy_features_patch_sha256", "nimble_csfc_patch_sha256"}
ARTIFACTS = {"app", "elf", "sdkconfig", "sdkconfig_h", "partition_table",
             "distro_manifest", "python_packages"}
TOP_KEYS = {"schema_version", "sources", "toolchain", "inputs", "artifacts"}


class VerificationError(ValueError):
    """Invalid provenance, unsafe artifact path, or nonidentical output."""


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def digest(value, length=64):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{%d}" % length, value)


def artifact_path(folder, filename):
    require(isinstance(filename, str) and filename and "\\" not in filename
            and ":" not in filename and not any(ord(char) < 32 for char in filename),
            "Artifact path must be a portable relative path")
    path = PurePosixPath(filename)
    safe_parts = all(part not in ("", ".", "..") for part in filename.split("/"))
    require(not path.is_absolute() and safe_parts,
            "Artifact path must stay within its build directory")
    candidate = folder
    for part in path.parts:
        candidate = candidate / part
        require(not candidate.is_symlink(), "Symlinks are not allowed in artifact paths")
    require(candidate.is_file(), "Required artifact is missing or is not a regular file")
    return candidate


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "Duplicate fields are not allowed in build manifests")
        value[key] = item
    return value


def load_manifest(folder):
    folder = Path(folder).resolve()
    require(folder.is_dir(), "Build directory is missing")
    manifest_path = artifact_path(folder, MANIFEST)
    require(manifest_path.stat().st_size <= MANIFEST_LIMIT, "Build manifest exceeds size limit")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError("Build manifest is not valid UTF-8 JSON") from exc
    require(isinstance(manifest, dict) and set(manifest) == TOP_KEYS,
            "Build manifest has unexpected or missing fields")
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1,
            "Unsupported build manifest schema")
    sources = manifest["sources"]
    require(isinstance(sources, dict) and set(sources) == SOURCE_KEYS
            and all(digest(value, 40) for value in sources.values()),
            "Source provenance must contain three recorded commit hashes")
    tools = manifest["toolchain"]
    require(isinstance(tools, dict) and set(tools) == TOOL_KEYS
            and all(isinstance(value, str) and value.strip() and len(value) <= 500
                    for value in tools.values()), "Toolchain provenance is incomplete")
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", tools["builder_image"]),
            "Builder image must be recorded by immutable image SHA256")
    inputs = manifest["inputs"]
    require(isinstance(inputs, dict), "Invalid recorded build inputs")
    original_keys = HASH_INPUTS | {"source_date_epoch"}
    require(set(inputs) in (original_keys, original_keys | NIMBLE_HASH_INPUTS)
            and all(digest(inputs[key]) for key in set(inputs) - {"source_date_epoch"})
            and type(inputs["source_date_epoch"]) is int and inputs["source_date_epoch"] >= 0,
            "Build input provenance is incomplete")
    artifacts = manifest["artifacts"]
    require(isinstance(artifacts, dict) and ARTIFACTS <= set(artifacts) and len(artifacts) <= 128
            and all(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) for name in artifacts),
            "Manifest must list the seven required artifacts and safe additional artifact names")
    paths = {}
    for name, entry in artifacts.items():
        require(isinstance(entry, dict) and set(entry) == {"file", "sha256"}
                and digest(entry["sha256"]), "Artifact entry must contain a filename and SHA256")
        paths[name] = artifact_path(folder, entry["file"])
        require(paths[name].stat().st_size > 0, "Required artifact must not be empty: " + name)
    require(len(set(paths.values())) == len(paths), "Artifact filenames must be distinct")
    return manifest, paths


def hash_file(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            value.update(chunk)
    return value.hexdigest()


def same_bytes(left, right):
    with left.open("rb") as first, right.open("rb") as second:
        while True:
            a, b = first.read(CHUNK_BYTES), second.read(CHUNK_BYTES)
            if a != b:
                return False
            if not a:
                return True


def verify(first, second):
    """Validate both manifests and require exact provenance and artifact bytes."""
    require(Path(first).resolve() != Path(second).resolve(),
            "Two distinct build artifact directories are required")
    left, left_paths = load_manifest(first)
    right, right_paths = load_manifest(second)
    for field in ("sources", "toolchain", "inputs"):
        require(left[field] == right[field], "Recorded %s differs between builds" % field)
    require(set(left_paths) == set(right_paths), "Artifact sets differ between builds")
    hashes = {}
    for name in sorted(left_paths):
        a, b = left_paths[name], right_paths[name]
        # Check each manifest independently before comparing output bytes.
        first_hash, second_hash = hash_file(a), hash_file(b)
        require(first_hash == left["artifacts"][name]["sha256"],
                "First build declared SHA256 does not match artifact: " + name)
        require(second_hash == right["artifacts"][name]["sha256"],
                "Second build declared SHA256 does not match artifact: " + name)
        require(same_bytes(a, b), "Artifact bytes differ between builds: " + name)
        hashes[name] = first_hash
    return {"schema_version": 1, "status": "identical", "artifact_sha256": hashes,
            "recorded_provenance_equal": True,
            "approved_source_pins_verified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify(args.first, args.second)
    except (VerificationError, OSError) as exc:
        print("FAIL reproducibility: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

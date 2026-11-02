"""Tamper/variance regressions for the offline native-build comparator."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "tools/circuitpython-runtime/verify_reproducibility.py"
SPEC = importlib.util.spec_from_file_location("native_build_reproducibility", SCRIPT)
repro = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repro)


def write_manifest(folder, value):
    (folder / repro.MANIFEST).write_text(json.dumps(value), encoding="utf-8")


def build(folder, bootloader=True):
    folder.mkdir()
    value = {
        "schema_version": 1,
        "sources": {name: "a" * 40 for name in repro.SOURCE_KEYS},
        "toolchain": {name: "recorded-version" for name in repro.TOOL_KEYS},
        "inputs": dict.fromkeys(repro.HASH_INPUTS, "b" * 64),
        "artifacts": {},
    }
    value["toolchain"]["builder_image"] = "sha256:" + "c" * 64
    value["inputs"]["source_date_epoch"] = 1789146568
    for name in repro.ARTIFACTS | ({"bootloader"} if bootloader else set()):
        data = (name + ": deterministic fixture\n").encode()
        filename = name + ".fixture"
        (folder / filename).write_bytes(data)
        value["artifacts"][name] = {"file": filename, "sha256": hashlib.sha256(data).hexdigest()}
    write_manifest(folder, value)
    return value


@pytest.fixture
def builds(tmp_path):
    first, second = tmp_path / "first build", tmp_path / "second build"
    return first, second, build(first), build(second)


def test_identical_builds_compare_all_raw_artifacts_and_provenance(builds):
    first, second, _left, right = builds
    result = repro.verify(first, second)
    assert result["status"] == "identical"
    assert set(result["artifact_sha256"]) == repro.ARTIFACTS | {"bootloader"}
    assert result["artifact_sha256"]["app"] == right["artifacts"]["app"]["sha256"]
    # Equality must not falsely attest the dummy source hashes or real image format.
    assert result["approved_source_pins_verified"] is False


def test_optional_bootloader_absent_from_both_is_allowed(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    build(a, bootloader=False)
    build(b, bootloader=False)
    assert set(repro.verify(a, b)["artifact_sha256"]) == repro.ARTIFACTS


def test_same_build_directory_cannot_stand_in_for_a_second_build(builds):
    first, _second, _left, _right = builds
    with pytest.raises(repro.VerificationError, match="Two distinct"):
        repro.verify(first, first / ".")


def test_additional_provenance_artifact_is_compared_instead_of_ignored(builds):
    first, second, left, right = builds
    name = "recursive_submodules"
    data = b"recorded submodule commits\n"
    for folder, manifest in ((first, left), (second, right)):
        (folder / "submodules.txt").write_bytes(data)
        manifest["artifacts"][name] = {"file": "submodules.txt", "sha256": hashlib.sha256(data).hexdigest()}
        write_manifest(folder, manifest)
    assert name in repro.verify(first, second)["artifact_sha256"]
    changed = data + b"different commit\n"
    (second / "submodules.txt").write_bytes(changed)
    right["artifacts"][name]["sha256"] = hashlib.sha256(changed).hexdigest()
    write_manifest(second, right)
    with pytest.raises(repro.VerificationError, match="Artifact bytes differ between builds: " + name):
        repro.verify(first, second)


@pytest.mark.parametrize("name", sorted(repro.ARTIFACTS | {"bootloader"}))
def test_each_artifact_tamper_is_rejected_against_declared_hash(builds, name):
    first, second, _left, right = builds
    path = second / right["artifacts"][name]["file"]
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(repro.VerificationError, match="declared SHA256 does not match artifact: " + name):
        repro.verify(first, second)


@pytest.mark.parametrize("name", sorted(repro.ARTIFACTS | {"bootloader"}))
def test_each_legitimate_but_different_output_fails_raw_comparison(builds, name):
    first, second, _left, right = builds
    path = second / right["artifacts"][name]["file"]
    path.write_bytes(path.read_bytes() + b"different build metadata\n")
    right["artifacts"][name]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_manifest(second, right)
    with pytest.raises(repro.VerificationError, match="Artifact bytes differ between builds: " + name):
        repro.verify(first, second)


@pytest.mark.parametrize("field,key,value", [
    ("sources", "circuitpython", "c" * 40),
    ("sources", "esp_idf", "c" * 40),
    ("sources", "esp_nimble", "c" * 40),
    ("toolchain", "python", "another-python"),
    ("toolchain", "cmake", "another-cmake"),
    ("toolchain", "ninja", "another-ninja"),
    ("toolchain", "gcc", "another-gcc"),
    ("toolchain", "cryptography", "another-cryptography"),
    ("toolchain", "builder_image", "sha256:" + "d" * 64),
    ("inputs", "constraints_sha256", "c" * 64),
    ("inputs", "requirements_sha256", "c" * 64),
    ("inputs", "patch_sha256", "c" * 64),
    ("inputs", "idf_tools_json_sha256", "c" * 64),
    ("inputs", "web_assets_patch_sha256", "c" * 64),
    ("inputs", "hashlib_close_patch_sha256", "c" * 64),
    ("inputs", "source_date_epoch", 1789146569),
])
def test_every_recorded_provenance_input_must_match(builds, field, key, value):
    first, second, _left, right = builds
    right[field][key] = value
    write_manifest(second, right)
    with pytest.raises(repro.VerificationError, match="Recorded " + field + " differs"):
        repro.verify(first, second)


@pytest.mark.parametrize("name", sorted(repro.ARTIFACTS))
def test_required_artifact_cannot_be_omitted_from_manifest(builds, name):
    first, second, _left, right = builds
    del right["artifacts"][name]
    write_manifest(second, right)
    with pytest.raises(repro.VerificationError, match="seven required artifacts"):
        repro.verify(first, second)


def test_unlisted_bootloader_on_one_side_is_not_silently_ignored(builds):
    first, second, _left, right = builds
    del right["artifacts"]["bootloader"]
    write_manifest(second, right)
    with pytest.raises(repro.VerificationError, match="Artifact sets differ"):
        repro.verify(first, second)


def test_missing_artifact_file_is_not_success(builds):
    first, second, _left, right = builds
    (second / right["artifacts"]["app"]["file"]).unlink()
    with pytest.raises(repro.VerificationError, match="missing or is not a regular file"):
        repro.verify(first, second)


def test_even_correctly_hashed_empty_artifacts_are_refused(builds):
    first, second, _left, right = builds
    (second / right["artifacts"]["app"]["file"]).write_bytes(b"")
    right["artifacts"]["app"]["sha256"] = hashlib.sha256(b"").hexdigest()
    write_manifest(second, right)
    with pytest.raises(repro.VerificationError, match="must not be empty"):
        repro.verify(first, second)


def test_raw_comparison_checks_beyond_the_first_streaming_chunk(builds):
    first, second, left, right = builds
    data = b"a" * (repro.CHUNK_BYTES * 2 + 1)
    for folder, manifest in ((first, left), (second, right)):
        (folder / manifest["artifacts"]["elf"]["file"]).write_bytes(data)
        manifest["artifacts"]["elf"]["sha256"] = hashlib.sha256(data).hexdigest()
        write_manifest(folder, manifest)
    assert repro.verify(first, second)["status"] == "identical"
    changed = data[:-1] + b"z"
    (second / right["artifacts"]["elf"]["file"]).write_bytes(changed)
    right["artifacts"]["elf"]["sha256"] = hashlib.sha256(changed).hexdigest()
    write_manifest(second, right)
    with pytest.raises(repro.VerificationError, match="Artifact bytes differ between builds: elf"):
        repro.verify(first, second)


def test_mutable_builder_image_tag_is_not_accepted_as_a_lock(builds):
    first, second, left, right = builds
    for folder, manifest in ((first, left), (second, right)):
        manifest["toolchain"]["builder_image"] = "python:3.11"
        write_manifest(folder, manifest)
    with pytest.raises(repro.VerificationError, match="immutable image SHA256"):
        repro.verify(first, second)


@pytest.mark.parametrize("filename", [
    "../outside.bin", "/absolute.bin", "a/../outside.bin", "a//file", "./file", "C:/file", "C:\\file", "a\nfile",
])
def test_artifact_paths_cannot_escape_or_use_ambiguous_syntax(builds, filename):
    first, second, _left, right = builds
    right["artifacts"]["app"]["file"] = filename
    write_manifest(second, right)
    with pytest.raises(repro.VerificationError, match="Artifact path"):
        repro.verify(first, second)


def test_symlink_artifact_is_not_read(builds):
    first, second, _left, right = builds
    path = second / right["artifacts"]["app"]["file"]
    path.unlink()
    try:
        path.symlink_to(first / right["artifacts"]["app"]["file"])
    except OSError:
        pytest.skip("Symlinks unavailable on this host")
    with pytest.raises(repro.VerificationError, match="Symlinks"):
        repro.verify(first, second)


@pytest.mark.parametrize("mutation", [
    "bad_json", "version_bool", "extra_field", "missing_tool", "bad_hash", "duplicate_path",
])
def test_malformed_or_incomplete_manifests_are_rejected(builds, mutation):
    first, second, _left, right = builds
    if mutation == "bad_json":
        (second / repro.MANIFEST).write_text("{bad-json")
    else:
        if mutation == "version_bool":
            right["schema_version"] = True
        elif mutation == "extra_field":
            right["timestamp"] = "not silently ignored"
        elif mutation == "missing_tool":
            del right["toolchain"]["gcc"]
        elif mutation == "bad_hash":
            right["artifacts"]["app"]["sha256"] = "not-a-hash"
        elif mutation == "duplicate_path":
            right["artifacts"]["elf"]["file"] = right["artifacts"]["app"]["file"]
        write_manifest(second, right)
    with pytest.raises(repro.VerificationError):
        repro.verify(first, second)


def test_duplicate_json_fields_are_not_silently_discarded(builds):
    first, second, _left, right = builds
    text = json.dumps(right).replace('"schema_version": 1', '"schema_version": 2, "schema_version": 1')
    (second / repro.MANIFEST).write_text(text)
    with pytest.raises(repro.VerificationError, match="Duplicate fields"):
        repro.verify(first, second)


def test_cli_success_and_failure_exit_codes_are_explicit(builds):
    first, second, _left, right = builds
    result = subprocess.run([sys.executable, str(SCRIPT), str(first), str(second)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "identical"
    (second / right["artifacts"]["elf"]["file"]).write_bytes(b"changed")
    result = subprocess.run([sys.executable, str(SCRIPT), str(first), str(second)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "FAIL reproducibility" in result.stderr

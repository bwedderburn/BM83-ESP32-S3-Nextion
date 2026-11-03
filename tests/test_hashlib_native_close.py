"""Apply the real native patch and execute its HAL with a bounded PSA model."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/native_hash_close"
RECIPE = ROOT / "tools/circuitpython-runtime"


@pytest.fixture
def patched_source(tmp_path):
    if not shutil.which("git"):
        pytest.skip("Git is required to apply the reviewed native patch")
    source = tmp_path / "source"
    shutil.copytree(FIXTURE / "base", source)
    subprocess.run(["git", "apply", "--check", str(RECIPE / "hashlib-close.patch")],
                   cwd=source, check=True, capture_output=True, text=True)
    subprocess.run(["git", "apply", str(RECIPE / "hashlib-close.patch")],
                   cwd=source, check=True, capture_output=True, text=True)
    pins = json.loads((RECIPE / "source-pins.json").read_text())["runtime_patches"]["hashlib_close"]
    assert hashlib.sha256((RECIPE / "hashlib-close.patch").read_bytes()).hexdigest() == pins["sha256"]
    for filename, expected in pins["files"].items():
        assert hashlib.sha256((source / filename).read_bytes()).hexdigest() == expected
    return source


def test_actual_patched_hal_releases_original_and_partial_clone_contexts(patched_source, tmp_path):
    compiler = shutil.which("cc")
    if not compiler:
        pytest.skip("A host C compiler is required for the native ownership model")
    executable = tmp_path / "native-lifetime"
    command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-deprecated-declarations",
               "-I" + str(FIXTURE / "include"), "-I" + str(patched_source),
               str(patched_source / "shared-module/hashlib/Hash.c"),
               str(patched_source / "shared-module/hashlib/__init__.c"),
               str(FIXTURE / "lifetime.c"), "-o", str(executable)]
    if sys.platform != "darwin":
        command.append("-lcrypto")
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    result = subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=15)
    assert "PASS native Hash lifecycle" in result.stdout


def test_finalizer_capability_and_non_psa_binding_guards_are_present(patched_source):
    constructor = (patched_source / "shared-bindings/hashlib/__init__.c").read_text()
    binding = (patched_source / "shared-bindings/hashlib/Hash.c").read_text()
    assert "mp_obj_malloc_with_finaliser(hashlib_hash_obj_t, &hashlib_hash_type)" in constructor
    assert "MP_QSTR__deinit_supported" in constructor
    assert "MP_QSTR___del__" in binding and "MP_QSTR_deinit" in binding
    assert "#if CIRCUITPY_HASHLIB_MBEDTLS" in constructor
    assert "#if CIRCUITPY_HASHLIB_MBEDTLS" in binding

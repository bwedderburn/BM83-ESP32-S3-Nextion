"""Offline regression for a failed optional feature query on a live LE link."""

import hashlib
from pathlib import Path
import shutil
import subprocess

import pytest

RECIPE = Path(__file__).resolve().parents[1] / "tools/circuitpython-runtime"
PATCH = RECIPE / "nimble-legacy-le-features.patch"
SOURCE_PATH = Path("nimble/host/src/ble_gap.c")


def apply_patch_to_fixture(tmp_path):
    # Exact upstream license and lines 3455–3546 from espressif/esp-nimble
    # 7075927f97c648af650a288e94a8c80dd7f00c27, retained for offline tests.
    fixture = (RECIPE / "tests/legacy_le_features_upstream.c").read_bytes()
    assert hashlib.sha256(fixture).hexdigest() == (
        "af05028a9a8f7bb2c43289e6c656c4e3c604424397341768f632f485e4c6bfb0"
    )
    target = tmp_path / SOURCE_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes(fixture)
    subprocess.run(["git", "apply", "--check", PATCH], cwd=tmp_path, check=True, timeout=10)
    subprocess.run(["git", "apply", PATCH], cwd=tmp_path, check=True, timeout=10)
    patched = target.read_bytes()
    assert patched != fixture
    subprocess.run(["git", "apply", "--reverse", PATCH], cwd=tmp_path, check=True, timeout=10)
    assert target.read_bytes() == fixture
    return fixture, patched


def test_vendor_patch_against_pinned_gap_source(tmp_path):
    apply_patch_to_fixture(tmp_path)


def test_production_gap_callback_ignores_only_unsupported_optional_features(tmp_path):
    compiler = shutil.which("gcc")
    if compiler is None:
        pytest.skip("NimBLE callback harness requires the Linux/WSL GCC builder")
    original, patched = apply_patch_to_fixture(tmp_path)
    for source, patched_flag in ((original, 0), (patched, 1)):
        start = (b"static void\nble_gap_event_connect_call_internal" if patched_flag
                 else b"void\nble_gap_event_connect_call")
        end = b"\nvoid\nble_gap_rx_rd_rem_ver_info_complete"
        callbacks = source[source.index(start):source.index(end)]
        (tmp_path / "legacy_le_features_under_test.h").write_bytes(callbacks)
        for memory_optimized in (0, 1):
            executable = tmp_path / "legacy-le-features-test"
            subprocess.run([
                compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                f"-DBT_NIMBLE_MEM_OPTIMIZATION={memory_optimized}",
                f"-DEXPECT_COMPAT_FIX={patched_flag}", "-I", str(tmp_path),
                str(RECIPE / "tests/legacy_le_features_test.c"), "-o", str(executable),
            ], check=True, timeout=30)
            subprocess.run([executable], cwd=tmp_path, check=True, timeout=10)

"""Compile the real BLS1 C++ decoder and exercise hardware-free scenarios."""
import os
import shutil
import subprocess  # nosec B404 - local compiler and built host test only
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("golden", "malformed", "validation", "ordering", "sessions", "expiry")


@pytest.fixture(scope="module")
def ble_status_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("no C++ compiler on this machine")
    suffix = ".exe" if os.name == "nt" else ""
    binary = tmp_path_factory.mktemp("ble_status_host") / ("ble_status_test" + suffix)
    result = subprocess.run(  # nosec B603 - fixed local source/include paths, no shell
        [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic",
         "-I" + str(ROOT / "firmware/crowpanel-remote/include"),
         str(ROOT / "tests/crowpanel_host/ble_status_test.cpp"), "-o", str(binary)],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_ble_status_scenario(ble_status_binary, scenario):
    result = subprocess.run(  # nosec B603 - locally built host test, fixed scenario argv
        [str(ble_status_binary), scenario], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr

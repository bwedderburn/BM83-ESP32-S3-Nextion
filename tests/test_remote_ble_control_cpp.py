"""The Settings transaction waits for observed state, not radio delivery."""
import os
import shutil
import subprocess  # nosec B404 - local compiler and built host test only
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def control_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("no C++ compiler on this machine")
    suffix = ".exe" if os.name == "nt" else ""
    binary = tmp_path_factory.mktemp("ble_control_host") / ("ble_control_test" + suffix)
    result = subprocess.run(  # nosec B603 - fixed repository source/include paths, no shell
        [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic",
         "-I" + str(ROOT / "firmware/crowpanel-remote/include"),
         str(ROOT / "tests/crowpanel_host/ble_control_test.cpp"), "-o", str(binary)],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("scenario", ("pause", "enable", "expiry"))
def test_observed_ble_confirmation(control_binary, scenario):
    result = subprocess.run(  # nosec B603 - owned local binary and fixed scenario argv
        [str(control_binary), scenario], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr

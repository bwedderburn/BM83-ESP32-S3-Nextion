"""Compile and run the slider's hardware-free C++11 queue scenarios."""
import os
import shutil
import subprocess  # nosec B404 - only the local compiler and built host binary
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REMOTE_DIR = REPO_ROOT / "firmware" / "crowpanel-remote"
HOST_DIR = Path(__file__).resolve().parent / "crowpanel_host"
SCENARIOS = (
    "clamping_and_completion",
    "pacing_after_blocked_send",
    "replacement_and_cancel",
    "failure_stops_queue",
    "expiry",
    "wraparound",
)


@pytest.fixture(scope="module")
def volume_adjustment_binary(tmp_path_factory):
    cxx = shutil.which("g++") or shutil.which("clang++")
    if not cxx:
        pytest.skip("no C++ compiler on this machine")
    suffix = ".exe" if os.name == "nt" else ""
    out = tmp_path_factory.mktemp("volume_adjustment_host") / ("volume_adjustment_test" + suffix)
    cmd = [
        cxx, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic",
        "-I%s" % (REMOTE_DIR / "include"),
        str(HOST_DIR / "volume_adjustment_test.cpp"), "-o", str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)  # nosec B603 - fixed argv, no shell
    assert result.returncode == 0, "volume adjustment host build failed:\n" + result.stderr
    return out


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_volume_adjustment_scenario(volume_adjustment_binary, scenario):
    result = subprocess.run(  # nosec B603 - locally built test binary, fixed scenario argv
        [str(volume_adjustment_binary), scenario], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr

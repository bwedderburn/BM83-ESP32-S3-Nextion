"""Compile actual hardware-independent artwork and setup protocol helpers."""
import os
import shutil
import subprocess  # nosec B404 - host-only regression compiler harness
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ROOT / "firmware/crowpanel-remote/include"
HOST = ROOT / "tests/crowpanel_host"


@pytest.mark.parametrize("name", ["matching", "album_fallback", "tls_time", "network_setup_parser"])
def test_artwork_host_helpers(name, tmp_path):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("no C++ compiler available")
    binary = tmp_path / name
    command = [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic",
               "-I" + str(INCLUDE), str(HOST / ("artwork_" + name + "_test.cpp")), "-o", str(binary)]
    if os.environ.get("RUN_ARTWORK_SANITIZERS") == "1":
        command[1:1] = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    result = subprocess.run(command, capture_output=True, text=True)  # nosec B603 - fixed local test sources/argv, no shell
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True)  # nosec B603 - execute the binary built by this test
    assert result.returncode == 0, result.stdout + result.stderr

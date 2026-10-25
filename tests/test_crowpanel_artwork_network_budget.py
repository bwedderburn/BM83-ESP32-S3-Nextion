"""Compile the actual artwork TLS deadline helper without network or hardware."""
import os
from pathlib import Path
import shutil
import subprocess  # nosec B404 - fixed local regression compiler harness

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_artwork_tls_handshake_budget_respects_total_deadline_and_millis_wrap(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("no C++ compiler available")
    binary = tmp_path / "artwork_network_budget"
    command = [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic",
               "-I" + str(ROOT / "firmware/crowpanel-remote/include"),
               str(ROOT / "tests/crowpanel_host/artwork_network_budget_test.cpp"), "-o", str(binary)]
    if os.environ.get("RUN_ARTWORK_SANITIZERS") == "1":
        command[1:1] = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    built = subprocess.run(command, capture_output=True, text=True)  # nosec B603 - fixed argv, no shell
    assert built.returncode == 0, built.stdout + built.stderr
    tested = subprocess.run([str(binary)], capture_output=True, text=True)  # nosec B603 - just-built local binary
    assert tested.returncode == 0, tested.stdout + tested.stderr

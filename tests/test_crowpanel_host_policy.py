"""Compile and run the production bounded host-policy codec and transaction model."""
import os
import json
from pathlib import Path
import shutil
import subprocess  # nosec B404 - fixed local C++ source and owned test executable

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def host_policy_binary(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("no host C++ compiler")
    binary = tmp_path_factory.mktemp("host_policy") / ("test.exe" if os.name == "nt" else "test")
    build = subprocess.run(  # nosec B603 - fixed owned paths, no shell or device access
        [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic",
         "-I" + str(ROOT / "firmware/crowpanel-remote/include"),
         str(ROOT / "tests/crowpanel_host/ble_host_policy_test.cpp"), "-o", str(binary)],
        text=True, capture_output=True)
    assert build.returncode == 0, build.stderr
    return binary


@pytest.mark.parametrize("scenario", ("codec", "fragments", "ordering", "completion", "generations", "operations", "golden-commands", "durability", "supersession", "handshake", "handshake-reboots", "admission-lost", "link-history", "enroll-timeout"))
def test_production_host_policy(host_policy_binary, scenario):
    run = subprocess.run(  # nosec B603 - locally built executable, fixed scenario argument
        [str(host_policy_binary), scenario], text=True, capture_output=True)
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.parametrize("kind", ("status", "max_list", "unsupported"))
def test_python_producer_golden_frames(host_policy_binary, kind):
    vectors = json.loads((ROOT / "tests/fixtures/ble_host_policy_v1.json").read_text())
    run = subprocess.run(  # nosec B603 - fixed owned binary; fixture contains inert hex bytes only
        [str(host_policy_binary), "golden-frames", kind, *vectors[kind]["frames_hex"]],
        text=True, capture_output=True)
    assert run.returncode == 0, run.stdout + run.stderr

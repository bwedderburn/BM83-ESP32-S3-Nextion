"""Host tests for the CrowPanel remote's battery gauge and supply detection.

firmware/crowpanel-remote/src/battery.cpp decides whether the remote is on
USB or battery, and that picks its sleep policy: a wrong "battery" would put
a USB-powered remote into light sleep that only the BOOT button can end.
These tests compile it against a small Arduino stand-in
(tests/crowpanel_host/Arduino.h) with the divider settings from
platformio.ini, and run every scenario in tests/crowpanel_host/battery_test.cpp
in its own process, because the module keeps its state in file-scope
variables. They need a C++17 compiler (g++ on the CI runners) and skip
where there is none.
"""
import re
import shutil
import subprocess  # nosec B404 - runs the compiler and the binary it builds here
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REMOTE_DIR = REPO_ROOT / "firmware" / "crowpanel-remote"
HOST_DIR = Path(__file__).resolve().parent / "crowpanel_host"


def _build_flag(name):
    ini = (REMOTE_DIR / "platformio.ini").read_text(encoding="utf-8")
    match = re.search(r"-D%s=([0-9.]+f?)" % name, ini)
    assert match, "%s missing from platformio.ini build_flags" % name
    return match.group(1)


@pytest.fixture(scope="module")
def battery_test_binary(tmp_path_factory):
    cxx = shutil.which("g++") or shutil.which("clang++")
    if not cxx:
        pytest.skip("no C++ compiler on this machine")
    out = tmp_path_factory.mktemp("battery_host") / "battery_test"
    cmd = [
        cxx, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-DBATTERY_ADC_PIN=%s" % _build_flag("BATTERY_ADC_PIN"),
        "-DBATTERY_DIVIDER_RATIO=%s" % _build_flag("BATTERY_DIVIDER_RATIO"),
        "-I%s" % HOST_DIR,
        "-I%s" % (REMOTE_DIR / "include"),
        str(HOST_DIR / "battery_test.cpp"),
        str(REMOTE_DIR / "src" / "battery.cpp"),
        "-o", str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)  # nosec B603 - fixed argv, no shell
    assert result.returncode == 0, "battery host build failed:\n" + result.stderr
    return out


def test_battery_adc_is_configured():
    # The gauge and the battery sleep timings are inert with pin 0.
    assert _build_flag("BATTERY_ADC_PIN") == "17"


def test_battery_scenarios(battery_test_binary):
    listed = subprocess.run(  # nosec B603 - binary built above, fixed argv
        [str(battery_test_binary), "--list"], capture_output=True, text=True, check=True)
    names = listed.stdout.split()
    assert len(names) >= 14, names
    failures = []
    for name in names:
        result = subprocess.run(  # nosec B603 - binary built above, fixed argv
            [str(battery_test_binary), name], capture_output=True, text=True)
        if result.returncode != 0:
            failures.append(result.stdout + result.stderr)
    assert not failures, "\n".join(failures)

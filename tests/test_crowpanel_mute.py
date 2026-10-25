"""Run the CrowPanel's production footer builder and click callbacks on host."""
import shutil
import subprocess  # nosec B404 - fixed local C++ compiler harness
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_mute_is_single_click_and_footer_controls_do_not_overlap(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("no C++ compiler available")
    source = (ROOT / "firmware/crowpanel-remote/src/main.cpp").read_text()

    def section(start, end):
        offset = source.index(start)
        return source[offset:source.index(end, offset)]

    runtime = section("static const char *action_name(", "static bool note_token(")
    runtime += section("static void cb_click(", "static lv_obj_t *make_label(")
    runtime += section("static void build_transport_controls(", "static void build_ui()")
    (tmp_path / "mute_controls_runtime.inc").write_text(runtime)
    binary = tmp_path / "mute_controls"
    command = [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic",
               "-I" + str(tmp_path), str(ROOT / "tests/crowpanel_host/mute_controls_test.cpp"),
               "-o", str(binary)]
    result = subprocess.run(command, capture_output=True, text=True)  # nosec B603 - fixed local test argv, no shell
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True)  # nosec B603 - locally compiled harness
    assert result.returncode == 0, result.stdout + result.stderr

"""Check bounded display composition and the production metadata/artwork flow."""
import os
from pathlib import Path
import shutil
import subprocess  # nosec B404 - fixed local compiler and host test binary

import pytest

ROOT = Path(__file__).resolve().parents[1]
REMOTE = ROOT / "firmware/crowpanel-remote"
SCENARIOS = ("captured-title", "exact-pairs", "unchanged", "capacity", "invalid-utf8",
             "long-input", "integration")


@pytest.fixture(scope="module")
def metadata_text_binary(tmp_path_factory):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("no C++ compiler available")
    build = tmp_path_factory.mktemp("metadata_text_host")
    source = (REMOTE / "src/main.cpp").read_text()

    def section(start, end):
        offset = source.index(start)
        return source[offset:source.index(end, offset)]

    runtime = section("static void request_artwork(", "static const char *artwork_status_name(")
    runtime += section("static void ui_set_now_playing(", "static void build_transport_controls(")
    (build / "metadata_text_runtime.inc").write_text(runtime)
    binary = build / ("metadata_text_test.exe" if os.name == "nt" else "metadata_text_test")
    result = subprocess.run(  # nosec B603 - fixed local source/include paths, no shell
        [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic",
         "-I" + str(REMOTE / "include"), "-I" + str(build),
         str(ROOT / "tests/crowpanel_host/metadata_text_test.cpp"), "-o", str(binary)],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_metadata_display_text(metadata_text_binary, scenario):
    result = subprocess.run(  # nosec B603 - locally built host test, fixed scenario argv
        [str(metadata_text_binary), scenario], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr

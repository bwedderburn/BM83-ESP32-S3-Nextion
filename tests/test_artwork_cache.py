"""Exercise the production SD cache reader against old on-card records."""
import os
import re
import shutil
import subprocess  # nosec B404 - host-only regression compiler harness
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/crowpanel-remote"


def test_artwork_cache_compatibility(tmp_path):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("no C++ compiler available")
    source = (FIRMWARE / "src/artwork.cpp").read_text()

    def section(start, end):
        # Compile these production definitions unchanged. A source refactor
        # should update this seam instead of leaving a copied reader behind.
        return source[source.index(start):source.index(end, source.index(start))]

    constants = re.findall(
        r"^(?:constexpr size_t TEXT_MAX[^\n]+|const char (?:CACHE_DIR\[\]|META_MAGIC(?:_V\d+)?\[8\])[^\n]+)$",
        source, re.MULTILINE,
    )
    assert constants
    (tmp_path / "artwork_cache_types.inc").write_text(
        "\n".join(constants) + "\n" + section("struct Job {", "struct Entry {")
        + section("String path_for(", "bool cache_hash(")
    )
    (tmp_path / "artwork_cache_runtime.inc").write_text(
        section("bool read_meta(", "void clean_incomplete_cache() {")
        + section("bool cached(", "String request_host(")
    )
    binary = tmp_path / "artwork_cache"
    command = [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic",
               "-I" + str(FIRMWARE / "include"), "-I" + str(tmp_path),
               str(ROOT / "tests/crowpanel_host/artwork_cache_test.cpp"), "-o", str(binary)]
    if os.environ.get("RUN_ARTWORK_SANITIZERS") == "1":
        command[1:1] = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    result = subprocess.run(command, capture_output=True, text=True)  # nosec B603 - fixed local compiler/source argv, no shell
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True)  # nosec B603 - run only the locally built harness
    assert result.returncode == 0, result.stdout + result.stderr

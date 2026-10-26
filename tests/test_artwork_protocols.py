"""Compile actual hardware-independent artwork and setup protocol helpers."""
import os
import json
import shutil
import subprocess  # nosec B404 - host-only regression compiler harness
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ROOT / "firmware/crowpanel-remote/include"
HOST = ROOT / "tests/crowpanel_host"


@pytest.mark.parametrize("name", ["matching", "artist_aliases", "artist_credit", "album_fallback",
                                  "tls_time", "network_setup_parser"])
def test_artwork_host_helpers(name, tmp_path):
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        pytest.skip("no C++ compiler available")
    if name == "artist_credit":
        source = (ROOT / "firmware/crowpanel-remote/src/artwork.cpp").read_text()

        def section(start, end):
            # Compile actual production text/credit adapters unchanged. A
            # refactor must update this seam rather than leave a copied helper.
            begin = source.index(start)
            return source[begin:source.index(end, begin)]

        (tmp_path / "artwork_artist_credit.inc").write_text(
            section("const char *text(", "unsigned score(")
            + section("const char *credited_artist(", "bool compilation(")
        )
    binary = tmp_path / name
    command = [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic",
               "-I" + str(INCLUDE), "-I" + str(tmp_path),
               str(HOST / ("artwork_" + name + "_test.cpp")), "-o", str(binary)]
    if os.environ.get("RUN_ARTWORK_SANITIZERS") == "1":
        command[1:1] = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    result = subprocess.run(command, capture_output=True, text=True)  # nosec B603 - fixed local test sources/argv, no shell
    assert result.returncode == 0, result.stdout + result.stderr
    arguments = [str(binary)]
    if name == "matching":
        payload = json.loads((ROOT / "tests/fixtures/musicbrainz_animals_as_leaders_encore.json").read_text())
        strict = payload["strict_response"]
        assert strict["count"] == len(strict["release-groups"]) == 0
        fallback = payload["fallback_response"]
        assert fallback["count"] == len(fallback["release-groups"]) == 1
        group = fallback["release-groups"][0]
        credits = group["artist-credit"]
        assert len(credits) == 1 and group["primary-type"] == "Album"
        assert not group.get("secondary-types")
        arguments += [credits[0]["name"], group["title"], group["id"],
                      str(group["score"]), str(len(credits)), group["primary-type"]]
    if name in ("artist_aliases", "artist_credit"):
        # Exact MusicBrainz HTTP200 response from the production strict query;
        # its canonical Ż credit includes the plain-Z provider alias.
        payload = json.loads((ROOT / "tests/fixtures/musicbrainz_jakub_nothing_lasts.json").read_text())
        assert payload["count"] == len(payload["release-groups"]) == 1
        group = payload["release-groups"][0]
        credits = group["artist-credit"]
        assert len(credits) == 1
        artist = credits[0]["artist"]
        alias = next(alias for alias in artist["aliases"] if alias["name"] == "Jakub Zytecki")
        arguments += [credits[0]["name"], artist["name"], artist["id"], alias["name"], alias.get("type") or "",
                      group["title"], group["id"], str(group["score"]), str(len(credits)), group["primary-type"]]
    result = subprocess.run(arguments, capture_output=True, text=True)  # nosec B603 - execute the binary built by this test
    assert result.returncode == 0, result.stdout + result.stderr

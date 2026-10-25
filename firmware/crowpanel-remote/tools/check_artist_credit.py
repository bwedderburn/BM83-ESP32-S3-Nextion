#!/usr/bin/env python3
"""Check the production artist adapter with supplied ArduinoJson 7.4.3 headers.

Host-only; no network, device ports or firmware deployment. For example:
python3 firmware/crowpanel-remote/tools/check_artist_credit.py \
    --arduinojson /path/to/libdeps/crowpanel_esp32s3_7in/ArduinoJson
"""

import argparse
from pathlib import Path
import re
import shutil
import subprocess  # nosec B404 - fixed local compiler/test argv
import tempfile

REMOTE = Path(__file__).resolve().parents[1]
ROOT = REMOTE.parents[1]
VERSION = "7.4.3"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arduinojson", required=True, type=Path,
                        help="ArduinoJson dependency root containing src/ArduinoJson.h")
    args = parser.parse_args()
    include = args.arduinojson.resolve(strict=True) / "src"
    version_file = include / "ArduinoJson/version.hpp"
    if not (include / "ArduinoJson.h").is_file() or not version_file.is_file():
        raise SystemExit("Expected ArduinoJson dependency root with src/ArduinoJson.h")
    actual = re.search(r'^#define ARDUINOJSON_VERSION "([^"]+)"', version_file.read_text(), re.M)
    if not actual or actual.group(1) != VERSION:
        raise SystemExit("ArduinoJson %s headers are required" % VERSION)
    compiler = shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        raise SystemExit("A native clang++ or g++ compiler is required")
    source = (REMOTE / "src/artwork.cpp").read_text()

    def section(start, end):
        begin = source.index(start)
        return source[begin:source.index(end, begin)]

    with tempfile.TemporaryDirectory(prefix="bm83-artist-credit-") as directory:
        work = Path(directory)
        (work / "artwork_artist_credit.inc").write_text(
            section("const char *text(", "unsigned score(")
            + section("const char *credited_artist(", "bool compilation(")
        )
        binary = work / "artist_credit_arduinojson"
        subprocess.run([  # nosec B603 - local source/header paths, no shell
            compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic",
            "-I" + str(include), "-I" + str(REMOTE / "include"), "-I" + str(work),
            str(ROOT / "tests/crowpanel_host/artwork_artist_credit_arduinojson_test.cpp"),
            "-o", str(binary),
        ], check=True)
        subprocess.run([  # nosec B603 - locally compiled test, public fixture
            str(binary), str(ROOT / "tests/fixtures/musicbrainz_jakub_nothing_lasts.json"),
        ], check=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Exercise shipped metadata fonts with the real LVGL 8.3.11 font decoder."""

import argparse
from pathlib import Path
import re
import shutil
import subprocess  # nosec B404 - local compilers and locally built test binary
import tempfile

REMOTE = Path(__file__).resolve().parents[1]
REPO = REMOTE.parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lvgl", type=Path, required=True,
                        help="LVGL source directory from the pinned PlatformIO dependency")
    args = parser.parse_args()
    lvgl = args.lvgl.resolve(strict=True)
    header = (lvgl / "lvgl.h").read_text()
    for field, value in (("MAJOR", 8), ("MINOR", 3), ("PATCH", 11)):
        if not re.search(r"#define\s+LVGL_VERSION_%s\s+%d\b" % (field, value), header):
            raise SystemExit("This check requires pinned LVGL 8.3.11")
    cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    cxx = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if not cc or not cxx:
        raise SystemExit("C and C++ host compilers are required")
    flags = ["-DLV_CONF_SKIP", "-DLV_USE_ASSERT_NULL=0", "-DLV_USE_ASSERT_MALLOC=0",
             "-DLV_USE_FONT_PLACEHOLDER=1", "-DLV_FONT_MONTSERRAT_18=1",
             "-DLV_FONT_MONTSERRAT_20=1", "-DLV_FONT_MONTSERRAT_28=1",
             "-I%s" % lvgl, "-I%s" % (REMOTE / "include")]
    sources = [lvgl / "src" / "font" / name for name in (
        "lv_font.c", "lv_font_fmt_txt.c", "lv_font_montserrat_18.c",
        "lv_font_montserrat_20.c", "lv_font_montserrat_28.c")]
    sources += [lvgl / "src" / "misc" / "lv_utils.c"]
    sources += sorted((REMOTE / "src" / "fonts").glob("bm83_latin_*.c"))
    with tempfile.TemporaryDirectory(prefix="bm83-font-check-") as directory:
        output = Path(directory)
        objects = []
        for source in sources:
            obj = output / (source.stem + ".o")
            subprocess.run([cc, "-std=c99", *flags, "-c", str(source), "-o", str(obj)],
                           check=True)  # nosec B603 - fixed argv, no shell
            objects.append(str(obj))
        binary = output / "metadata_fonts_lvgl_test"
        subprocess.run([  # nosec B603 - fixed argv, no shell
            cxx, "-std=c++17", *flags, str(REMOTE / "src" / "metadata_fonts.cpp"),
            str(REPO / "tests" / "crowpanel_host" / "metadata_fonts_lvgl_test.cpp"),
            *objects, "-o", str(binary),
        ], check=True)
        subprocess.run([str(binary)], check=True)  # nosec B603 - compiled test, no shell


if __name__ == "__main__":
    main()

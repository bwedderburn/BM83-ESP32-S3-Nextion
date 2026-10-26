#!/usr/bin/env python3
"""Check shipped font decoding and offscreen labels with real LVGL 8.3.11."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import os
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
    parser.add_argument("--render-output", type=Path,
                        help="optional directory for before/after PPM images")
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
             "-DLV_MEM_CUSTOM=1", "-DLV_COLOR_DEPTH=16", "-DLV_COLOR_16_SWAP=0",
             "-DLV_USE_FONT_PLACEHOLDER=1", "-DLV_FONT_MONTSERRAT_18=1",
             "-DLV_FONT_MONTSERRAT_20=1", "-DLV_FONT_MONTSERRAT_28=1",
             "-I%s" % lvgl, "-I%s" % (REMOTE / "include")]
    # The complete pinned renderer is needed: decoding glyph descriptors alone
    # cannot establish that a real label paints its accents without clipping.
    sources = sorted((lvgl / "src").rglob("*.c"))
    sources += sorted((REMOTE / "src" / "fonts").glob("bm83_latin_*.c"))
    with tempfile.TemporaryDirectory(prefix="bm83-font-check-") as directory:
        output = Path(directory)

        def compile_source(item):
            index, source = item
            obj = output / ("%03d_%s.o" % (index, source.stem))
            subprocess.run([cc, "-std=c99", *flags, "-c", str(source), "-o", str(obj)],
                           check=True)  # nosec B603 - fixed argv, no shell
            return str(obj)

        with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 1)) as workers:
            objects = list(workers.map(compile_source, enumerate(sources)))
        for name in ("metadata_fonts_lvgl_test", "metadata_text_lvgl_render_test"):
            binary = output / name
            subprocess.run([  # nosec B603 - fixed argv, no shell
                cxx, "-std=c++17", *flags, str(REMOTE / "src" / "metadata_fonts.cpp"),
                str(REPO / "tests" / "crowpanel_host" / (name + ".cpp")),
                *objects, "-lm", "-o", str(binary),
            ], check=True)
            command = [str(binary)]
            if name == "metadata_text_lvgl_render_test" and args.render_output:
                destination = args.render_output.resolve()
                destination.mkdir(parents=True, exist_ok=True)
                command.append(str(destination))
            subprocess.run(command, check=True)  # nosec B603 - compiled test, no shell


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit("LVGL host check failed (exit %d)" % error.returncode) from None

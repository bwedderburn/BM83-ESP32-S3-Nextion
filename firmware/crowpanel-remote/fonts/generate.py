#!/usr/bin/env python3
"""Regenerate metadata font assets with the pinned, locally installed converter."""

import argparse
import hashlib
from pathlib import Path
import subprocess  # nosec B404 - invokes the explicitly supplied local build tool

ROOT = Path(__file__).resolve().parent
FONT_SHA256 = "421f26b23e2be6b98373d32acd3cb2897b154d4bf0a77d26534ce476e4cbed53"
CONVERTER_VERSION = "1.5.3"
RANGES = "0xA0-0x17F,0x2010-0x2027,0x2030,0x2039-0x203A,0x20AC,0x2122"


def harden_latin_cmap(path):
    # LVGL 8.3.11's dense cmap decoder accepts range_start + range_length,
    # one past the converter's final glyph. An explicit sparse membership list
    # avoids displaying the next cmap's first glyph for unsupported U+0180.
    text = path.read_text(encoding="utf-8")
    original = (
        ".range_start = 160, .range_length = 224, .glyph_id_start = 1,\n"
        "        .unicode_list = NULL, .glyph_id_ofs_list = NULL, .list_length = 0, "
        ".type = LV_FONT_FMT_TXT_CMAP_FORMAT0_TINY")
    replacement = (
        ".range_start = 160, .range_length = 224, .glyph_id_start = 1,\n"
        "        .unicode_list = latin_unicode_list, .glyph_id_ofs_list = NULL, "
        ".list_length = 224, .type = LV_FONT_FMT_TXT_CMAP_SPARSE_TINY")
    marker = "/*Collect the unicode lists and glyph_id offsets*/"
    if text.count(original) != 1 or text.count(marker) != 1:
        raise SystemExit("Unexpected converter cmap layout in %s" % path)
    rows = ["    " + ", ".join("0x%x" % value for value in range(start, start + 8))
            for start in range(0, 224, 8)]
    explicit_list = (
        "/*Explicit membership avoids the LVGL 8.3.11 dense-cmap end-boundary quirk.*/\n"
        "static const uint16_t latin_unicode_list[] = {\n" + ",\n".join(rows) + "\n};\n\n")
    text = text.replace(original, replacement).replace(marker, explicit_list + marker)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--converter", required=True, type=Path,
                        help="path to lv_font_conv from the locked tooling install")
    args = parser.parse_args()
    converter = args.converter.resolve(strict=True)
    font = ROOT / "Montserrat-Medium.ttf"
    if hashlib.sha256(font.read_bytes()).hexdigest() != FONT_SHA256:
        raise SystemExit("Montserrat source hash does not match pinned LVGL 8.3.11")
    version = subprocess.run(  # nosec B603 - explicit local tool, no shell
        [str(converter), "--version"], check=True, capture_output=True, text=True)
    if version.stdout.strip() != CONVERTER_VERSION:
        raise SystemExit("lv_font_conv %s is required" % CONVERTER_VERSION)
    for size in (18, 20, 28):
        subprocess.run([  # nosec B603 - fixed arguments, no shell/network
            str(converter), "--no-compress", "--no-prefilter", "--bpp", "4",
            "--size", str(size), "--font", font.name, "-r", RANGES,
            "--format", "lvgl", "--lv-font-name", "bm83_latin_%d" % size,
            "--lv-include", "lvgl.h", "--force-fast-kern-format",
            "-o", "../src/fonts/bm83_latin_%d.c" % size,
        ], cwd=ROOT, check=True)
        harden_latin_cmap(ROOT / ".." / "src" / "fonts" / ("bm83_latin_%d.c" % size))


if __name__ == "__main__":
    main()

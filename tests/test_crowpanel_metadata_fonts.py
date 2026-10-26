"""Validate shipped font glyphs/metrics and the production fallback wrappers."""

import hashlib
from pathlib import Path
import re
import runpy
import shutil
import subprocess  # nosec B404 - fixed local compiler and host test binary

import pytest

ROOT = Path(__file__).resolve().parents[1]
REMOTE = ROOT / "firmware" / "crowpanel-remote"
HOST = ROOT / "tests" / "crowpanel_host"


def _array(source, name):
    match = re.search(r"\b%s\[\]\s*=\s*\{(.*?)\};" % name, source, re.S)
    assert match, name
    return re.sub(r"/\*.*?\*/", "", match.group(1), flags=re.S)


def _numbers(source):
    return [int(value, 0) for value in re.findall(r"0x[0-9a-fA-F]+|-?\d+", source)]


def _font(size):
    source = (REMOTE / "src" / "fonts" / ("bm83_latin_%d.c" % size)).read_text()
    glyphs = [dict((key, int(value)) for key, value in
                   re.findall(r"\.(\w+)\s*=\s*(-?\d+)", row))
              for row in re.findall(r"\{([^}]+)\}", _array(source, "glyph_dsc"))]
    bitmaps = _numbers(_array(source, "glyph_bitmap"))
    # Decode the actual generated cmap, not comments or the generator's ranges.
    codepoints = {}
    for cmap in re.findall(r"\{([^}]+)\}", _array(source, "cmaps")):
        def value(name):
            return int(re.search(r"\.%s\s*=\s*(\d+)" % name, cmap).group(1))
        start, glyph_start = value("range_start"), value("glyph_id_start")
        if "LV_FONT_FMT_TXT_CMAP_FORMAT0_TINY" in cmap:
            codes = range(value("range_length"))
        else:
            assert "LV_FONT_FMT_TXT_CMAP_SPARSE_TINY" in cmap
            array = re.search(r"\.unicode_list\s*=\s*(\w+)", cmap).group(1)
            codes = _numbers(_array(source, array))
            assert len(codes) == value("list_length")
            assert codes == sorted(set(codes))
        for index, code in enumerate(codes):
            assert start + code not in codepoints
            codepoints[start + code] = glyph_start + index
    height = int(re.search(r"\.line_height\s*=\s*(\d+)", source).group(1))
    baseline = int(re.search(r"\.base_line\s*=\s*(\d+)", source).group(1))
    return glyphs, bitmaps, codepoints, height, baseline


@pytest.mark.parametrize("size", [18, 20, 28])
def test_latin_glyphs_have_real_bitmaps_and_fit_metadata_lines(size):
    glyphs, bitmaps, codes, height, baseline = _font(size)
    assert set(range(0xA0, 0x180)) <= codes.keys()
    assert set(map(ord, "éíâÉÁÇŁœŸÆßñø—‘’“”…€™Ӧӧ")) <= codes.keys()
    assert len(codes) == 246
    assert 0x180 not in codes and 0x4E8 not in codes
    # Dense cmaps have an end-boundary ambiguity in pinned LVGL 8.3.11.
    source = (REMOTE / "src/fonts" / ("bm83_latin_%d.c" % size)).read_text()
    assert "LV_FONT_FMT_TXT_CMAP_FORMAT0_" not in source
    assert len(glyphs) == len(codes) + 1  # glyph zero is the missing-glyph sentinel
    for code, glyph_id in codes.items():
        glyph = glyphs[glyph_id]
        start = glyph["bitmap_index"]
        length = (glyph["box_w"] * glyph["box_h"] + 1) // 2  # 4bpp, uncompressed
        assert 0 <= start <= len(bitmaps)
        assert start + length <= len(bitmaps)
        if code not in (0xA0, 0xAD):  # nonbreaking space / soft hyphen may be blank
            assert glyph["box_w"] > 0 and glyph["box_h"] > 0, hex(code)
            assert any(bitmaps[start:start + length]), hex(code)
        assert glyph["box_h"] + glyph["ofs_y"] <= height - baseline
        assert glyph["ofs_y"] >= -baseline
    # The existing title label is 76px high and can retain two lines.
    if size == 28:
        assert height * 2 <= 76
    if size == 18:
        assert height * 2 <= 48


def test_generator_hardens_multiple_dense_ranges(tmp_path):
    # The converter currently merges Cyrillic and punctuation into a sparse
    # map. Also cover a separately emitted two-glyph dense range, so a future
    # layout cannot reintroduce the U+04E8 end-boundary substitution.
    path = tmp_path / "font.c"
    path.write_text("/*Collect the unicode lists and glyph_id offsets*/\n" +
                    "\n".join(
                        ".range_start = %d, .range_length = %d, .glyph_id_start = %d,\n"
                        "        .unicode_list = NULL, .glyph_id_ofs_list = NULL, .list_length = 0, "
                        ".type = LV_FONT_FMT_TXT_CMAP_FORMAT0_TINY" % values
                        for values in ((160, 224, 1), (1254, 2, 225))))
    generator = runpy.run_path(str(REMOTE / "fonts/generate.py"))
    generator["harden_dense_cmaps"](path)
    source = path.read_text()
    assert "LV_FONT_FMT_TXT_CMAP_FORMAT0_" not in source
    assert source.count("LV_FONT_FMT_TXT_CMAP_SPARSE_TINY") == 2
    names = re.findall(r"\.unicode_list = (\w+)", source)
    assert [_numbers(_array(source, name)) for name in names] == [list(range(224)), [0, 1]]
    assert ".range_start = 1254, .range_length = 2, .glyph_id_start = 225" in source


def test_font_source_and_tooling_are_pinned():
    source = REMOTE / "fonts" / "Montserrat-Medium.ttf"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        "421f26b23e2be6b98373d32acd3cb2897b154d4bf0a77d26534ce476e4cbed53")
    assert "SIL OPEN FONT LICENSE Version 1.1" in (REMOTE / "fonts" / "OFL.txt").read_text()


def test_metadata_wrappers_preserve_base_and_fallback_metrics(tmp_path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("no C++ compiler on this machine")
    binary = tmp_path / "metadata_fonts_test"
    result = subprocess.run([  # nosec B603 - fixed argv, no shell
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-I%s" % (HOST / "font_stubs"), "-I%s" % (REMOTE / "include"),
        str(HOST / "metadata_fonts_test.cpp"), str(REMOTE / "src" / "metadata_fonts.cpp"),
        "-o", str(binary),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    subprocess.run([str(binary)], check=True)  # nosec B603 - compiled host test, no shell

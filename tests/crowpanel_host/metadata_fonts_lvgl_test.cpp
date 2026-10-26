// Run against the real pinned LVGL decoder with fonts/check_lvgl.py.
#include "metadata_fonts.h"

#include <cassert>
#include <cstdio>
#include <initializer_list>

static void check(const lv_font_t *font, const lv_font_t &base) {
    lv_font_glyph_dsc_t glyph;
    for (uint32_t code = 0xA0; code <= 0x17F; ++code) {
        assert(lv_font_get_glyph_dsc(font, &glyph, code, 0));
        assert(!glyph.is_placeholder && glyph.resolved_font);
        if (code != 0xA0 && code != 0xAD) {
            assert(glyph.box_w && glyph.box_h);
            assert(lv_font_get_glyph_bitmap(glyph.resolved_font, code));
        }
        assert(glyph.box_h + glyph.ofs_y <= font->line_height - font->base_line);
        assert(glyph.ofs_y >= -font->base_line);
    }
    for (uint32_t code : {0x2014u, 0x2018u, 0x2019u, 0x201Cu, 0x201Du,
                          0x2026u, 0x20ACu, 0x2122u}) {
        assert(lv_font_get_glyph_dsc(font, &glyph, code, 0));
        assert(!glyph.is_placeholder && glyph.resolved_font);
        assert(lv_font_get_glyph_bitmap(glyph.resolved_font, code));
    }
    for (uint32_t code : {uint32_t('A'), uint32_t('e'), 0xF028u}) {
        lv_font_glyph_dsc_t original;
        assert(lv_font_get_glyph_dsc(&base, &original, code, 0));
        assert(lv_font_get_glyph_dsc(font, &glyph, code, 0));
        assert(glyph.resolved_font == font);
        assert(glyph.adv_w == original.adv_w);
        assert(glyph.box_w == original.box_w && glyph.box_h == original.box_h);
        assert(lv_font_get_glyph_bitmap(font, code) == lv_font_get_glyph_bitmap(&base, code));
    }
    // User examples include Latin accents and Cyrillic O/o with diaeresis.
    for (uint32_t code : {0xE9u, 0xEDu, 0xE2u, 0x4E6u, 0x4E7u}) {
        assert(lv_font_get_glyph_dsc(font, &glyph, code, 0));
        assert(!glyph.is_placeholder && glyph.resolved_font == font->fallback);
        assert(glyph.box_w && glyph.box_h);
        assert(lv_font_get_glyph_bitmap(glyph.resolved_font, code));
        assert(glyph.box_h + glyph.ofs_y <= font->line_height - font->base_line);
        assert(glyph.ofs_y >= -font->base_line);
    }
    assert(!lv_font_get_glyph_dsc(font, &glyph, 0x180, 0));  // just beyond supported Latin
    assert(!lv_font_get_glyph_dsc(font, &glyph, 0x4E8, 0));  // just beyond Cyrillic pair
    assert(!lv_font_get_glyph_dsc(font, &glyph, 0x4E2D, 0));  // no full CJK promise
    std::printf("LVGL glyphs/bitmap/baseline passed: height=%d baseline=%d\n",
                font->line_height, font->base_line);
}

int main() {
    check(metadata_fonts::title(), lv_font_montserrat_28);
    check(metadata_fonts::artist(), lv_font_montserrat_20);
    check(metadata_fonts::album(), lv_font_montserrat_18);
}

#include "metadata_fonts.h"

#include <cassert>

namespace {
const uint8_t bitmap = 42;
bool descriptor(const lv_font_t *, lv_font_glyph_dsc_t *, uint32_t, uint32_t) {
    return false;
}
const uint8_t *get_bitmap(const lv_font_t *, uint32_t) { return &bitmap; }
}  // namespace

// Deliberately different base/fallback metrics exercise independent ascent and
// descent handling as well as retaining all original bitmap/style fields.
const lv_font_t lv_font_montserrat_18 = {
    descriptor, get_bitmap, 21, 4, 0, -1, 1, &bitmap, nullptr, nullptr};
const lv_font_t lv_font_montserrat_20 = {
    descriptor, get_bitmap, 22, 7, 0, -1, 1, &bitmap, nullptr, nullptr};
const lv_font_t lv_font_montserrat_28 = {
    descriptor, get_bitmap, 40, 5, 0, -2, 1, &bitmap, nullptr, nullptr};
extern "C" {
extern const lv_font_t bm83_latin_18 = {
    descriptor, get_bitmap, 24, 5, 0, -1, 1, &bitmap, nullptr, nullptr};
extern const lv_font_t bm83_latin_20 = {
    descriptor, get_bitmap, 26, 6, 0, -1, 1, &bitmap, nullptr, nullptr};
extern const lv_font_t bm83_latin_28 = {
    descriptor, get_bitmap, 37, 8, 0, -2, 1, &bitmap, nullptr, nullptr};
}

static void check(const lv_font_t *font, const lv_font_t &base,
                  const lv_font_t &latin, int height, int baseline) {
    assert(font != &base);
    assert(font->fallback == &latin);
    assert(base.fallback == nullptr);
    assert(latin.fallback == nullptr);
    assert(font->line_height == height);
    assert(font->base_line == baseline);
    assert(font->get_glyph_dsc == base.get_glyph_dsc);
    assert(font->get_glyph_bitmap == base.get_glyph_bitmap);
    assert(font->dsc == base.dsc);
    assert(font->subpx == base.subpx);
    assert(font->underline_position == base.underline_position);
    assert(font->underline_thickness == base.underline_thickness);
    assert(font->user_data == base.user_data);
}

int main() {
    check(metadata_fonts::album(), lv_font_montserrat_18, bm83_latin_18, 24, 5);
    check(metadata_fonts::artist(), lv_font_montserrat_20, bm83_latin_20, 27, 7);
    check(metadata_fonts::title(), lv_font_montserrat_28, bm83_latin_28, 43, 8);
    assert(metadata_fonts::title() == metadata_fonts::title());
    assert(metadata_fonts::artist() == metadata_fonts::artist());
    assert(metadata_fonts::album() == metadata_fonts::album());
}

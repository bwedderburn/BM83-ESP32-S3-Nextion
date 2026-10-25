#include "metadata_fonts.h"

extern "C" {
LV_FONT_DECLARE(bm83_latin_18);
LV_FONT_DECLARE(bm83_latin_20);
LV_FONT_DECLARE(bm83_latin_28);
}

namespace {
lv_font_t with_latin_fallback(const lv_font_t &base, const lv_font_t &latin) {
    lv_font_t font = base;
    font.fallback = &latin;
    // LVGL draws fallback bitmaps on the primary font's baseline. Preserve the
    // largest ascent and descent so uppercase accents and low glyphs fit too.
    const lv_coord_t ascent = base.line_height - base.base_line;
    const lv_coord_t latin_ascent = latin.line_height - latin.base_line;
    font.base_line = base.base_line > latin.base_line ? base.base_line : latin.base_line;
    font.line_height = (ascent > latin_ascent ? ascent : latin_ascent) + font.base_line;
    return font;
}
}  // namespace

namespace metadata_fonts {
const lv_font_t *title() {
    static const lv_font_t font = with_latin_fallback(lv_font_montserrat_28, bm83_latin_28);
    return &font;
}

const lv_font_t *artist() {
    static const lv_font_t font = with_latin_fallback(lv_font_montserrat_20, bm83_latin_20);
    return &font;
}

const lv_font_t *album() {
    static const lv_font_t font = with_latin_fallback(lv_font_montserrat_18, bm83_latin_18);
    return &font;
}
}  // namespace metadata_fonts

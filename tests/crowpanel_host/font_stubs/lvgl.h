#pragma once

#include <cstdint>

// Font descriptor shape used by metadata_fonts.cpp, independent of LVGL's UI
// engine. The generated bitmap/cmap assets are validated separately in Python.
using lv_coord_t = int16_t;
struct lv_font_glyph_dsc_t;
struct lv_font_t {
    bool (*get_glyph_dsc)(const lv_font_t *, lv_font_glyph_dsc_t *, uint32_t, uint32_t);
    const uint8_t *(*get_glyph_bitmap)(const lv_font_t *, uint32_t);
    lv_coord_t line_height;
    lv_coord_t base_line;
    uint8_t subpx : 2;
    int8_t underline_position;
    int8_t underline_thickness;
    const void *dsc;
    const lv_font_t *fallback;
    void *user_data;
};
#define LV_FONT_DECLARE(name) extern const lv_font_t name
LV_FONT_DECLARE(lv_font_montserrat_18);
LV_FONT_DECLARE(lv_font_montserrat_20);
LV_FONT_DECLARE(lv_font_montserrat_28);

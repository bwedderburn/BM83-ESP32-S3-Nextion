#pragma once

#include <lvgl.h>

// The built-in Montserrat bitmaps/icons remain primary. Matching supplemental
// Montserrat glyphs cover precomposed European Latin metadata at each UI size.
namespace metadata_fonts {
const lv_font_t *title();
const lv_font_t *artist();
const lv_font_t *album();
}  // namespace metadata_fonts

// Real LVGL 8.3.11 display/label raster test, run by fonts/check_lvgl.py.
#include "metadata_fonts.h"
#include "metadata_text.h"

#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

namespace {
constexpr int WIDTH = 800;
constexpr int HEIGHT = 128;
constexpr int MARGIN = 24;
constexpr int FIELD_WIDTH = 524;  // Production metadata label width.
using Pixels = std::array<uint16_t, WIDTH * HEIGHT>;
Pixels framebuffer;
lv_color_t draw_pixels[WIDTH * HEIGHT];
lv_disp_t *display;
unsigned flush_count;

void flush(lv_disp_drv_t *driver, const lv_area_t *area, lv_color_t *pixels) {
    assert(area->x1 >= 0 && area->y1 >= 0 && area->x2 < WIDTH && area->y2 < HEIGHT);
    for (int y = area->y1; y <= area->y2; ++y) {
        for (int x = area->x1; x <= area->x2; ++x) {
            framebuffer[y * WIDTH + x] = pixels->full;
            ++pixels;
        }
    }
    ++flush_count;
    lv_disp_flush_ready(driver);
}

void initialize() {
    lv_init();
    static lv_disp_draw_buf_t buffer;
    lv_disp_draw_buf_init(&buffer, draw_pixels, nullptr, WIDTH * HEIGHT);
    static lv_disp_drv_t driver;
    lv_disp_drv_init(&driver);
    driver.hor_res = WIDTH;
    driver.ver_res = HEIGHT;
    driver.draw_buf = &buffer;
    driver.flush_cb = flush;
    driver.full_refresh = 1;
    display = lv_disp_drv_register(&driver);
    assert(display);
    lv_disp_set_theme(display, nullptr);
    lv_obj_t *screen = lv_disp_get_scr_act(display);
    lv_obj_remove_style_all(screen);
    lv_obj_clear_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(screen, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
}

// A padded reference lets glyph ink extend beyond nominal font ascent/descent.
// The unpadded label has the same text anchor but clips to one font line. Their
// complete framebuffers must agree, so missing accent rows cannot hide behind
// an equally clipped canonical reference. A final production-size label also
// checks its DOT mode does not insert ellipses for this title.
Pixels render(const lv_font_t *font, const char *text, bool padded,
              int line_height = 0, int anchor_shift = 0, bool production = false) {
    lv_obj_t *screen = lv_disp_get_scr_act(display);
    lv_obj_clean(screen);
    framebuffer.fill(0);
    lv_obj_t *label = lv_label_create(screen);
    assert(label);
    lv_obj_remove_style_all(label);
    lv_obj_clear_flag(label, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_text_font(label, font, 0);
    lv_obj_set_style_text_color(label, lv_color_white(), 0);
    lv_obj_set_style_text_opa(label, LV_OPA_COVER, 0);
    lv_obj_set_style_text_letter_space(label, 0, 0);
    lv_obj_set_style_text_line_space(label, 0, 0);
    const int padding = padded ? MARGIN : 0;
    const int height = line_height ? line_height : font->line_height;
    lv_obj_set_style_pad_all(label, padding, 0);
    lv_obj_set_pos(label, padded ? 0 : MARGIN, (padded ? 0 : MARGIN) + anchor_shift);
    lv_obj_set_size(label, FIELD_WIDTH + 2 * padding, height + 2 * padding);
    lv_label_set_long_mode(label, production ? LV_LABEL_LONG_DOT : LV_LABEL_LONG_CLIP);
    lv_label_set_text(label, text);
    lv_obj_update_layout(screen);
    const unsigned before = flush_count;
    lv_obj_invalidate(screen);
    lv_refr_now(display);
    assert(flush_count > before);
    assert(std::strcmp(lv_label_get_text(label), text) == 0);
    assert(std::count_if(framebuffer.begin(), framebuffer.end(),
                         [](uint16_t color) { return color != 0; }) > 20);
    return framebuffer;
}

void no_placeholder(const lv_font_t *font, const char *text) {
    uint32_t index = 0;
    while (text[index]) {
        const uint32_t code = _lv_txt_encoded_next(text, &index);
        uint32_t next_index = index;
        const uint32_t next = _lv_txt_encoded_next(text, &next_index);
        lv_font_glyph_dsc_t glyph;
        assert(lv_font_get_glyph_dsc(font, &glyph, code, next));
        assert(!glyph.is_placeholder && glyph.resolved_font);
        assert(glyph.box_h + glyph.ofs_y <= font->line_height - font->base_line);
        assert(glyph.ofs_y >= -font->base_line);
        if (glyph.box_w && glyph.box_h) assert(lv_font_get_glyph_bitmap(glyph.resolved_font, code));
    }
}

void export_ppm(const std::string &path, const Pixels &pixels) {
    FILE *file = std::fopen(path.c_str(), "wb");
    assert(file);
    std::fprintf(file, "P6\n%d %d\n255\n", WIDTH, HEIGHT);
    for (uint16_t pixel : pixels) {
        lv_color_t color;
        color.full = pixel;
        lv_color32_t rgb;
        rgb.full = lv_color_to32(color);
        const unsigned char bytes[] = {rgb.ch.red, rgb.ch.green, rgb.ch.blue};
        assert(std::fwrite(bytes, sizeof(bytes), 1, file) == 1);
    }
    assert(std::fclose(file) == 0);
}

void check(const char *name, const lv_font_t *font, const lv_font_t *base,
           int production_height, const char *export_directory) {
    const char *raw[] = {u8"M\u043E\u0308bius Pt I", u8"M\u041E\u0308bius Pt I",
                         u8"Mo\u0308bius Pt I", u8"MO\u0308bius Pt I"};
    const char *canonical[] = {u8"M\u04E7bius Pt I", u8"M\u04E6bius Pt I",
                               u8"M\u00F6bius Pt I", u8"M\u00D6bius Pt I"};
    for (unsigned i = 0; i < 4; ++i) {
        char composed[128];
        assert(metadata_text::compose_diaeresis(raw[i], composed, sizeof(composed)));
        assert(std::strcmp(composed, canonical[i]) == 0);
        // Cyrillic and Latin lookalikes remain different Unicode text even if
        // their font outlines happen to be identical.
        if (i < 2) assert(std::strcmp(composed, canonical[i + 2]) != 0);
        no_placeholder(font, composed);
        const Pixels normalized = render(font, composed, true);
        const Pixels expected = render(font, canonical[i], true);
        assert(normalized == expected);
        assert(normalized != render(font, (i % 2) ? "MObius Pt I" : "Mobius Pt I", true));
        assert(normalized == render(font, composed, false));
        assert(normalized == render(font, composed, false, production_height, 0, true));
        if (i == 0) {
            const Pixels raw_before = render(font, raw[i], true);
            assert(raw_before != normalized);  // Reproduce the user's raw-label defect.
            if (export_directory) {
                const std::string prefix = std::string(export_directory) + "/" + name;
                export_ppm(prefix + "-raw-before.ppm", raw_before);
                export_ppm(prefix + "-normalized-after.ppm", normalized);
            }
        }
    }
    const char *ascii_icons = "CAFO - 04:27 " LV_SYMBOL_VOLUME_MAX;
    char unchanged[128];
    assert(metadata_text::compose_diaeresis(ascii_icons, unchanged, sizeof(unchanged)));
    assert(std::strcmp(unchanged, ascii_icons) == 0);
    no_placeholder(font, unchanged);
    const int shift = font->line_height - font->base_line - (base->line_height - base->base_line);
    assert(render(font, unchanged, true) == render(base, unchanged, true, 0, shift));
    std::printf("LVGL real label pixels passed: %s, height=%d baseline=%d\n",
                name, font->line_height, font->base_line);
}
}  // namespace

int main(int argc, char **argv) {
    assert(argc == 1 || argc == 2);
    initialize();
    const char *directory = argc == 2 ? argv[1] : nullptr;
    check("title", metadata_fonts::title(), &lv_font_montserrat_28, 76, directory);
    check("artist", metadata_fonts::artist(), &lv_font_montserrat_20,
          metadata_fonts::artist()->line_height, directory);
    check("album", metadata_fonts::album(), &lv_font_montserrat_18, 48, directory);
    lv_disp_remove(display);
}

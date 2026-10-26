#include "metadata_text.h"
#include "now_playing.h"

#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

static const char *RAW_TITLE = u8"M\u043E\u0308bius Pt I";
static const char *COMPOSED_TITLE = u8"M\u04E7bius Pt I";

static std::string compose(const char *source) {
    char out[256];
    assert(metadata_text::compose_diaeresis(source, out, sizeof(out)));
    return out;
}

static void captured_title() {
    char source[97];
    std::strcpy(source, RAW_TITLE);
    const std::string original(source);
    assert(compose(source) == COMPOSED_TITLE);
    assert(std::string(source) == original);
    assert(compose(COMPOSED_TITLE) == COMPOSED_TITLE);
    assert(compose(compose(source).c_str()) == COMPOSED_TITLE);
}

static void exact_pairs() {
    assert(compose(u8"O\u0308 o\u0308 \u041E\u0308 \u043E\u0308") ==
           u8"\u00D6 \u00F6 \u04E6 \u04E7");
    assert(compose(u8"\u00D6 \u00F6 \u04E6 \u04E7") == u8"\u00D6 \u00F6 \u04E6 \u04E7");
    assert(compose(u8"o\u0308") != compose(u8"\u043E\u0308"));
    assert(compose(u8"O\u0308") != compose(u8"\u041E\u0308"));
}

static void unchanged() {
    const char *examples[] = {
        "ASCII -- 'quotes' / EP", u8"A\u0308 e\u0308 \u0435\u0308",
        u8"o\u0301 \u043E\u0301 \u0308", u8"Bj\u00F6rk \u4E2D \U0001F3B5",
        u8"\u00F6\u0308 \u04E7\u0308", "line\tbreak\n",
    };
    for (const char *source : examples) assert(compose(source) == source);
}

static void capacity() {
    const char *sources[] = {"", "ASCII", RAW_TITLE, u8"o\u0308\U0001F3B5x",
                             u8"\u043E\u0308\u4E2D", u8"A\u0308"};
    for (const char *source : sources) {
        const std::string expected = compose(source);
        for (size_t size = 0; size <= expected.size() + 3; ++size) {
            std::vector<char> guarded(size + 2, '#');
            char *out = guarded.data() + 1;
            const bool complete = metadata_text::compose_diaeresis(source, out, size);
            assert(guarded.front() == '#' && guarded.back() == '#');
            assert(complete == (size > expected.size()));
            if (!size) continue;
            const size_t length = std::strlen(out);
            assert(length < size);
            assert(now_playing::valid_utf8(reinterpret_cast<const uint8_t *>(out), length));
            assert(expected.compare(0, length, out) == 0);
            if (complete) assert(expected == out);
        }
    }
    char one[1] = {'!'};
    assert(metadata_text::compose_diaeresis("", one, sizeof(one)) && one[0] == 0);
    assert(!metadata_text::compose_diaeresis("a", one, sizeof(one)) && one[0] == 0);
    assert(!metadata_text::compose_diaeresis("a", nullptr, 10));
    assert(!metadata_text::compose_diaeresis(nullptr, one, sizeof(one)) && one[0] == 0);
    // Composition never expands, and also remains safe when explicitly used in-place.
    char in_place[97];
    std::strcpy(in_place, RAW_TITLE);
    assert(metadata_text::compose_diaeresis(in_place, in_place, sizeof(in_place)));
    assert(std::strcmp(in_place, COMPOSED_TITLE) == 0);
}

static void invalid_utf8() {
    const char *invalid[] = {"\x80", "\xc0\xaf", "\xe0\x80\x80", "\xed\xa0\x80",
                              "\xf4\x90\x80\x80", "\xf5\x80\x80\x80", "\xc2",
                              "\xe2\x82", "\xf0\x9f\x8e", "\xe2x"};
    for (const char *tail : invalid) {
        const std::string source = std::string("ok") + tail;
        char out[64];
        assert(!metadata_text::compose_diaeresis(source.c_str(), out, sizeof(out)));
        assert(std::strcmp(out, "ok") == 0);
    }
    char out[8];
    assert(!metadata_text::compose_diaeresis("o\xcc", out, sizeof(out)));
    assert(std::strcmp(out, "o") == 0);
}

static void long_input() {
    const std::string source = std::string(400, 'x') + RAW_TITLE;
    char out[97];
    assert(!metadata_text::compose_diaeresis(source.c_str(), out, sizeof(out)));
    assert(std::string(out) == std::string(96, 'x'));
    assert(source == std::string(400, 'x') + RAW_TITLE);
}

// Compile the actual main.cpp artwork/UI functions with observation stubs.
// This checks their data flow, independently of the renderer's font/pixel tests.
struct lv_font_t {};
struct lv_obj_t { std::string text; int value = 0; bool disabled = false; };
namespace metadata_fonts {
static lv_font_t font;
static const lv_font_t *title() { return &font; }
static const lv_font_t *artist() { return &font; }
static const lv_font_t *album() { return &font; }
}
struct Model {
    now_playing::NowPlayingState state = {};
    bool is_fresh = true;
    bool fresh(uint32_t) const { return is_fresh; }
    bool have_snapshot() const { return true; }
    uint32_t position(uint32_t) const { return state.position_ms; }
};
static Model g_now_playing;
static lv_obj_t labels[10];
static lv_obj_t *g_title_label = &labels[0], *g_artist_label = &labels[1], *g_album_label = &labels[2];
static lv_obj_t *g_playback_label = &labels[3], *g_play_button_label = &labels[4], *g_eq_label = &labels[5];
static lv_obj_t *g_position_label = &labels[6], *g_duration_label = &labels[7], *g_progress_bar = &labels[8];
static bool g_artwork_ready = true;
static uint32_t g_artwork_request = 0;
static std::string artwork_title, artwork_artist, artwork_album, diagnostic[3];
static uint32_t artwork_request(const char *title, const char *artist, const char *album) {
    artwork_title = title; artwork_artist = artist; artwork_album = album;
    return 1;
}
static void clear_artwork(const char *) {}
static void set_label(lv_obj_t *label, const char *text) { label->text = text; }
static const char *eq_name(uint8_t) { return "OFF"; }
static void format_track_time(uint32_t, char *out, size_t size) { std::snprintf(out, size, "--:--"); }
static void log_missing_glyphs(unsigned field, const char *, const char *text, const lv_font_t *) {
    assert(field < 3); diagnostic[field] = text;
}
static const int LV_STATE_DISABLED = 1, LV_ANIM_OFF = 0;
#define LV_SYMBOL_PLAY ">"
#define LV_SYMBOL_PAUSE "||"
static void lv_obj_clear_state(lv_obj_t *obj, int) { obj->disabled = false; }
static void lv_obj_add_state(lv_obj_t *obj, int) { obj->disabled = true; }
static int lv_bar_get_value(lv_obj_t *obj) { return obj->value; }
static void lv_bar_set_value(lv_obj_t *obj, int value, int) { obj->value = value; }
#include "metadata_text_runtime.inc"

static void integration() {
    const char *raw_artist = u8"Artist O\u0308";
    const char *raw_album = u8"Album \u041E\u0308";
    auto &state = g_now_playing.state;
    state.power_on = state.connected = true;
    state.play_status = 1;
    state.duration_ms = 120000;
    state.position_ms = 30000;
    std::strcpy(state.title, RAW_TITLE);
    std::strcpy(state.artist, raw_artist);
    std::strcpy(state.album, raw_album);
    ui_set_now_playing(100);
    assert(g_title_label->text == COMPOSED_TITLE);
    assert(g_artist_label->text == u8"Artist \u00D6");
    assert(g_album_label->text == u8"Album \u04E6");
    assert(diagnostic[0] == g_title_label->text && diagnostic[1] == g_artist_label->text &&
           diagnostic[2] == g_album_label->text);
    assert(artwork_title == RAW_TITLE && artwork_artist == raw_artist && artwork_album == raw_album);
    assert(std::strcmp(state.title, RAW_TITLE) == 0 && std::strcmp(state.artist, raw_artist) == 0 &&
           std::strcmp(state.album, raw_album) == 0);
    assert(g_progress_bar->value == 250);
    g_now_playing.is_fresh = false;
    ui_set_now_playing(4000);
    assert(g_title_label->text == "Audio unit unavailable");
    assert(g_artist_label->text.empty() && g_album_label->text.empty());
    assert(artwork_title.empty() && artwork_artist.empty() && artwork_album.empty());
    assert(std::strcmp(state.title, RAW_TITLE) == 0);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    const std::string scenario = argv[1];
    if (scenario == "captured-title") captured_title();
    else if (scenario == "exact-pairs") exact_pairs();
    else if (scenario == "unchanged") unchanged();
    else if (scenario == "capacity") capacity();
    else if (scenario == "invalid-utf8") invalid_utf8();
    else if (scenario == "long-input") long_input();
    else if (scenario == "integration") integration();
    else return 2;
    return 0;
}

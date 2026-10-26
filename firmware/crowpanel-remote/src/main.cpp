// BM83 wireless remote — CrowPanel ESP32 7" — controls and Now Playing.
//
// Repurposes the solar-monitor wall HMI as a remote controller for the
// BM83-ESP32-S3-Nextion audio unit:
//
//   - Now Playing page with source metadata and display-only progress
//   - compact transport/volume controls shared with the device settings page
//   - buttons emit the SAME token vocabulary the Nextion sends over UART
//     (see NEXTION_SETUP.md): volume uses press/release pairs (BT_VOLUP_P /
//     BT_VOLUP_R, ...) for hold-and-repeat; the rest are single tokens
//   - every token is logged to serial AND transmitted over ESP-NOW to the
//     audio unit as "BMR1:<seq>:<token>" (see espnow_link.h). The audio-unit
//     receiver shares the Nextion dispatch path. A radio ACK confirms
//     delivery to the peer radio, not playback or resulting source volume.
//   - heartbeat line every 5 s so a silent panel is never ambiguous
//   - battery gauge (top right) from the panel's Li-ion cell, and supply
//     detection that picks the sleep policy: on USB the screen only dims
//     (a tap always wakes it); on battery it dims sooner and light-sleeps
//     until BOOT is pressed (see battery.h, display_init.h)
//
// Display/touch/power bring-up comes verbatim from the solar HMI firmware
// (same physical hardware). Optional WiFi artwork shares the radio channel
// with ESP-NOW. The artwork worker owns SD/cache/TLS; LVGL stays in this task.

#include <Arduino.h>
#include <lvgl.h>
#include <stdarg.h>

#include "battery.h"
#include "display_init.h"
#include "espnow_link.h"
#include "now_playing.h"
#include "ble_control.h"
#include "metadata_fonts.h"
#include "artwork.h"
#include "artwork_ca_bundle.h"
#include "network_setup.h"

// ----- logging ---------------------------------------------------------------
// ARDUINO_USB_CDC_ON_BOOT=1 makes `Serial` the native USB CDC and `Serial0`
// UART0 (the CH340 the CrowPanel's USB socket is wired through). Print to
// BOTH so the monitor sees output regardless of which path is live.
static void rlog(const char *fmt, ...) {
    char buf[192];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    Serial.println(buf);
    if (!network_setup_serial_busy()) Serial0.println(buf);
}

// ----- LVGL plumbing (v8 API, same shape as the solar HMI) -------------------
constexpr uint32_t SCREEN_W = 800;
constexpr uint32_t SCREEN_H = 480;
constexpr uint32_t DRAW_BUF_PIXELS = SCREEN_W * SCREEN_H / 15;  // ~50 KB partial buffer

static lv_disp_draw_buf_t draw_buf;
static lv_color_t         disp_draw_buf[DRAW_BUF_PIXELS];
static lv_disp_drv_t      disp_drv;
static lv_indev_drv_t     indev_drv;

// ----- UI state ---------------------------------------------------------------
static lv_obj_t *g_status_label = nullptr;
static uint32_t  g_token_count  = 0;
static now_playing::NowPlayingModel g_now_playing;
static ble_control::Control g_ble_control;
static lv_obj_t *g_ble_button = nullptr;
static lv_obj_t *g_ble_button_label = nullptr;
static lv_obj_t *g_ble_status_label = nullptr;
static lv_obj_t *g_page_title = nullptr;
static lv_obj_t *g_page_button_label = nullptr;
static lv_obj_t *g_now_page = nullptr;
static lv_obj_t *g_settings_page = nullptr;
static lv_obj_t *g_title_label = nullptr;
static lv_obj_t *g_artist_label = nullptr;
static lv_obj_t *g_album_label = nullptr;
static lv_obj_t *g_playback_label = nullptr;
static lv_obj_t *g_position_label = nullptr;
static lv_obj_t *g_duration_label = nullptr;
static lv_obj_t *g_progress_bar = nullptr;
static lv_obj_t *g_play_button_label = nullptr;
static lv_obj_t *g_eq_label = nullptr;
static bool g_show_settings = false;
static bool g_artwork_ready = false;
static uint32_t g_artwork_request = 0;
static lv_obj_t *g_artwork_image = nullptr;
static lv_obj_t *g_artwork_icon = nullptr;
static lv_obj_t *g_artwork_hint = nullptr;
static uint16_t *g_artwork_pixels = nullptr;
static lv_img_dsc_t g_artwork_descriptor = {};
static lv_img_dsc_t g_blank_artwork = {};
static const uint16_t g_blank_pixel = 0;

// ----- battery widget (the solar HMI header icon, scaled for the remote) -----
// [body with fill + charging bolt][tip]  "98%  4.12 V"
constexpr int      BATT_BODY_W = 32;
constexpr int      BATT_BODY_H = 16;
constexpr int      BATT_TIP_W  = 4;
constexpr int      BATT_TIP_H  = 8;
constexpr int      BATT_PAD    = 2;  // gap between the body's border and the fill
constexpr uint32_t COLOR_FG    = 0xE8EAED;
constexpr uint32_t COLOR_OK    = 0x34A853;
constexpr uint32_t COLOR_WARN  = 0xFBBC04;
constexpr uint32_t COLOR_BAD   = 0xEA4335;

static lv_obj_t    *g_batt_fill = nullptr;
static lv_obj_t    *g_batt_bolt = nullptr;
static lv_obj_t    *g_batt_text = nullptr;
static BatteryState g_batt      = {-1.0f, -1, Supply::Unknown, false};

static lv_obj_t *make_plain(lv_obj_t *parent, int w, int h) {
    lv_obj_t *o = lv_obj_create(parent);
    lv_obj_remove_style_all(o);
    lv_obj_set_size(o, w, h);
    lv_obj_clear_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    return o;
}

static void build_battery_widget(lv_obj_t *scr) {
    lv_obj_t *row = make_plain(scr, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(row, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(row, 8, 0);
    lv_obj_align(row, LV_ALIGN_TOP_RIGHT, -24, 22);

    lv_obj_t *icon = make_plain(row, BATT_BODY_W + BATT_TIP_W, BATT_BODY_H);

    lv_obj_t *body = make_plain(icon, BATT_BODY_W, BATT_BODY_H);
    lv_obj_set_style_border_color(body, lv_color_hex(COLOR_FG), 0);
    lv_obj_set_style_border_width(body, 1, 0);
    lv_obj_set_style_radius(body, 3, 0);

    lv_obj_t *tip = make_plain(icon, BATT_TIP_W, BATT_TIP_H);
    lv_obj_set_pos(tip, BATT_BODY_W, (BATT_BODY_H - BATT_TIP_H) / 2);
    lv_obj_set_style_bg_color(tip, lv_color_hex(COLOR_FG), 0);
    lv_obj_set_style_bg_opa(tip, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(tip, 1, 0);

    // Children sit inside the body's 1 px border, hence the -2.
    g_batt_fill = make_plain(body, 0, BATT_BODY_H - 2 * BATT_PAD - 2);
    lv_obj_set_pos(g_batt_fill, BATT_PAD, BATT_PAD);
    lv_obj_set_style_bg_color(g_batt_fill, lv_color_hex(COLOR_OK), 0);
    lv_obj_set_style_bg_opa(g_batt_fill, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(g_batt_fill, 1, 0);

    g_batt_bolt = lv_label_create(body);
    lv_label_set_text(g_batt_bolt, LV_SYMBOL_CHARGE);
    lv_obj_set_style_text_color(g_batt_bolt, lv_color_hex(COLOR_FG), 0);
    lv_obj_set_style_text_font(g_batt_bolt, &lv_font_montserrat_14, 0);
    lv_obj_center(g_batt_bolt);
    lv_obj_add_flag(g_batt_bolt, LV_OBJ_FLAG_HIDDEN);

    g_batt_text = lv_label_create(row);
    lv_label_set_text(g_batt_text, "--%");
    lv_obj_set_style_text_color(g_batt_text, lv_color_hex(COLOR_FG), 0);
    lv_obj_set_style_text_font(g_batt_text, &lv_font_montserrat_14, 0);
}

// Repaint only on a change: percent, bolt, or the voltage at 10 mV.
static void ui_set_battery(const BatteryState &b) {
    static int  last_pct  = -2;
    static bool last_bolt = false;
    static int  last_cv   = -1;
    if (!g_batt_fill || !g_batt_text) return;
    const bool bolt = b.charging && b.percent >= 0;
    const int  cv   = (b.percent >= 0) ? (int)(b.volts * 100.0f + 0.5f) : -1;
    if (b.percent == last_pct && bolt == last_bolt && cv == last_cv) return;
    last_pct  = b.percent;
    last_bolt = bolt;
    last_cv   = cv;

    if (bolt) lv_obj_clear_flag(g_batt_bolt, LV_OBJ_FLAG_HIDDEN);
    else      lv_obj_add_flag(g_batt_bolt, LV_OBJ_FLAG_HIDDEN);
    if (b.percent < 0) {
        lv_obj_set_width(g_batt_fill, 0);
        lv_label_set_text(g_batt_text, "--%");
        return;
    }
    const int inner_w = BATT_BODY_W - 2 * BATT_PAD - 2;
    lv_obj_set_width(g_batt_fill, (inner_w * b.percent) / 100);
    const uint32_t color = (b.percent < 20) ? COLOR_BAD
                         : (b.percent < 50) ? COLOR_WARN
                                            : COLOR_OK;
    lv_obj_set_style_bg_color(g_batt_fill, lv_color_hex(color), 0);
    lv_label_set_text_fmt(g_batt_text, "%d%%  %d.%02d V", b.percent, cv / 100, cv % 100);
}

// Sleep policy follows the detected supply: battery timings only once a
// step has shown the remote is on battery; Unknown runs USB timings.
static void apply_power_mode(Supply s) {
    const bool on_battery = (s == Supply::Battery);
    if (on_battery == screen_is_battery_mode()) return;
    screen_set_battery_mode(on_battery);
    if (on_battery) {
        rlog("[power] on battery: dim after %lus, light sleep after %lus (BOOT wakes)",
             (unsigned long)(SCREEN_DIM_AFTER_MS_BATTERY / 1000),
             (unsigned long)(SCREEN_SLEEP_AFTER_MS_BATTERY / 1000));
    } else {
        rlog("[power] on USB: dim after %lus, light sleep %s",
             (unsigned long)(SCREEN_DIM_AFTER_MS / 1000),
             SCREEN_SLEEP_AFTER_MS > 0 ? "enabled" : "off (a tap always wakes)");
    }
}

static const char *action_name(const char *token) {
    if (strcmp(token, "BT_PREV") == 0) return "Previous track";
    if (strcmp(token, "BT_NEXT") == 0) return "Next track";
    if (strcmp(token, "BT_PLAY") == 0) return "Play/Pause";
    if (strcmp(token, "BT_MUTE") == 0) return "Mute";
    if (strncmp(token, "BT_VOLUP", 8) == 0) return "Volume up";
    if (strncmp(token, "BT_VOLDN", 8) == 0) return "Volume down";
    if (strcmp(token, "BT_EQ") == 0) return "EQ";
    if (strcmp(token, "BT_POWER") == 0) return "Power";
    if (strcmp(token, "BT_PAIR") == 0) return "Pair";
    if (strcmp(token, "BT_EBIND") == 0) return "Erase BLE bonds";
    if (strcmp(token, "NET_RETRY") == 0) return "Retry network";
    if (strcmp(token, "BLE_PAUSE") == 0) return "Pause volume remote";
    if (strcmp(token, "BLE_ENABLE") == 0) return "Enable volume remote";
    return "Control";
}

static bool note_token(const char *token, uint32_t *sequence = nullptr, bool *attempted = nullptr) {
    g_token_count++;
    const bool sent = espnow_send_token(token, sequence);
    if (attempted) *attempted = sent;
    // Sends are synchronous with bounded retries, so this is THIS token's
    // delivery status (ok = the unit's radio ACKed one of the attempts).
    rlog("[TOKEN] %s (#%lu) | link %s", token, (unsigned long)g_token_count,
         espnow_link_status_str());
    const char *status = espnow_link_status_str();
    const bool delivered = strcmp(status, "ok") == 0;
    const char *message = delivered ? "sent"
                        : strcmp(status, "off") == 0
                            ? "remote wireless unavailable; restart remote"
                            : "no response; check the audio unit";
    if (g_status_label) {
        lv_label_set_text_fmt(g_status_label,
                              "%s - %s", action_name(token),
                              message);
        lv_obj_set_style_text_color(g_status_label,
                                    lv_color_hex(delivered ? 0x9AAAB8 : COLOR_WARN), 0);
    }
    return delivered;
}

// Single-shot buttons: one token on click.
static void cb_click(lv_event_t *e) {
    note_token(static_cast<const char *>(lv_event_get_user_data(e)));
}

// A lost press must release too, including a finger dragged off a button.
static void cb_press_release(lv_event_t *e) {
    const char *base = static_cast<const char *>(lv_event_get_user_data(e));
    char token[32];
    if (lv_event_get_code(e) == LV_EVENT_PRESSED) {
        snprintf(token, sizeof(token), "%s_P", base);
        note_token(token);
    } else if (lv_event_get_code(e) == LV_EVENT_RELEASED ||
               lv_event_get_code(e) == LV_EVENT_PRESS_LOST) {
        snprintf(token, sizeof(token), "%s_R", base);
        note_token(token);
    }
}

static lv_obj_t *make_label(lv_obj_t *parent, const char *text, int x, int y,
                            const lv_font_t *font, uint32_t color) {
    lv_obj_t *label = lv_label_create(parent);
    lv_label_set_text(label, text);
    lv_obj_set_pos(label, x, y);
    lv_obj_set_style_text_font(label, font, 0);
    lv_obj_set_style_text_color(label, lv_color_hex(color), 0);
    return label;
}

static lv_obj_t *make_button(lv_obj_t *parent, const char *text,
                             int x, int y, int w, int h, bool primary = false) {
    lv_obj_t *btn = lv_btn_create(parent);
    lv_obj_set_pos(btn, x, y);
    lv_obj_set_size(btn, w, h);
    lv_obj_set_style_bg_color(btn, lv_color_hex(primary ? 0x267BE8 : 0x203246), 0);
    lv_obj_set_style_bg_color(btn, lv_color_hex(primary ? 0x4698FF : 0x304A65), LV_STATE_PRESSED);
    lv_obj_set_style_bg_grad_dir(btn, LV_GRAD_DIR_NONE, 0);
    lv_obj_set_style_radius(btn, 10, 0);
    lv_obj_set_style_border_width(btn, 1, 0);
    lv_obj_set_style_border_color(btn, lv_color_hex(primary ? 0x4698FF : 0x344A60), 0);
    lv_obj_set_style_shadow_width(btn, 0, LV_STATE_DEFAULT);
    lv_obj_set_style_shadow_width(btn, 0, LV_STATE_PRESSED);
    lv_obj_set_style_transform_width(btn, 0, LV_STATE_PRESSED);
    lv_obj_set_style_transform_height(btn, 0, LV_STATE_PRESSED);
    lv_obj_set_style_pad_all(btn, 8, 0);
    lv_obj_t *label = lv_label_create(btn);
    lv_label_set_text(label, text);
    lv_obj_set_style_text_font(label, &lv_font_montserrat_18, 0);
    lv_obj_set_style_text_color(label, lv_color_hex(COLOR_FG), 0);
    lv_obj_center(label);
    return btn;
}

static void set_label(lv_obj_t *label, const char *text) {
    if (strcmp(lv_label_get_text(label), text) != 0) lv_label_set_text(label, text);
}

static const char *ble_error_text(uint8_t error) {
    switch (error) {
        case 1: return "BLE unavailable";
        case 2: return "Could not stop advertising";
        case 3: return "Disconnect failed";
        case 4: return "Disconnect timed out";
        case 5: return "Could not stop BLE workflow";
        case 6: return "BLE state unavailable";
        case 7: return "Bond operation was busy";
        default: return "BLE operation failed";
    }
}

static void ui_set_ble(uint32_t now) {
    if (!g_ble_button || !g_ble_status_label) return;
    g_ble_control.tick(now);
    const bool fresh = g_ble_control.status.fresh(now);
    const auto &state = g_ble_control.status.state;
    const char *text = "Volume remote unavailable";
    if (fresh) {
        if (state.mode == ble_status::MODE_ERROR) text = ble_error_text(state.error);
        else if (!(state.flags & ble_status::FLAG_READY)) text = "Volume remote unavailable";
        else if (state.mode == ble_status::MODE_PAUSED) text = "Paused (bonds kept)";
        else if (state.mode == ble_status::MODE_PAUSING) text = "Pausing volume remote...";
        else if (state.flags & ble_status::FLAG_CONNECTED) text = "Volume remote connected";
        else if (state.flags & ble_status::FLAG_ADVERTISING) text = "Available for connection";
        else text = "Enabling volume remote...";
    }
    set_label(g_ble_button_label, fresh && !(state.flags & ble_status::FLAG_INTENT)
              ? "Enable volume remote" : "Pause volume remote");
    if (g_ble_control.can_request(now)) lv_obj_clear_state(g_ble_button, LV_STATE_DISABLED);
    else lv_obj_add_state(g_ble_button, LV_STATE_DISABLED);
    char message[128];
    const char *detail = g_ble_control.result == ble_control::WAITING ? "Waiting for confirmation"
                       : g_ble_control.result == ble_control::TIMED_OUT ? "Request unconfirmed"
                       : g_ble_control.result == ble_control::RESTARTED ? "Controller restarted"
                       : "";
    snprintf(message, sizeof(message), "%s%s%s", text, detail[0] ? "\n" : "", detail);
    set_label(g_ble_status_label, message);
    lv_obj_set_style_text_color(g_ble_status_label,
        lv_color_hex(!fresh || state.mode == ble_status::MODE_ERROR ? COLOR_WARN : 0x9AAAB8), 0);
}

static void cb_ble_control(lv_event_t *) {
    const uint32_t now = millis();
    if (!g_ble_control.can_request(now)) return;
    const bool pause = (g_ble_control.status.state.flags & ble_status::FLAG_INTENT) != 0;
    uint32_t sequence = 0;
    bool attempted = false;
    note_token(pause ? "BLE_PAUSE" : "BLE_ENABLE", &sequence, &attempted);
    // A no-ACK attempt can still reach the controller. Wait for the matching
    // observed state either way, rather than issuing a second command here.
    if (attempted) g_ble_control.begin(pause, sequence, now);
    ui_set_ble(millis());
}

static void cb_network_settings(lv_event_t *) {
    network_setup_show(lv_scr_act());
}

static void retry_network_both() {
    // This callback runs only after the user selects Retry both in setup.
    note_token("NET_RETRY");
}

static void clear_artwork(const char *message) {
    if (!g_artwork_image) return;
    lv_obj_add_flag(g_artwork_image, LV_OBJ_FLAG_HIDDEN);
    // Switch the widget away from the owned buffer and evict any decoder/cache
    // references before releasing it. Both descriptors have static lifetimes.
    lv_img_set_src(g_artwork_image, &g_blank_artwork);
    lv_img_cache_invalidate_src(&g_artwork_descriptor);
    uint16_t *previous = g_artwork_pixels;
    g_artwork_pixels = nullptr;
    g_artwork_descriptor = {};
    artwork_release(previous);
    set_label(g_artwork_hint, message);
    lv_obj_clear_flag(g_artwork_icon, LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(g_artwork_hint, LV_OBJ_FLAG_HIDDEN);
}

static void request_artwork(bool eligible) {
    if (!g_artwork_ready) return;
    const auto &state = g_now_playing.state;
    eligible = eligible && state.artist[0] && (state.album[0] || state.title[0]);
    const uint32_t id = artwork_request(eligible ? state.title : "",
                                         eligible ? state.artist : "",
                                         eligible ? state.album : "");
    if (id != g_artwork_request) {
        g_artwork_request = id;
        clear_artwork(eligible ? "Finding artwork..." : "Artwork unavailable");
    }
}

static const char *artwork_status_name(ArtworkStatus status) {
    switch (status) {
        case ArtworkStatus::Ready: return "ready";
        case ArtworkStatus::NoMatch: return "no-match";
        case ArtworkStatus::Offline: return "offline";
        case ArtworkStatus::ClockUnavailable: return "waiting-time";
        case ArtworkStatus::TrustUnavailable: return "trust-unavailable";
        case ArtworkStatus::InvalidImage: return "invalid-image";
        case ArtworkStatus::StorageError: return "storage-error";
        default: return "network-error";
    }
}

static void poll_artwork() {
    ArtworkResult result;
    if (!g_artwork_ready || !artwork_poll(result)) return;
    if (result.request_id != g_artwork_request) {
        artwork_release(result.rgb565);
        return;
    }
    static uint32_t last_logged_id = 0;
    static ArtworkStatus last_logged_status = ArtworkStatus::NoMatch;
    if (result.request_id != last_logged_id || result.status != last_logged_status) {
        rlog("[artwork] request=%lu status=%s cache=%u sd=%u size=%ux%u",
             (unsigned long)result.request_id, artwork_status_name(result.status),
             (unsigned)result.from_cache, (unsigned)result.sd_ready,
             (unsigned)result.width, (unsigned)result.height);
        last_logged_id = result.request_id;
        last_logged_status = result.status;
    }
    if (result.status != ArtworkStatus::Ready || !result.rgb565 || !result.width || !result.height) {
        clear_artwork(result.status == ArtworkStatus::Offline ? "Artwork offline" :
                      result.status == ArtworkStatus::ClockUnavailable ? "Waiting for artwork..." :
                      result.status == ArtworkStatus::NetworkError ? "Retrying artwork..." :
                      "Artwork unavailable");
        artwork_release(result.rgb565);
        return;
    }
    clear_artwork("Artwork unavailable");
    g_artwork_pixels = result.rgb565;
    g_artwork_descriptor.header.always_zero = 0;
    g_artwork_descriptor.header.cf = LV_IMG_CF_TRUE_COLOR;
    g_artwork_descriptor.header.w = result.width;
    g_artwork_descriptor.header.h = result.height;
    g_artwork_descriptor.data_size = static_cast<uint32_t>(result.width) * result.height * 2;
    g_artwork_descriptor.data = reinterpret_cast<const uint8_t *>(g_artwork_pixels);
    lv_img_set_src(g_artwork_image, &g_artwork_descriptor);
    const uint16_t zoom_x = 200U * 256U / result.width;
    const uint16_t zoom_y = 200U * 256U / result.height;
    lv_img_set_pivot(g_artwork_image, result.width / 2, result.height / 2);
    lv_img_set_zoom(g_artwork_image, zoom_x < zoom_y ? zoom_x : zoom_y);
    lv_obj_center(g_artwork_image);
    lv_obj_add_flag(g_artwork_icon, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(g_artwork_hint, LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(g_artwork_image, LV_OBJ_FLAG_HIDDEN);
}

// Raw BM83 EQ modes, matching BM83.EQ_L. Do not infer EQ from button presses:
// a delivered command does not prove that the module applied the setting.
static const char *eq_name(uint8_t mode) {
    switch (mode) {
        case 0: return "OFF";
        case 1: return "SOFT";
        case 2: return "BASS";
        case 3: return "TREBLE";
        case 4: return "CLASSICAL";
        case 5: return "ROCK";
        case 6: return "JAZZ";
        case 7: return "POP";
        case 8: return "DANCE";
        case 9: return "RNB";
        case 11: return "USER";
        default: return "--";
    }
}

// The model validates UTF-8 before committing a snapshot. Decode only that
// bounded text here, once per text change, to identify any missing font glyphs.
static void log_missing_glyphs(unsigned field, const char *name, const char *text,
                               const lv_font_t *font) {
    static char previous[3][now_playing::MAX_TEXT_BYTES + 1] = {};
    static bool initialized[3] = {};
    if (field >= 3 || (initialized[field] && strcmp(previous[field], text) == 0)) return;
    strncpy(previous[field], text, now_playing::MAX_TEXT_BYTES);
    previous[field][now_playing::MAX_TEXT_BYTES] = '\0';
    initialized[field] = true;

    char missing[120] = {};
    size_t used = 0;
    const auto *bytes = reinterpret_cast<const uint8_t *>(text);
    for (size_t i = 0; bytes[i] != 0;) {
        const uint8_t lead = bytes[i++];
        uint32_t code = lead;
        unsigned tail = 0;
        if ((lead & 0xE0) == 0xC0) { code = lead & 0x1F; tail = 1; }
        else if ((lead & 0xF0) == 0xE0) { code = lead & 0x0F; tail = 2; }
        else if ((lead & 0xF8) == 0xF0) { code = lead & 7; tail = 3; }
        while (tail--) code = (code << 6) | (bytes[i++] & 0x3F);
        lv_font_glyph_dsc_t glyph;
        if (lv_font_get_glyph_dsc(font, &glyph, code, 0) && !glyph.is_placeholder) continue;
        // Leave room for the largest Unicode codepoint and a final terminator.
        if (sizeof(missing) - used < 11) break;
        const int written = snprintf(missing + used, sizeof(missing) - used,
                                     "%sU+%04lX", used ? " " : "", (unsigned long)code);
        if (written > 0) used += static_cast<size_t>(written);
    }
    if (used) rlog("[text] %s missing glyphs: %s", name, missing);
}

static void cb_page(lv_event_t *) {
    g_show_settings = !g_show_settings;
    if (g_show_settings) {
        lv_obj_add_flag(g_now_page, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(g_settings_page, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(g_settings_page, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(g_now_page, LV_OBJ_FLAG_HIDDEN);
    }
    set_label(g_page_title, g_show_settings ? "Settings" : "Now Playing");
    set_label(g_page_button_label, g_show_settings ? "Now Playing" : "Settings");
}

static void format_track_time(uint32_t ms, char *out, size_t size) {
    if (ms == now_playing::UNKNOWN) {
        snprintf(out, size, "--:--");
        return;
    }
    const uint32_t seconds = ms / 1000;
    if (seconds >= 3600) {
        snprintf(out, size, "%lu:%02lu:%02lu", (unsigned long)(seconds / 3600),
                 (unsigned long)((seconds / 60) % 60), (unsigned long)(seconds % 60));
    } else {
        snprintf(out, size, "%lu:%02lu", (unsigned long)(seconds / 60),
                 (unsigned long)(seconds % 60));
    }
}

// Display only: the unit has no implemented arbitrary-position seek command.
static void ui_set_now_playing(uint32_t now) {
    const auto &state = g_now_playing.state;
    const bool fresh = g_now_playing.fresh(now);
    const bool bluetooth = fresh && state.power_on && state.connected && !state.aux;
    request_artwork(bluetooth);
    const char *title;
    const char *artist = "";
    const char *album = "";
    const char *playback = "";
    const char *play_button = LV_SYMBOL_PLAY "  Play/Pause";
    if (!fresh) {
        title = g_now_playing.have_snapshot() ? "Audio unit unavailable" : "Waiting for audio unit";
        playback = "Waiting for current playback information";
    } else if (!state.power_on) {
        title = "Audio unit off";
    } else if (state.aux) {
        title = "AUX input";
        playback = "Track information unavailable for AUX";
    } else if (!state.connected) {
        title = "Bluetooth disconnected";
    } else {
        title = state.title[0] ? state.title : "No track information";
        artist = state.artist;
        album = state.album;
        switch (state.play_status) {
            case 0x00: playback = "Stopped"; break;
            case 0x01:
                playback = "Playing";
                play_button = LV_SYMBOL_PAUSE "  Pause";
                break;
            case 0x02:
                playback = "Paused";
                play_button = LV_SYMBOL_PLAY "  Play";
                break;
            case 0x03:
            case 0x04:
                playback = "Seeking";
                play_button = LV_SYMBOL_PAUSE "  Pause";
                break;
            default: playback = "Playback status unavailable"; break;
        }
    }
    set_label(g_title_label, title);
    set_label(g_artist_label, artist);
    set_label(g_album_label, album);
    set_label(g_playback_label, playback);
    set_label(g_play_button_label, play_button);
    char eq_text[24];
    snprintf(eq_text, sizeof(eq_text), "EQ: %s", fresh && state.power_on ? eq_name(state.eq_index) : "--");
    set_label(g_eq_label, eq_text);
    if (bluetooth) {
        log_missing_glyphs(0, "title", state.title, metadata_fonts::title());
        log_missing_glyphs(1, "artist", state.artist, metadata_fonts::artist());
        log_missing_glyphs(2, "album", state.album, metadata_fonts::album());
    }

    const uint32_t position = bluetooth ? g_now_playing.position(now) : now_playing::UNKNOWN;
    const uint32_t duration = bluetooth ? state.duration_ms : now_playing::UNKNOWN;
    char time_text[20];
    format_track_time(position, time_text, sizeof(time_text));
    set_label(g_position_label, time_text);
    format_track_time(duration, time_text, sizeof(time_text));
    set_label(g_duration_label, time_text);
    const bool progress_known = position != now_playing::UNKNOWN &&
                                duration != now_playing::UNKNOWN && duration > 0;
    int32_t progress = 0;
    if (progress_known) {
        const uint32_t bounded_position = position > duration ? duration : position;
        progress = (int32_t)((uint64_t)bounded_position * 1000 / duration);
        lv_obj_clear_state(g_progress_bar, LV_STATE_DISABLED);
    } else {
        lv_obj_add_state(g_progress_bar, LV_STATE_DISABLED);
    }
    if (lv_bar_get_value(g_progress_bar) != progress) {
        lv_bar_set_value(g_progress_bar, progress, LV_ANIM_OFF);
    }
}

static void build_transport_controls(lv_obj_t *scr) {
    lv_obj_add_event_cb(make_button(scr, LV_SYMBOL_PREV "  Prev", 24, 392, 120, 52),
                        cb_click, LV_EVENT_CLICKED, (void *)"BT_PREV");
    lv_obj_t *play_button = make_button(scr, LV_SYMBOL_PLAY "  Play/Pause",
                                        156, 392, 168, 52, true);
    g_play_button_label = lv_obj_get_child(play_button, 0);
    lv_obj_add_event_cb(play_button, cb_click, LV_EVENT_CLICKED, (void *)"BT_PLAY");
    lv_obj_add_event_cb(make_button(scr, LV_SYMBOL_NEXT "  Next", 336, 392, 120, 52),
                        cb_click, LV_EVENT_CLICKED, (void *)"BT_NEXT");
    // Mute is a one-shot media command. The source does not report its mute
    // state, so the button must not latch a local muted/unmuted indication.
    lv_obj_add_event_cb(make_button(scr, LV_SYMBOL_MUTE "  Mute", 468, 392, 88, 52),
                        cb_click, LV_EVENT_CLICKED, (void *)"BT_MUTE");
    lv_obj_t *vdn = make_button(scr, "Vol -", 568, 392, 96, 52);
    lv_obj_add_event_cb(vdn, cb_press_release, LV_EVENT_PRESSED, (void *)"BT_VOLDN");
    lv_obj_add_event_cb(vdn, cb_press_release, LV_EVENT_RELEASED, (void *)"BT_VOLDN");
    lv_obj_add_event_cb(vdn, cb_press_release, LV_EVENT_PRESS_LOST, (void *)"BT_VOLDN");
    lv_obj_t *vup = make_button(scr, "Vol +", 676, 392, 100, 52);
    lv_obj_add_event_cb(vup, cb_press_release, LV_EVENT_PRESSED, (void *)"BT_VOLUP");
    lv_obj_add_event_cb(vup, cb_press_release, LV_EVENT_RELEASED, (void *)"BT_VOLUP");
    lv_obj_add_event_cb(vup, cb_press_release, LV_EVENT_PRESS_LOST, (void *)"BT_VOLUP");
}

static void build_ui() {
    lv_obj_t *scr = lv_scr_act();
    lv_obj_set_style_bg_color(scr, lv_color_hex(0x101418), 0);
    lv_obj_clear_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    g_page_title = make_label(scr, "Now Playing", 24, 22,
                              &lv_font_montserrat_20, COLOR_FG);
    lv_obj_t *page_button = make_button(scr, "Settings", 484, 12, 128, 44);
    g_page_button_label = lv_obj_get_child(page_button, 0);
    lv_obj_add_event_cb(page_button, cb_page, LV_EVENT_CLICKED, nullptr);
    build_battery_widget(scr);
    g_eq_label = make_label(scr, "EQ: --", 640, 48, &lv_font_montserrat_12, 0x9AAAB8);
    lv_obj_set_width(g_eq_label, 136);
    lv_obj_set_style_text_align(g_eq_label, LV_TEXT_ALIGN_RIGHT, 0);
    lv_obj_t *divider = make_plain(scr, 752, 1);
    lv_obj_set_pos(divider, 24, 72);
    lv_obj_set_style_bg_color(divider, lv_color_hex(0x293846), 0);
    lv_obj_set_style_bg_opa(divider, LV_OPA_COVER, 0);

    // Shared screen keeps battery, transport and wake handling live on both pages.
    g_now_page = make_plain(scr, 752, 302);
    lv_obj_set_pos(g_now_page, 24, 88);
    g_settings_page = make_plain(scr, 752, 302);
    lv_obj_set_pos(g_settings_page, 24, 88);
    lv_obj_add_flag(g_settings_page, LV_OBJ_FLAG_HIDDEN);

    lv_obj_t *art = make_plain(g_now_page, 200, 200);
    lv_obj_set_pos(art, 0, 4);
    lv_obj_set_style_bg_color(art, lv_color_hex(0x203246), 0);
    lv_obj_set_style_bg_opa(art, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(art, lv_color_hex(0x344A60), 0);
    lv_obj_set_style_border_width(art, 1, 0);
    lv_obj_set_style_radius(art, 12, 0);
    g_artwork_icon = make_label(art, LV_SYMBOL_AUDIO, 0, 0,
                                     &lv_font_montserrat_36, 0x9AAAB8);
    lv_obj_align(g_artwork_icon, LV_ALIGN_CENTER, 0, -16);
    g_artwork_hint = make_label(art, "Artwork unavailable", 0, 0,
                                   &lv_font_montserrat_12, 0x9AAAB8);
    lv_obj_align(g_artwork_hint, LV_ALIGN_CENTER, 0, 28);
    g_blank_artwork.header.always_zero = 0;
    g_blank_artwork.header.cf = LV_IMG_CF_TRUE_COLOR;
    g_blank_artwork.header.w = g_blank_artwork.header.h = 1;
    g_blank_artwork.data_size = sizeof(g_blank_pixel);
    g_blank_artwork.data = reinterpret_cast<const uint8_t *>(&g_blank_pixel);
    g_artwork_image = lv_img_create(art);
    lv_img_set_src(g_artwork_image, &g_blank_artwork);
    lv_obj_add_flag(g_artwork_image, LV_OBJ_FLAG_HIDDEN);

    g_title_label = make_label(g_now_page, "Waiting for audio unit", 228, 8,
                               metadata_fonts::title(), COLOR_FG);
    lv_obj_set_size(g_title_label, 524, 76);
    lv_label_set_long_mode(g_title_label, LV_LABEL_LONG_DOT);
    g_artist_label = make_label(g_now_page, "", 228, 100,
                                metadata_fonts::artist(), 0xBAC7D3);
    lv_obj_set_width(g_artist_label, 524);
    lv_label_set_long_mode(g_artist_label, LV_LABEL_LONG_DOT);
    g_album_label = make_label(g_now_page, "", 228, 140,
                               metadata_fonts::album(), 0x9AAAB8);
    lv_obj_set_size(g_album_label, 524, 48);
    lv_label_set_long_mode(g_album_label, LV_LABEL_LONG_DOT);
    g_playback_label = make_label(g_now_page, "Waiting for current playback information",
                                  228, 192, &lv_font_montserrat_14, 0x9AAAB8);
    lv_obj_set_width(g_playback_label, 524);
    lv_label_set_long_mode(g_playback_label, LV_LABEL_LONG_DOT);

    g_progress_bar = lv_bar_create(g_now_page);
    lv_obj_set_pos(g_progress_bar, 0, 240);
    lv_obj_set_size(g_progress_bar, 752, 10);
    lv_bar_set_range(g_progress_bar, 0, 1000);
    lv_bar_set_value(g_progress_bar, 0, LV_ANIM_OFF);
    lv_obj_clear_flag(g_progress_bar, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_bg_color(g_progress_bar, lv_color_hex(0x415468), LV_PART_MAIN);
    lv_obj_set_style_bg_color(g_progress_bar, lv_color_hex(0x267BE8), LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(g_progress_bar, lv_color_hex(0x415468),
                              LV_PART_INDICATOR | LV_STATE_DISABLED);
    g_position_label = make_label(g_now_page, "--:--", 0, 258,
                                  &lv_font_montserrat_16, 0xBAC7D3);
    g_duration_label = make_label(g_now_page, "--:--", 652, 258,
                                  &lv_font_montserrat_16, 0xBAC7D3);
    lv_obj_set_width(g_duration_label, 100);
    lv_obj_set_style_text_align(g_duration_label, LV_TEXT_ALIGN_RIGHT, 0);

    make_label(g_settings_page, "Device controls", 0, 8,
                &lv_font_montserrat_18, 0xBAC7D3);
    lv_obj_add_event_cb(make_button(g_settings_page, LV_SYMBOL_POWER "  Power",
                                    0, 56, 240, 64),
                        cb_click, LV_EVENT_CLICKED, (void *)"BT_POWER");
    lv_obj_add_event_cb(make_button(g_settings_page, LV_SYMBOL_BLUETOOTH "  Pair",
                                    256, 56, 240, 64),
                        cb_click, LV_EVENT_CLICKED, (void *)"BT_PAIR");
    lv_obj_add_event_cb(make_button(g_settings_page, LV_SYMBOL_SETTINGS "  EQ",
                                    0, 140, 240, 64),
                        cb_click, LV_EVENT_CLICKED, (void *)"BT_EQ");
    lv_obj_add_event_cb(make_button(g_settings_page, "Erase BLE bonds",
                                    256, 140, 240, 64),
                        cb_click, LV_EVENT_CLICKED, (void *)"BT_EBIND");
    lv_obj_add_event_cb(make_button(g_settings_page, "Wi-Fi / Artwork",
                                    512, 56, 240, 64),
                        cb_network_settings, LV_EVENT_CLICKED, nullptr);
    lv_obj_t *artwork_help = make_label(g_settings_page,
                                       "Connect for automatic artwork. Saved covers work offline.",
                                       512, 140, &lv_font_montserrat_14, 0x9AAAB8);
    lv_obj_set_width(artwork_help, 240);
    lv_label_set_long_mode(artwork_help, LV_LABEL_LONG_WRAP);
    g_ble_button = make_button(g_settings_page, "Pause volume remote", 0, 218, 312, 48);
    g_ble_button_label = lv_obj_get_child(g_ble_button, 0);
    lv_obj_add_event_cb(g_ble_button, cb_ble_control, LV_EVENT_CLICKED, nullptr);
    g_ble_status_label = make_label(g_settings_page, "Volume remote unavailable",
                                    328, 220, &lv_font_montserrat_14, 0x9AAAB8);
    lv_obj_set_width(g_ble_status_label, 424);
    lv_label_set_long_mode(g_ble_status_label, LV_LABEL_LONG_WRAP);
    make_label(g_settings_page, "Bonds stay saved. Enable allows a saved host to reconnect.",
                0, 282, &lv_font_montserrat_14, 0x9AAAB8);

    build_transport_controls(scr);

    g_status_label = make_label(scr, "Ready", 24, 456,
                                &lv_font_montserrat_12, 0x9AAAB8);
    lv_obj_set_width(g_status_label, 752);
    lv_label_set_long_mode(g_status_label, LV_LABEL_LONG_DOT);
    ui_set_now_playing(millis());
    ui_set_ble(millis());
}

// ----- Arduino entry points ---------------------------------------------------
void setup() {
    Serial.begin(115200);
    Serial0.begin(115200);
    delay(200);
    rlog("");
    rlog("[remote] BM83 Remote booting (built %s %s)", __DATE__, __TIME__);

    display_init();
    rlog("[remote] display_init ok");

    lv_init();
    lv_disp_draw_buf_init(&draw_buf, disp_draw_buf, NULL, DRAW_BUF_PIXELS);

    lv_disp_drv_init(&disp_drv);
    disp_drv.hor_res  = SCREEN_W;
    disp_drv.ver_res  = SCREEN_H;
    disp_drv.flush_cb = display_flush;
    disp_drv.draw_buf = &draw_buf;
    lv_disp_drv_register(&disp_drv);

    touch_init();
    lv_indev_drv_init(&indev_drv);
    indev_drv.type    = LV_INDEV_TYPE_POINTER;
    indev_drv.read_cb = touch_read;
    lv_indev_drv_register(&indev_drv);

    // Start on USB timings: battery timings need a plug/unplug step as
    // evidence (battery.cpp), because a wrongly "on battery" remote would
    // light-sleep behind the BOOT button.
    screen_set_battery_mode(false);
    rlog("[power] USB timings until a plug/unplug step shows the supply "
         "(dim after %lus, light sleep %s)",
         (unsigned long)(SCREEN_DIM_AFTER_MS / 1000),
         SCREEN_SLEEP_AFTER_MS > 0 ? "enabled" : "off");

    // Bring the ESP-NOW link up before the UI so the first tap
    // can already transmit. Init failure is logged and non-fatal — the
    // panel keeps working as a serial-only remote.
    espnow_link_init(rlog);
    network_setup_set_retry_callback(retry_network_both);
    network_setup_set_export_hooks(artwork_prepare_sleep, artwork_resume);
    network_setup_begin();
    ArtworkConfig artwork_config;
    artwork_config.ca_bundle = artwork_trust::kMozillaCaBundle;
    artwork_config.archive_ca_pem = artwork_trust::kArchiveRootG2Pem;
    g_artwork_ready = artwork_begin(artwork_config);
    if (!g_artwork_ready) rlog("[artwork] worker unavailable; controls remain active");

    // Battery gauge after WiFi is up: the divider ratio was calibrated with
    // the radio running. On the bench a boot read taken before WiFi started
    // came out ~5% above every later reading (2026-10-02).
    battery_init(rlog);

    build_ui();
    rlog("[remote] UI built; Now Playing, progress and settings ready");
}

// Backlight on/off is the panel's biggest load step: report every change to
// the battery module before its next sample, so the step is not read as a
// plug or unplug.
static void report_backlight_change() {
    static bool was_dimmed = false;
    if (screen_is_dimmed() == was_dimmed) return;
    was_dimmed = !was_dimmed;
    battery_note_load_change(!was_dimmed);  // restored = heavier load
}

static uint32_t g_last_batt_poll = 0;

static void poll_battery() {  // the battery module assumes ~1 Hz
    g_last_batt_poll = millis();
    g_batt = battery_poll();
    ui_set_battery(g_batt);
    apply_power_mode(g_batt.supply);
}

void loop() {
    static uint32_t last_heartbeat = 0;
    static bool preparing_sleep = false;
    static bool network_prepared = false;
    static bool sleep_retry_pending = false;
    static uint32_t sleep_failed_at = 0;

    lv_timer_handler();  // a tap may wake the dimmed screen here
    report_backlight_change();
    const bool sleep_due = screen_idle_tick(SCREEN_DIM_AFTER_MS);  // may dim
    report_backlight_change();
    if (!sleep_due && preparing_sleep) {
        if (network_prepared) network_setup_resume_after_sleep();
        network_prepared = false;
        // A USB credential export may own a separate worker pause now.
        if (!network_setup_serial_busy()) artwork_resume();
        preparing_sleep = false;
    }
    if (sleep_due) {
        // The current timings say light sleep. USB may have been plugged in
        // since the last 1 Hz sample, and a USB-powered remote must never
        // end up asleep behind BOOT: sample again, re-apply the supply, and
        // ask again under the refreshed timings before committing. Asking
        // again (rather than checking battery mode) also honours a positive
        // SCREEN_SLEEP_AFTER_MS override on USB instead of re-sampling the
        // battery every loop (PR #157 review).
        poll_battery();
        if (screen_idle_tick(SCREEN_DIM_AFTER_MS)) {
            const bool retry_due = !sleep_retry_pending ||
                                   static_cast<uint32_t>(millis() - sleep_failed_at) >= 30000;
            if (!network_setup_serial_busy() && retry_due) {
                preparing_sleep = true;
                // A worker may be in SD/TLS I/O. Keep the UI responsive while
                // cancellation finishes; never sleep through an active write.
                if (artwork_prepare_sleep() && network_setup_prepare_sleep()) {
                    network_prepared = true;
                    if (espnow_link_suspend()) {
                        screen_light_sleep();       // normal wake uses BOOT
                        espnow_link_init(rlog);
                        g_now_playing.reset();
                        g_ble_control.reset();
                        network_setup_resume_after_sleep();
                        network_prepared = false;
                        artwork_resume();
                        preparing_sleep = false;
                        sleep_retry_pending = false;
                        report_backlight_change();
                        rlog("[power] screen resumed; refreshing playback state");
                        ui_set_now_playing(millis());
                        ui_set_ble(millis());
                    } else {
                        // A failed radio stop must restore controls and avoid
                        // retrying every UI tick while the idle timer is due.
                        espnow_link_init(rlog);
                        g_now_playing.reset();
                        g_ble_control.reset();
                        network_setup_resume_after_sleep();
                        network_prepared = false;
                        if (!network_setup_serial_busy()) artwork_resume();
                        preparing_sleep = false;
                        sleep_retry_pending = true;
                        sleep_failed_at = millis();
                        rlog("[power] sleep deferred; radio stop failed");
                        ui_set_now_playing(millis());
                        ui_set_ble(millis());
                    }
                }
            }
        } else if (preparing_sleep) {
            if (network_prepared) network_setup_resume_after_sleep();
            network_prepared = false;
            if (!network_setup_serial_busy()) artwork_resume();
            preparing_sleep = false;
        }
    }

    uint8_t rx_frame[ESPNOW_FRAME_MAX];
    size_t rx_len;
    bool snapshot_changed = false;
    bool ble_changed = false;
    while ((rx_len = espnow_link_poll(rx_frame, sizeof(rx_frame))) != 0) {
        if (rx_len >= 4 && memcmp(rx_frame, "BLS1", 4) == 0) {
            if (g_ble_control.status.accept(rx_frame, rx_len, millis())) ble_changed = true;
        } else if (g_now_playing.accept(rx_frame, rx_len, millis())) snapshot_changed = true;
    }

    const uint32_t now = millis();
    network_setup_peer_fresh(g_now_playing.fresh(now));
    network_setup_tick();
    if (network_setup_take_rescan_request()) {
        g_now_playing.reset();
        g_ble_control.reset();
        ui_set_now_playing(millis());
        ui_set_ble(millis());
        espnow_link_rescan();
    }
    static uint32_t last_playback_refresh = 0;
    if (snapshot_changed || ble_changed || now - last_playback_refresh >= 250) {
        last_playback_refresh = now;
        ui_set_now_playing(now);
        ui_set_ble(now);
    }
    poll_artwork();
    if (now - g_last_batt_poll >= 1000) poll_battery();

    if (now - last_heartbeat >= 5000) {
        last_heartbeat = now;
        uint32_t tx_sent = 0, tx_acked = 0;
        espnow_link_heartbeat(&tx_sent, &tx_acked);
        char batt[24];
        if (g_batt.percent >= 0) {
            snprintf(batt, sizeof(batt), "%.3fV/%d%%", (double)g_batt.volts, g_batt.percent);
        } else {
            snprintf(batt, sizeof(batt), "--");
        }
        rlog("[remote] alive up=%lus heap=%u psram=%u tokens=%lu espnow=%lu/%lu rt=%lu ch=%u "
             "batt=%s supply=%s%s",
             (unsigned long)(now / 1000),
             (unsigned)esp_get_free_heap_size(),
             (unsigned)ESP.getFreePsram(),
             (unsigned long)g_token_count,
             (unsigned long)tx_acked, (unsigned long)tx_sent,
             (unsigned long)espnow_link_retries(),
             (unsigned)espnow_link_channel(),
             batt, battery_supply_str(g_batt.supply),
             screen_is_battery_mode() ? " (battery timings)" : "");
        const auto &state = g_now_playing.state;
        rlog("[playback] snapshot=%u fresh=%u power=%u connected=%u aux=%u status=0x%02X eq=%u advancing=%u",
             (unsigned)g_now_playing.have_snapshot(), (unsigned)g_now_playing.fresh(now),
             (unsigned)state.power_on, (unsigned)state.connected, (unsigned)state.aux,
             (unsigned)state.play_status, (unsigned)state.eq_index, (unsigned)state.clock_advancing);
        rlog("[clock] cached=%lu age=%lu shown=%lu duration=%lu",
             (unsigned long)state.position_ms, (unsigned long)state.position_age_ms,
             (unsigned long)g_now_playing.position(now), (unsigned long)state.duration_ms);
    }
    delay(5);
}

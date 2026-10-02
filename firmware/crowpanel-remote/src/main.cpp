// BM83 wireless remote — CrowPanel ESP32 7" — Stage 2: ESP-NOW sender.
//
// Repurposes the solar-monitor wall HMI as a remote controller for the
// BM83-ESP32-S3-Nextion audio unit:
//
//   - splash + nine buttons (Prev / Play-Pause / Next / Vol- / Vol+ /
//     EQ / Power / Pair / E-Bind)
//   - buttons emit the SAME token vocabulary the Nextion sends over UART
//     (see NEXTION_SETUP.md): volume uses press/release pairs (BT_VOLUP_P /
//     BT_VOLUP_R, ...) for hold-and-repeat; the rest are single tokens
//   - every token is logged to serial AND transmitted over ESP-NOW to the
//     audio unit as "BMR1:<seq>:<token>" (see espnow_link.h). The audio-unit
//     receiver is Stage 3 — until it lands, sends report no-ack, which is
//     the expected bench state and proves the TX path runs.
//   - heartbeat line every 5 s so a silent panel is never ambiguous
//   - battery gauge (top right) from the panel's Li-ion cell, and supply
//     detection that picks the sleep policy: on USB the screen only dims
//     (a tap always wakes it); on battery it dims sooner and light-sleeps
//     until BOOT is pressed (see battery.h, display_init.h)
//
// Display/touch/power bring-up comes verbatim from the solar HMI firmware
// (same physical hardware). WiFi runs in unassociated STA mode for ESP-NOW
// only — no AP association, no SD in this build.

#include <Arduino.h>
#include <lvgl.h>
#include <stdarg.h>

#include "battery.h"
#include "display_init.h"
#include "espnow_link.h"

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
    Serial0.println(buf);
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

// ----- battery widget (the solar HMI header icon, scaled for the remote) -----
// [body with fill + charging bolt][tip]  "98%  4.12 V"
constexpr int      BATT_BODY_W = 40;
constexpr int      BATT_BODY_H = 20;
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
    lv_obj_align(row, LV_ALIGN_TOP_RIGHT, -16, 22);

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
    lv_obj_set_style_text_font(g_batt_text, &lv_font_montserrat_20, 0);
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

static void note_token(const char *token) {
    g_token_count++;
    espnow_send_token(token);
    // Sends are synchronous with bounded retries, so this is THIS token's
    // delivery status (ok = the unit's radio ACKed one of the attempts).
    rlog("[TOKEN] %s (#%lu) | link %s", token, (unsigned long)g_token_count,
         espnow_link_status_str());
    if (g_status_label) {
        lv_label_set_text_fmt(g_status_label,
                              "last token: %s   (%lu sent)   link: %s",
                              token, (unsigned long)g_token_count,
                              espnow_link_status_str());
    }
}

// Single-shot buttons: one token on click.
static void cb_click(lv_event_t *e) {
    note_token(static_cast<const char *>(lv_event_get_user_data(e)));
}

// Volume buttons: press/release pair for the firmware's hold-and-repeat.
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

static lv_obj_t *make_button(const char *text, int x, int y, int w, int h) {
    lv_obj_t *btn = lv_btn_create(lv_scr_act());
    lv_obj_set_pos(btn, x, y);
    lv_obj_set_size(btn, w, h);
    lv_obj_t *label = lv_label_create(btn);
    lv_label_set_text(label, text);
    lv_obj_set_style_text_font(label, &lv_font_montserrat_28, 0);
    lv_obj_center(label);
    return btn;
}

static void build_ui() {
    lv_obj_t *scr = lv_scr_act();
    lv_obj_set_style_bg_color(scr, lv_color_hex(0x101418), 0);

    lv_obj_t *title = lv_label_create(scr);
    lv_label_set_text(title, "BM83 Remote  -  bring-up build");
    lv_obj_set_style_text_color(title, lv_color_hex(0xE8EAED), 0);
    lv_obj_set_style_text_font(title, &lv_font_montserrat_28, 0);
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 14);

    build_battery_widget(scr);

    g_status_label = lv_label_create(scr);
    lv_label_set_text(g_status_label, "touch a button - tokens log to serial");
    lv_obj_set_style_text_color(g_status_label, lv_color_hex(0x9AA0A6), 0);
    lv_obj_align(g_status_label, LV_ALIGN_TOP_MID, 0, 58);

    // 3 rows x 3 columns on the 800x480 panel.
    const int W = 236, H = 112;
    const int X0 = 20, X1 = 282, X2 = 544;
    const int Y0 = 100, Y1 = 222, Y2 = 344;

    lv_obj_add_event_cb(make_button(LV_SYMBOL_PREV "  Prev", X0, Y0, W, H),
                        cb_click, LV_EVENT_CLICKED, (void *)"BT_PREV");
    lv_obj_add_event_cb(make_button(LV_SYMBOL_PLAY "  Play/Pause", X1, Y0, W, H),
                        cb_click, LV_EVENT_CLICKED, (void *)"BT_PLAY");
    lv_obj_add_event_cb(make_button(LV_SYMBOL_NEXT "  Next", X2, Y0, W, H),
                        cb_click, LV_EVENT_CLICKED, (void *)"BT_NEXT");

    lv_obj_t *vdn = make_button(LV_SYMBOL_VOLUME_MID "  Vol -", X0, Y1, W, H);
    lv_obj_add_event_cb(vdn, cb_press_release, LV_EVENT_PRESSED, (void *)"BT_VOLDN");
    lv_obj_add_event_cb(vdn, cb_press_release, LV_EVENT_RELEASED, (void *)"BT_VOLDN");
    lv_obj_add_event_cb(vdn, cb_press_release, LV_EVENT_PRESS_LOST, (void *)"BT_VOLDN");

    lv_obj_t *vup = make_button(LV_SYMBOL_VOLUME_MAX "  Vol +", X1, Y1, W, H);
    lv_obj_add_event_cb(vup, cb_press_release, LV_EVENT_PRESSED, (void *)"BT_VOLUP");
    lv_obj_add_event_cb(vup, cb_press_release, LV_EVENT_RELEASED, (void *)"BT_VOLUP");
    lv_obj_add_event_cb(vup, cb_press_release, LV_EVENT_PRESS_LOST, (void *)"BT_VOLUP");

    lv_obj_add_event_cb(make_button(LV_SYMBOL_SETTINGS "  EQ", X2, Y1, W, H),
                        cb_click, LV_EVENT_CLICKED, (void *)"BT_EQ");

    // Row 3 — power/pairing controls. Single-click tokens, exactly as the
    // Nextion sends them; main.py owns the behavior (MMI hold timing for
    // BT_POWER, pairing mode for BT_PAIR) and already debounces repeated
    // BT_EBIND bond-wipe presses firmware-side.
    lv_obj_add_event_cb(make_button(LV_SYMBOL_POWER "  Power", X0, Y2, W, H),
                        cb_click, LV_EVENT_CLICKED, (void *)"BT_POWER");
    lv_obj_add_event_cb(make_button(LV_SYMBOL_BLUETOOTH "  Pair", X1, Y2, W, H),
                        cb_click, LV_EVENT_CLICKED, (void *)"BT_PAIR");
    lv_obj_add_event_cb(make_button(LV_SYMBOL_TRASH "  E-Bind", X2, Y2, W, H),
                        cb_click, LV_EVENT_CLICKED, (void *)"BT_EBIND");
}

// ----- Arduino entry points ---------------------------------------------------
void setup() {
    Serial.begin(115200);
    Serial0.begin(115200);
    delay(200);
    rlog("");
    rlog("[remote] BM83 remote bring-up booting (built %s %s)", __DATE__, __TIME__);

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

    // Stage 2: bring the ESP-NOW link up before the UI so the first tap
    // can already transmit. Init failure is logged and non-fatal — the
    // panel keeps working as a serial-only remote.
    espnow_link_init(rlog);

    // Battery gauge after WiFi is up: the divider ratio was calibrated with
    // the radio running. On the bench a boot read taken before WiFi started
    // came out ~5% above every later reading (2026-10-02).
    battery_init(rlog);

    build_ui();
    rlog("[remote] UI built; panel should show the button grid now");
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

    lv_timer_handler();  // a tap may wake the dimmed screen here
    report_backlight_change();
    const bool sleep_due = screen_idle_tick(SCREEN_DIM_AFTER_MS);  // may dim
    report_backlight_change();
    if (sleep_due) {
        // Battery timings say light sleep. USB may have been plugged in
        // since the last 1 Hz sample, and a USB-powered remote must never
        // end up asleep behind BOOT: sample again and re-apply the supply
        // before committing (PR #157 review).
        poll_battery();
        if (screen_is_battery_mode()) {
            screen_light_sleep();       // blocks until BOOT is pressed
            report_backlight_change();  // the backlight is back on
            rlog("[power] woke from light sleep (BOOT)");
            // The unit may have changed channel while we slept: find it
            // again now, so the first tap is not spent on a stale channel.
            espnow_link_rescan();
        }
    }

    char rx_frame[ESPNOW_FRAME_MAX + 1];
    while (espnow_link_poll(rx_frame, sizeof(rx_frame))) {
        // Stage 3 will carry audio-unit state/metadata here; log for now.
        rlog("[ESPNOW RX] %s", rx_frame);
    }

    const uint32_t now = millis();
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
    }
    delay(5);
}

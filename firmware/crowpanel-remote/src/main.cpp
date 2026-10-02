// BM83 wireless remote — CrowPanel ESP32 7" — BRING-UP build.
//
// Stage 1 of repurposing the solar-monitor wall HMI as a remote controller
// for the BM83-ESP32-S3-Nextion audio unit. This build proves panel, touch,
// and the button/token semantics only:
//
//   - splash + nine stub buttons (Prev / Play-Pause / Next / Vol- / Vol+ /
//     EQ / Power / Pair / E-Bind)
//   - buttons emit the SAME token vocabulary the Nextion sends over UART
//     (see NEXTION_SETUP.md): volume uses press/release pairs (BT_VOLUP_P /
//     BT_VOLUP_R, ...) for hold-and-repeat; the rest are single tokens
//   - tokens are LOGGED to serial for now; the ESP-NOW link to the audio
//     unit is the next stage and will carry exactly these strings
//   - heartbeat line every 5 s so a silent panel is never ambiguous
//
// Display/touch/power bring-up comes verbatim from the solar HMI firmware
// (same physical hardware). No WiFi, no ESP-NOW, no SD in this build.

#include <Arduino.h>
#include <lvgl.h>
#include <stdarg.h>

#include "display_init.h"

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

static void note_token(const char *token) {
    g_token_count++;
    rlog("[TOKEN] %s (#%lu)", token, (unsigned long)g_token_count);
    if (g_status_label) {
        lv_label_set_text_fmt(g_status_label, "last token: %s   (%lu sent)",
                              token, (unsigned long)g_token_count);
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

    build_ui();
    rlog("[remote] UI built; panel should show the button grid now");
}

void loop() {
    static uint32_t last_heartbeat = 0;

    lv_timer_handler();
    screen_idle_tick(SCREEN_DIM_AFTER_MS);

    const uint32_t now = millis();
    if (now - last_heartbeat >= 5000) {
        last_heartbeat = now;
        rlog("[remote] alive up=%lus heap=%u psram=%u tokens=%lu",
             (unsigned long)(now / 1000),
             (unsigned)esp_get_free_heap_size(),
             (unsigned)ESP.getFreePsram(),
             (unsigned long)g_token_count);
    }
    delay(5);
}

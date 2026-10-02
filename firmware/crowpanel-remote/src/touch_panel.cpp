// GT911 touch driver wrapper for the CrowPanel 7" 800x480.
//
// Library: TAMCTec/gt911-arduino  (TAMC_GT911)
// I2C SDA=19, SCL=20 (shared with PCA9557 on the same bus).
// No INT or RST pin used (-1, -1).
// The 800x480 -> 0..799 / 0..479 mapping is inverted on both axes per the
// factory touch.h, so we call map(...) with reversed bounds.

#include "display_init.h"
#include "power.h"   // enter_light_sleep_until_boot() — second-stage escalation

#include <Arduino.h>
#include <Wire.h>
#include <TAMC_GT911.h>

namespace {

constexpr int   PIN_SDA = 19;
constexpr int   PIN_SCL = 20;
constexpr int   PIN_INT = -1;
constexpr int   PIN_RST = -1;
constexpr int   MAP_X1  = 800;
constexpr int   MAP_X2  = 0;
constexpr int   MAP_Y1  = 480;
constexpr int   MAP_Y2  = 0;
constexpr int   PANEL_W = 800;
constexpr int   PANEL_H = 480;

// After a wake-from-dim touch, swallow further touches for this many ms so
// the user's "tap to wake" doesn't also activate a button under the finger.
constexpr uint32_t WAKE_DEBOUNCE_MS = 300;

TAMC_GT911 g_ts(PIN_SDA, PIN_SCL, PIN_INT, PIN_RST,
                max(MAP_X1, MAP_X2),
                max(MAP_Y1, MAP_Y2));

uint32_t g_last_activity_ms     = 0;
bool     g_screen_dimmed        = false;
// Wake-debounce window: armed-flag + start-time, NOT an absolute deadline.
// The F4 fix compared a deadline with the signed idiom, which re-arms once
// the deadline is >2^31 ms stale — with dimming disabled that latched touch
// OFF for uptime 24.8→49.7 d (review 2026-07-25 M8). An armed flag plus
// elapsed-since compare is wrap-safe AND can't go stale.
bool     g_wake_ignore_active   = false;
uint32_t g_wake_ignore_since_ms = 0;
bool     g_battery_mode         = false;

}  // namespace

void screen_set_battery_mode(bool on_battery) { g_battery_mode = on_battery; }
bool screen_is_battery_mode()                 { return g_battery_mode; }

void touch_init() {
    // Wire.begin already called from display_init() — calling again is safe.
    Wire.begin(PIN_SDA, PIN_SCL);
    g_ts.begin();
    g_ts.setRotation(ROTATION_NORMAL);
}

void touch_read(lv_indev_drv_t *indev_driver, lv_indev_data_t *data) {
    g_ts.read();
    const uint32_t now = millis();

    if (!g_ts.isTouched) {
        data->state = LV_INDEV_STATE_REL;
        return;
    }

    // Any contact counts as user activity for the dim-timer, even if we
    // suppress the touch from LVGL below.
    g_last_activity_ms = now;

    if (g_screen_dimmed) {
        // Wake the screen and start the debounce window. Don't let this
        // touch propagate — otherwise tapping the dark panel to wake it
        // would also fire the button under the user's finger.
        set_backlight(255);
        g_screen_dimmed = false;
        g_wake_ignore_active   = true;
        g_wake_ignore_since_ms = now;
        data->state = LV_INDEV_STATE_REL;
        return;
    }

    if (g_wake_ignore_active) {
        if (now - g_wake_ignore_since_ms < WAKE_DEBOUNCE_MS) {
            // Still inside the wake-debounce window; user is probably
            // still lifting their finger from the wake-tap. Suppress.
            data->state = LV_INDEV_STATE_REL;
            return;
        }
        g_wake_ignore_active = false;
    }

    data->state = LV_INDEV_STATE_PR;
    data->point.x = map(g_ts.points[0].x, MAP_X1, MAP_X2, 0, PANEL_W - 1);
    data->point.y = map(g_ts.points[0].y, MAP_Y1, MAP_Y2, 0, PANEL_H - 1);
}

void screen_idle_tick(uint32_t timeout_ms) {
    if (g_last_activity_ms == 0) {
        // First call: count boot as activity so we don't dim before the
        // user has had a chance to interact.
        g_last_activity_ms = millis();
        return;
    }

    const uint32_t now            = millis();
    const uint32_t since_activity = now - g_last_activity_ms;

    // Stage 1 — dim. On battery, override the caller's timeout with the
    // shorter battery-mode value so we stretch runtime even if main.cpp
    // is still passing the USB-mode default.
    const uint32_t dim_after = g_battery_mode ? SCREEN_DIM_AFTER_MS_BATTERY
                                              : timeout_ms;
    if (!g_screen_dimmed && since_activity > dim_after) {
        set_backlight(0);
        g_screen_dimmed = true;
    }

    // Stage 2 — escalate from dim to ESP32 light sleep after a longer
    // idle window. Only reachable from the dimmed state. Blocks here
    // until the BOOT button (GPIO 0) is pressed; on return the screen
    // is back on and we reset idle tracking so the dim timer starts
    // fresh. Touch-wake is bypassed (the GT911 misbehaves across light
    // sleep on this hardware), so the wake-debounce window isn't armed.
#if SCREEN_SLEEP_AFTER_MS > 0
    const uint32_t sleep_after = g_battery_mode ? SCREEN_SLEEP_AFTER_MS_BATTERY
                                                : SCREEN_SLEEP_AFTER_MS;
    if (g_screen_dimmed && since_activity > sleep_after) {
        enter_light_sleep_until_boot();
        // On return: BOOT was pressed, backlight is back. Reset state so
        // we're treated as fresh activity and the dim timer restarts.
        g_screen_dimmed    = false;
        g_last_activity_ms = millis();
    }
#endif
}

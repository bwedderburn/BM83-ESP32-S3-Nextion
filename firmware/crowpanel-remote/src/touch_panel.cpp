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

TAMC_GT911 g_ts(PIN_SDA, PIN_SCL, PIN_INT, PIN_RST,
                max(MAP_X1, MAP_X2),
                max(MAP_Y1, MAP_Y2));

uint32_t g_last_activity_ms     = 0;
bool     g_screen_dimmed        = false;
// Wake-gesture suppression: a plain armed flag, no time compare at all.
// Armed by the touch that wakes a dimmed screen, cleared on the first
// no-touch report, so the ENTIRE wake gesture is swallowed however long
// the finger stays down. History: a deadline + signed-compare version
// re-armed when stale (review 2026-07-25 M8), and a 300 ms window leaked
// the tail of a held wake-touch to LVGL as a fresh press (PR #150 review).
bool     g_wake_ignore_active   = false;
bool     g_battery_mode         = false;

}  // namespace

void screen_set_battery_mode(bool on_battery) { g_battery_mode = on_battery; }
bool screen_is_battery_mode()                 { return g_battery_mode; }
bool screen_is_dimmed()                       { return g_screen_dimmed; }

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
        // First no-touch report ends any wake gesture: the finger that
        // woke the screen has lifted, so stop suppressing from the next
        // contact onward.
        g_wake_ignore_active = false;
        data->state = LV_INDEV_STATE_REL;
        return;
    }

    // Any contact counts as user activity for the dim-timer, even if we
    // suppress the touch from LVGL below.
    g_last_activity_ms = now;

    if (g_screen_dimmed) {
        // Wake the screen and arm the gesture suppression. Don't let this
        // touch propagate — otherwise tapping the dark panel to wake it
        // would also fire the button under the user's finger.
        set_backlight(255);
        g_screen_dimmed = false;
        g_wake_ignore_active = true;
        data->state = LV_INDEV_STATE_REL;
        return;
    }

    if (g_wake_ignore_active) {
        // The contact that woke the screen is still down. Suppress until
        // the controller first reports no touch — clearing on a timer here
        // handed the tail of a held wake-touch to LVGL as a fresh press.
        data->state = LV_INDEV_STATE_REL;
        return;
    }

    data->state = LV_INDEV_STATE_PR;
    data->point.x = map(g_ts.points[0].x, MAP_X1, MAP_X2, 0, PANEL_W - 1);
    data->point.y = map(g_ts.points[0].y, MAP_Y1, MAP_Y2, 0, PANEL_H - 1);
}

bool screen_idle_tick(uint32_t timeout_ms) {
    if (g_last_activity_ms == 0) {
        // First call: count boot as activity so we don't dim before the
        // user has had a chance to interact.
        g_last_activity_ms = millis();
        return false;
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
    // idle window. Only reachable from the dimmed state. Only BOOT (GPIO 0)
    // wakes it; touch cannot wake light sleep on this hardware (power.h).
    // That is why it is battery-only by default: SCREEN_SLEEP_AFTER_MS (USB)
    // is 0, so on USB the remote stays in dim and a tap always wakes it.
    // This only reports that sleep is due: the caller refreshes the supply
    // first (USB may have been plugged in since its last sample) and then
    // commits with screen_light_sleep() (PR #157 review).
    const uint32_t sleep_after = g_battery_mode ? SCREEN_SLEEP_AFTER_MS_BATTERY
                                                : SCREEN_SLEEP_AFTER_MS;
    return sleep_after > 0 && g_screen_dimmed && since_activity > sleep_after;
}

void screen_light_sleep() {
    enter_light_sleep_until_boot();
    // On return: BOOT was pressed, backlight is back. Count it as fresh
    // activity so the dim timer restarts, and swallow touches until the
    // controller first reports no-touch: the GT911 reports phantom touches
    // for a few samples after light sleep (power.h), and on a remote a
    // phantom press could fire E-Bind or Power.
    g_screen_dimmed      = false;
    g_last_activity_ms   = millis();
    g_wake_ignore_active = true;
}

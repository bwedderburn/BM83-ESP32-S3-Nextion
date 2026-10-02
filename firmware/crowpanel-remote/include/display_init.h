// Display + touch driver bring-up for the CrowPanel ESP32 7" RGB panel.
//
// Pins, panel timings, and the PCA9557 power-on dance are taken verbatim from
// Elecrow-RD/CrowPanel-7.0-HMI-ESP32-Display-800x480 (V2.0/V3.0 hardware).
// Verify by flashing the factory_firmare/ binary first — if that comes up,
// this should compile and run too.

#pragma once
#include <lvgl.h>

#define LGFX_USE_V1
#include <LovyanGFX.hpp>
#include <lgfx/v1/platforms/esp32s3/Panel_RGB.hpp>
#include <lgfx/v1/platforms/esp32s3/Bus_RGB.hpp>

class LGFX : public lgfx::LGFX_Device {
public:
    lgfx::Bus_RGB     _bus_instance;
    lgfx::Panel_RGB   _panel_instance;
    LGFX();
};

// The single global display instance. Defined in display_init.cpp.
extern LGFX lcd;

// Backlight pin used by the panel. Driven via ledc channel 1.
#ifndef TFT_BL
#define TFT_BL 2
#endif

// Order: power-on dance via PCA9557, then lcd.begin(), then backlight.
void display_init();

// LVGL v8 flush callback — copies tile bytes via lcd.pushImageDMA.
void display_flush(lv_disp_drv_t *disp, const lv_area_t *area, lv_color_t *color_p);

// Touch driver (GT911 over I2C).
void touch_init();
void touch_read(lv_indev_drv_t *indev_driver, lv_indev_data_t *data);

// Backlight + screen idle dimming.
//   set_backlight(0..255) sets the PWM duty on the TFT backlight (channel 1).
//   screen_idle_tick(timeout_ms) is called from the main loop; if no touch
//   has happened in `timeout_ms`, it dims the backlight to 0. Next touch
//   wakes it back to full and the touch is swallowed (no accidental
//   relay/button trigger). Returns true on the call that comes back from
//   light sleep (battery mode, BOOT pressed), so the caller can resync.
void set_backlight(uint8_t pwm_value);
bool screen_idle_tick(uint32_t timeout_ms);
bool screen_is_dimmed();

// Default backlight-dim timeout. Override via a -D build flag in
// platformio.ini (e.g. -DSCREEN_DIM_AFTER_MS=300000) — the #ifndef
// wrappers let an explicit build-flag value win. (The include/config.h
// mechanism belongs to the solar repo; this project has no such file.)
#ifndef SCREEN_DIM_AFTER_MS
#define SCREEN_DIM_AFTER_MS (10UL * 60UL * 1000UL)   // 10 minutes (USB powered)
#endif

// Shorter timeout when the panel is running on its onboard battery — the
// backlight is the dominant load so dimming aggressively stretches runtime
// from ~7.5 h to 20+ h on a 3000 mAh pack.
#ifndef SCREEN_DIM_AFTER_MS_BATTERY
#define SCREEN_DIM_AFTER_MS_BATTERY (2UL * 60UL * 1000UL)   // 2 minutes
#endif

// Second-stage standby: after this much continuous idle time (measured from
// the last touch, not from when dim started), escalate from backlight-off
// dim to ESP32 light sleep. While in light sleep the chip draws ~1-2 mA
// vs ~30 mA in plain dim. Wake requires a press of the BOOT button (GPIO 0)
// on the back of the panel — touch-wake is unreliable here (see power.h).
// 0 disables the escalation. On USB it is 0 by default: there is no energy
// to save, and a remote whose taps stop working until BOOT is pressed looks
// broken. The solar HMI used 30 min here.
#ifndef SCREEN_SLEEP_AFTER_MS
#define SCREEN_SLEEP_AFTER_MS 0UL                           // USB: never
#endif

// Battery-mode equivalent — escalates sooner since battery is precious.
#ifndef SCREEN_SLEEP_AFTER_MS_BATTERY
#define SCREEN_SLEEP_AFTER_MS_BATTERY (10UL * 60UL * 1000UL) // 10 minutes
#endif

// Tell the screen subsystem we're on battery (true) or USB (false). On
// battery, screen_idle_tick uses the battery timings above. Default: USB.
// main.cpp switches it from the battery module's supply detection.
void screen_set_battery_mode(bool on_battery);
bool screen_is_battery_mode();

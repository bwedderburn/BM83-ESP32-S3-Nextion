// LovyanGFX bring-up for the CrowPanel ESP32 7" 800x480 RGB panel.
//
// Pin map and timings copied verbatim from
//   factory_sourecode/LvglWidgets-LVGL-7.0/LvglWidgets-LVGL-7.0.ino
// in the Elecrow-RD/CrowPanel-7.0-HMI-ESP32-Display-800x480 repo.
//
// The PCA9557 reset sequence is required on V2.0+ hardware; without it the
// GT911 touch controller doesn't respond. V1.0 hardware works without it but
// running it is harmless on V1.0, so we always do it.

#include "display_init.h"

#include <Arduino.h>
#include <PCA9557.h>
#include <Wire.h>

LGFX::LGFX() {
    {
        auto cfg = _bus_instance.config();
        cfg.panel = &_panel_instance;

        cfg.pin_d0  = GPIO_NUM_15; // B0
        cfg.pin_d1  = GPIO_NUM_7;  // B1
        cfg.pin_d2  = GPIO_NUM_6;  // B2
        cfg.pin_d3  = GPIO_NUM_5;  // B3
        cfg.pin_d4  = GPIO_NUM_4;  // B4

        cfg.pin_d5  = GPIO_NUM_9;  // G0
        cfg.pin_d6  = GPIO_NUM_46; // G1
        cfg.pin_d7  = GPIO_NUM_3;  // G2
        cfg.pin_d8  = GPIO_NUM_8;  // G3
        cfg.pin_d9  = GPIO_NUM_16; // G4
        cfg.pin_d10 = GPIO_NUM_1;  // G5

        cfg.pin_d11 = GPIO_NUM_14; // R0
        cfg.pin_d12 = GPIO_NUM_21; // R1
        cfg.pin_d13 = GPIO_NUM_47; // R2
        cfg.pin_d14 = GPIO_NUM_48; // R3
        cfg.pin_d15 = GPIO_NUM_45; // R4

        cfg.pin_henable = GPIO_NUM_41;
        cfg.pin_vsync   = GPIO_NUM_40;
        cfg.pin_hsync   = GPIO_NUM_39;
        cfg.pin_pclk    = GPIO_NUM_0;
        cfg.freq_write  = 15000000;

        cfg.hsync_polarity    = 0;
        cfg.hsync_front_porch = 40;
        cfg.hsync_pulse_width = 48;
        cfg.hsync_back_porch  = 40;

        cfg.vsync_polarity    = 0;
        cfg.vsync_front_porch = 1;
        cfg.vsync_pulse_width = 31;
        cfg.vsync_back_porch  = 13;

        cfg.pclk_active_neg   = 1;
        cfg.de_idle_high      = 0;
        cfg.pclk_idle_high    = 0;

        _bus_instance.config(cfg);
    }
    {
        auto cfg = _panel_instance.config();
        cfg.memory_width  = 800;
        cfg.memory_height = 480;
        cfg.panel_width   = 800;
        cfg.panel_height  = 480;
        cfg.offset_x      = 0;
        cfg.offset_y      = 0;
        _panel_instance.config(cfg);
    }
    _panel_instance.setBus(&_bus_instance);
    setPanel(&_panel_instance);
}

LGFX lcd;

static PCA9557 g_io_expander;

void display_init() {
    // I2C for the touch + IO expander on shared bus (SDA=19, SCL=20).
    Wire.begin(19, 20);

    // PCA9557 reset dance — required on V2.0+ to bring up the GT911 cleanly.
    // IO0/IO1 toggling pulses the touch reset line; IO1 then goes input so
    // the GT911 can drive INT.
    g_io_expander.reset();
    g_io_expander.setMode(IO_OUTPUT);
    g_io_expander.setState(IO0, IO_LOW);
    g_io_expander.setState(IO1, IO_LOW);
    delay(20);
    g_io_expander.setState(IO0, IO_HIGH);
    delay(100);
    g_io_expander.setMode(IO1, IO_INPUT);

    lcd.begin();
    lcd.setRotation(0);

    // Backlight via ledc channel 1 — full brightness. Drop ledcWrite below
    // 255 if you want the wall display dimmer at night.
    pinMode(TFT_BL, OUTPUT);
    ledcSetup(1, 300, 8);
    ledcAttachPin(TFT_BL, 1);
    ledcWrite(1, 255);
}

void display_flush(lv_disp_drv_t *disp, const lv_area_t *area, lv_color_t *color_p) {
    const uint32_t w = (area->x2 - area->x1 + 1);
    const uint32_t h = (area->y2 - area->y1 + 1);
    lcd.pushImageDMA(area->x1, area->y1, w, h, (lgfx::rgb565_t *)&color_p->full);
    lv_disp_flush_ready(disp);
}

void set_backlight(uint8_t pwm_value) {
    // ledcWrite is idempotent — first call latched the PWM channel, this
    // just updates the duty.
    ledcWrite(1, pwm_value);
}

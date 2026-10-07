// CrowPanel onboard Li-ion cell: voltage gauge + USB/battery supply detection.
//
// Hardware: Brian's solder mod, carried over with the panel from the
// solar-monitor HMI: BAT+ -> 100 k -> IO17 -> 100 k -> GND. IO17 is ADC2 ch6
// and also the NS4168 audio amp's SDATA input (the remote never runs audio;
// the amp input loads the lower leg, which the calibrated ratio absorbs).
// The panel's 4054A charger leaves CHRG unconnected on V3.0, so whether USB
// is supplying is inferred from the voltage alone.
//
// Ported from solar-monitor/firmware/crowpanel-hmi/src/hmi_battery.*: the
// sampling, SOC curve and rate-limited display are unchanged. Supply
// detection is reworked, because here it picks the sleep policy (see
// battery.cpp).

#pragma once
#include <stdint.h>

// ADC GPIO on the divider midpoint; 0 = not fitted. Then the gauge shows
// "--%" and the supply stays Unknown, so the remote keeps USB timings.
#ifndef BATTERY_ADC_PIN
#define BATTERY_ADC_PIN 0
#endif

// V_battery / V_adc. The calibrated value lives in platformio.ini.
#ifndef BATTERY_DIVIDER_RATIO
#define BATTERY_DIVIDER_RATIO 2.0f
#endif

// Power source as last evidenced by a plug/unplug step. Unknown until the
// first one: the remote then runs USB timings (see battery.cpp for why).
enum class Supply : uint8_t { Unknown, Usb, Battery };

struct BatteryState {
    float  volts;     // trimmed-mean battery voltage; outside 2.5-4.5 V = no reading
    int    percent;   // displayed SOC 0..100 (rate-limited); -1 when no reading
    Supply supply;    // drives the sleep policy
    bool   charging;  // display only: the bolt (USB, or float voltage while unknown)
};

typedef void (*battery_log_fn)(const char *fmt, ...);

// Configure the ADC and log one boot reading (raw count, pin voltage,
// battery voltage) so the mod can be checked from serial alone. Call it
// after WiFi is up: the calibrated ratio assumes the radio running, and a
// read taken before WiFi started came out ~5% high on the bench.
void battery_init(battery_log_fn logf);

// Take a fresh reading. Call at ~1 Hz — the rate limits and the trend
// window assume it. Logs every supply change with the rule and the step.
BatteryState battery_poll();

// The panel's own load just changed: true = heavier (backlight restored,
// woke from light sleep), false = lighter (backlight dimmed). Call it before
// the next battery_poll(). That poll trusts a step only in the direction
// the load change could not have caused, and restarts the trend window.
void battery_note_load_change(bool load_increased);

// "usb" / "bat" / "?" for logs.
const char *battery_supply_str(Supply s);

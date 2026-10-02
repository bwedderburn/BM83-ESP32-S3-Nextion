// Battery gauge + supply detection for the remote — see battery.h for the
// hardware. Sampling, the SOC curve and the display rate limits are the
// solar HMI's hmi_battery.cpp unchanged; supply detection is reworked
// because here it drives the sleep policy, not just a charging bolt.

#include "battery.h"

#include <Arduino.h>

namespace {

battery_log_fn g_log = nullptr;

// --- Sampling (unchanged) ----------------------------------------------------
// 32-sample trimmed mean: sort, drop the top and bottom 8, average the middle
// 16. ADC2 shares its converter with the WiFi radio, and a read that collides
// with radio activity comes back as 0 or a full-scale spike; trimming drops
// those instead of letting one sample drag the mean ~250 mV.
constexpr int   ADC_SAMPLE_COUNT  = 32;
constexpr int   ADC_TRIM_PER_SIDE = 8;
constexpr float ADC_VREF_V        = 3.30f;
constexpr int   ADC_FULL_SCALE    = 4095;

// A connected 1S cell reads inside this window whether charging or loaded.
// Anything outside it is an open wire, a missing cell or a wrong ratio, and
// reports "no reading" rather than a misleading 0 % or 100 %.
constexpr float PLAUSIBLE_MIN_V = 2.50f;
constexpr float PLAUSIBLE_MAX_V = 4.50f;

// --- Voltage -> SOC (unchanged) ----------------------------------------------
// Published 1S LiPo OCV curve, biased ~30 mV low for the panel's load, dense
// through the 3.65-4.05 V plateau where the cell spends most of its life.
// Interpolated between anchors. Good for a visual gauge; remaining-minutes
// accuracy would need a fuel-gauge IC (MAX17048).
struct VoltsToPct { float v; int pct; };
constexpr VoltsToPct SOC_CURVE[] = {
    {4.15f, 100},  // freshly off the charger, settled
    {4.05f,  90},
    {3.95f,  80},
    {3.85f,  70},
    {3.80f,  60},
    {3.75f,  50},  // mid-plateau
    {3.70f,  40},
    {3.65f,  30},
    {3.60f,  20},
    {3.50f,  10},
    {3.35f,   5},  // low-voltage warning territory
    {3.00f,   0},  // protection cutoff
};
constexpr int SOC_CURVE_LEN = sizeof(SOC_CURVE) / sizeof(SOC_CURVE[0]);

// --- Displayed-SOC rate limits (unchanged) -----------------------------------
// Unplugging drops the terminal voltage by 10-12 pp worth with no real change
// in stored energy, so descent is capped: 0.05 pp/s bleeds that artifact off
// over ~4 min, while real discharge (~0.02 pp/s) tracks with little lag.
// Ascent is capped too (0.5 pp/s) so a plug-in fills rather than snaps. While
// charging near the top, the display snaps to 100: the CV taper above ~4.1 V
// holds only a few percent of capacity.
constexpr float SOC_MAX_DESCENT_PP_PER_S = 0.05f;
constexpr float SOC_MAX_ASCENT_PP_PER_S  = 0.50f;
constexpr int   SOC_TOPOFF_PCT_THRESHOLD = 85;

// --- Supply detection --------------------------------------------------------
// Evidence, latest wins; with none, the supply holds:
//   STEP  >= 40 mV between two 1 Hz polls: USB plugged (rise) or unplugged
//         (fall). The solar HMI used 60 mV; unplugging a dimmed, full remote
//         only moves the light standby load onto the cell, so its step is
//         smaller.
//   TREND >= 40 mV over 15 s, for a plug event spread over several polls.
// The panel's own load changes are the confounder: the backlight alone moves
// the terminal voltage tens of mV. On a known load change
// (battery_note_load_change) the next STEP is trusted in one direction only
// — a heavier load can only pull the voltage down, a lighter one only let it
// up, so a step the other way must be the supply — and the trend window
// restarts.
// The supply starts Unknown, and the remote runs USB timings until a step
// says battery: a wrong "USB" only costs battery life, but a wrong "battery"
// would light-sleep a USB-powered remote behind the BOOT button.
// FLOAT (>= 4.05 V, released below 4.03 V) is display-only and counts only
// while the supply is still unknown: it lights the charging bolt (and the
// top-off to 100 %) when the panel boots on USB with a full cell, where
// there is no step to see. It never decides the sleep policy, and a step
// overrides it, because a full cell under the light dimmed load reads above
// 4.05 V on battery too.
constexpr float    STEP_DV_V       = 0.040f;
constexpr float    TREND_DV_V      = 0.040f;
constexpr uint32_t TREND_WINDOW_MS = 15000;
constexpr float    FLOAT_ON_V      = 4.05f;
constexpr float    FLOAT_OFF_V     = 4.03f;

enum class StepIgnore : uint8_t { None, Rise, Fall };

bool       g_initialized    = false;
float      g_last_v         = -1.0f;   // previous plausible reading (STEP)
uint32_t   g_last_poll_ms   = 0;       // previous poll (dt for the rate limits)
float      g_soc_tracked    = -1.0f;   // displayed SOC; < 0 until seeded
Supply     g_supply         = Supply::Unknown;
bool       g_at_float       = false;
StepIgnore g_step_ignore    = StepIgnore::None;  // applies to the next poll
float      g_trend_start_v  = -1.0f;
uint32_t   g_trend_start_ms = 0;

float read_battery_volts() {
#if BATTERY_ADC_PIN > 0
    int samples[ADC_SAMPLE_COUNT];
    for (int i = 0; i < ADC_SAMPLE_COUNT; ++i) {
        samples[i] = analogRead(BATTERY_ADC_PIN);
    }
    for (int i = 1; i < ADC_SAMPLE_COUNT; ++i) {  // insertion sort, n = 32
        const int key = samples[i];
        int j = i - 1;
        while (j >= 0 && samples[j] > key) {
            samples[j + 1] = samples[j];
            --j;
        }
        samples[j + 1] = key;
    }
    uint32_t sum = 0;
    for (int i = ADC_TRIM_PER_SIDE; i < ADC_SAMPLE_COUNT - ADC_TRIM_PER_SIDE; ++i) {
        sum += samples[i];
    }
    const float adc_avg = (float)sum / (float)(ADC_SAMPLE_COUNT - 2 * ADC_TRIM_PER_SIDE);
    return (adc_avg / (float)ADC_FULL_SCALE) * ADC_VREF_V * BATTERY_DIVIDER_RATIO;
#else
    return -1.0f;
#endif
}

// Piecewise-linear over SOC_CURVE (anchors high -> low), clamped at the ends.
int volts_to_percent(float v) {
    if (v >= SOC_CURVE[0].v)                 return 100;
    if (v <= SOC_CURVE[SOC_CURVE_LEN - 1].v) return 0;
    for (int i = 0; i < SOC_CURVE_LEN - 1; ++i) {
        const float v_hi = SOC_CURVE[i].v;
        const float v_lo = SOC_CURVE[i + 1].v;
        if (v <= v_hi && v >= v_lo) {
            const float frac = (v - v_lo) / (v_hi - v_lo);
            return (int)((float)SOC_CURVE[i + 1].pct +
                         frac * (float)(SOC_CURVE[i].pct - SOC_CURVE[i + 1].pct) + 0.5f);
        }
    }
    return 0;  // unreachable given the clamps
}

void set_supply(Supply s, const char *rule, float dv) {
    if (s == g_supply) return;
    if (g_log) {
        g_log("[battery] supply %s -> %s (%s %+.3f V)", battery_supply_str(g_supply),
              battery_supply_str(s), rule, (double)dv);
    }
    g_supply = s;
}

}  // namespace

const char *battery_supply_str(Supply s) {
    switch (s) {
        case Supply::Usb:     return "usb";
        case Supply::Battery: return "bat";
        default:              return "?";
    }
}

void battery_init(battery_log_fn logf) {
    g_log = logf;
#if BATTERY_ADC_PIN > 0
    pinMode(BATTERY_ADC_PIN, INPUT);
    analogReadResolution(12);  // default 11 dB attenuation spans the ~1.7 V midpoint
    delay(50);                 // let the ADC mux settle
    const int   raw   = analogRead(BATTERY_ADC_PIN);
    const float v_pin = (raw / (float)ADC_FULL_SCALE) * ADC_VREF_V;
    if (g_log) {
        g_log("[battery] ADC GPIO%d, divider %.3f:1; boot read raw=%d pin=%.3fV batt=%.3fV",
              BATTERY_ADC_PIN, (double)BATTERY_DIVIDER_RATIO, raw, (double)v_pin,
              (double)(v_pin * BATTERY_DIVIDER_RATIO));
        if (raw == 0) {
            g_log("[battery] WARNING: ADC reads 0 - divider wire open or cell disconnected?");
        } else if (raw >= ADC_FULL_SCALE - 5) {
            g_log("[battery] WARNING: ADC at full scale - divider missing or wrong ratio?");
        }
    }
    g_initialized = true;
#else
    if (g_log) g_log("[battery] no ADC pin configured; gauge shows --%%, USB timings");
#endif
}

void battery_note_load_change(bool load_increased) {
    g_step_ignore   = load_increased ? StepIgnore::Fall : StepIgnore::Rise;
    g_trend_start_v = -1.0f;  // restart the trend window after the step
}

BatteryState battery_poll() {
    BatteryState s = {-1.0f, -1, g_supply, false};
    if (!g_initialized) return s;

    const uint32_t now   = millis();
    const uint32_t dt_ms = g_last_poll_ms ? (now - g_last_poll_ms) : 1000;
    g_last_poll_ms = now;

    const float v = read_battery_volts();
    const StepIgnore ignore = g_step_ignore;
    g_step_ignore = StepIgnore::None;
    if (v < PLAUSIBLE_MIN_V || v > PLAUSIBLE_MAX_V) {
        // No usable reading: keep the supply, restart the detectors so the
        // next good reading is not compared against a stale one.
        s.volts         = v;
        g_last_v        = -1.0f;
        g_trend_start_v = -1.0f;
        g_at_float      = false;
        return s;
    }
    s.volts = v;

    // --- Supply evidence ---
    if (g_last_v > 0.0f) {
        const float step = v - g_last_v;
        if (step >= STEP_DV_V && ignore != StepIgnore::Rise) {
            set_supply(Supply::Usb, "step", step);
            g_trend_start_v = -1.0f;
        } else if (step <= -STEP_DV_V && ignore != StepIgnore::Fall) {
            set_supply(Supply::Battery, "step", step);
            g_trend_start_v = -1.0f;
        }
    }
    g_last_v = v;
    if (g_trend_start_v < 0.0f) {
        g_trend_start_v  = v;
        g_trend_start_ms = now;
    } else if (now - g_trend_start_ms >= TREND_WINDOW_MS) {
        const float dv = v - g_trend_start_v;
        if (dv >= TREND_DV_V)       set_supply(Supply::Usb, "trend", dv);
        else if (dv <= -TREND_DV_V) set_supply(Supply::Battery, "trend", dv);
        g_trend_start_v  = v;
        g_trend_start_ms = now;
    }
    if (v >= FLOAT_ON_V)      g_at_float = true;
    else if (v < FLOAT_OFF_V) g_at_float = false;

    s.supply   = g_supply;
    s.charging = (g_supply == Supply::Usb) || (g_supply == Supply::Unknown && g_at_float);

    // --- Displayed SOC: rate-limited toward the curve (unchanged) ---
    const int raw_pct = volts_to_percent(v);
    float target = (float)raw_pct;
    if (s.charging && raw_pct >= SOC_TOPOFF_PCT_THRESHOLD) target = 100.0f;
    if (g_soc_tracked < 0.0f) {
        g_soc_tracked = target;  // seed directly: no ramp from 0 at boot
    } else {
        const float dt_s = (float)dt_ms / 1000.0f;
        const float gap  = target - g_soc_tracked;
        if (gap > 0.0f) {
            const float max_step = SOC_MAX_ASCENT_PP_PER_S * dt_s;
            g_soc_tracked += (gap < max_step) ? gap : max_step;
        } else if (gap < 0.0f) {
            const float max_step = SOC_MAX_DESCENT_PP_PER_S * dt_s;
            g_soc_tracked -= (-gap < max_step) ? -gap : max_step;
        }
    }
    int pct = (int)(g_soc_tracked + 0.5f);
    if (pct > 100) pct = 100;
    if (pct < 0)   pct = 0;
    s.percent = pct;
    return s;
}

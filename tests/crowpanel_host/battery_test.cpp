// Host scenarios for firmware/crowpanel-remote/src/battery.cpp: supply
// detection (which picks the remote's sleep policy) and the displayed SOC.
//
// Run by tests/test_crowpanel_battery.py. One scenario per process, because
// the module keeps its state in file-scope variables:
//     battery_test --list       print the scenario names
//     battery_test <name>       run one; exit 0 on pass
// Each poll() advances the clock 1 s, like the firmware's 1 Hz loop.

#include "battery.h"

#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>

uint32_t host_now_ms  = 1000;
int      host_adc_raw = 0;

namespace {

int g_failures = 0;

void log_to_stdout(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    std::printf("    log: ");
    std::vprintf(fmt, ap);
    std::printf("\n");
    va_end(ap);
}

void expect(bool ok, const char *what) {
    std::printf("  %s  %s\n", ok ? "ok  " : "FAIL", what);
    if (!ok) g_failures++;
}

// Battery voltage -> the ADC count the firmware would read.
void set_volts(float v) {
    host_adc_raw = (int)std::lround(v / (3.30f * BATTERY_DIVIDER_RATIO) * 4095.0f);
}

BatteryState poll(float v, int seconds = 1) {
    BatteryState s{};
    for (int i = 0; i < seconds; ++i) {
        host_now_ms += 1000;
        set_volts(v);
        s = battery_poll();
    }
    return s;
}

void boot(float v) {
    set_volts(v);
    battery_init(log_to_stdout);
}

// Boot on USB with no step seen yet, then unplug: the usual way into Battery.
BatteryState boot_then_unplug() {
    boot(4.15f);
    poll(4.15f, 3);
    return poll(4.05f);
}

// --- scenarios ----------------------------------------------------------------

void boot_on_usb_full() {
    boot(4.18f);
    const BatteryState s = poll(4.18f, 5);
    expect(s.supply == Supply::Unknown, "no step seen: supply unknown (USB timings)");
    expect(s.charging, "float voltage lights the bolt while unknown");
    expect(s.percent == 100, "full cell on USB shows 100%");
}

void unplug_step_means_battery() {
    const BatteryState s = boot_then_unplug();
    expect(s.supply == Supply::Battery, "-100 mV step -> battery");
    expect(!s.charging, "no bolt on battery");
}

void plug_step_means_usb() {
    boot_then_unplug();
    poll(4.05f, 10);
    const BatteryState s = poll(4.17f);
    expect(s.supply == Supply::Usb, "+120 mV step -> usb");
    expect(s.charging, "bolt on USB");
}

void dim_rise_is_not_usb() {
    boot_then_unplug();
    poll(4.05f, 5);
    battery_note_load_change(false);  // backlight off: lighter load
    BatteryState s = poll(4.11f);
    expect(s.supply == Supply::Battery, "+60 mV right after dimming is ignored");
    s = poll(4.11f, 30);
    expect(s.supply == Supply::Battery, "the trend window restarted at the new level");
}

void wake_fall_is_not_unplug() {
    boot_then_unplug();
    poll(4.05f, 3);
    poll(4.17f);  // plugged in
    poll(4.17f, 5);
    battery_note_load_change(true);  // backlight on: heavier load
    const BatteryState s = poll(4.10f);
    expect(s.supply == Supply::Usb, "-70 mV right after waking is ignored on USB");
}

void unplug_while_dimmed() {
    boot_then_unplug();
    poll(4.05f, 3);
    poll(4.18f);  // plugged in
    poll(4.18f, 10);
    const BatteryState s = poll(4.135f);
    expect(s.supply == Supply::Battery, "-45 mV (standby load moving to the cell) -> battery");
}

void usb_plugged_during_light_sleep() {
    boot_then_unplug();
    poll(4.05f, 5);
    host_now_ms += 3600000;  // an hour asleep
    battery_note_load_change(true);  // woke: backlight back on
    const BatteryState s = poll(4.17f);
    expect(s.supply == Supply::Usb, "a rise across a heavier-load change must be USB");
}

void rise_split_across_windows() {
    // PR #157 review: a plug-in rise spread over several polls, none of
    // them a 40 mV step, that a tumbling 15 s window would split into two
    // sub-threshold halves. The rolling window must still catch it.
    boot_then_unplug();
    poll(4.05f, 12);
    for (int i = 1; i <= 10; ++i) poll(4.05f + 0.005f * (float)i);  // +50 mV over 10 s
    const BatteryState s = poll(4.10f, 16);
    expect(s.supply == Supply::Usb, "+50 mV over 10 s -> usb");
}

void fall_split_across_windows() {
    boot(4.15f);
    poll(4.15f, 3);
    poll(4.20f);  // plugged in -> usb
    poll(4.20f, 12);
    for (int i = 1; i <= 10; ++i) poll(4.20f - 0.005f * (float)i);  // -50 mV over 10 s
    const BatteryState s = poll(4.15f, 16);
    expect(s.supply == Supply::Battery, "-50 mV over 10 s -> battery");
}

void noise_never_flips() {
    boot_then_unplug();
    BatteryState s = poll(3.80f);
    std::srand(1);
    int flips = 0;
    Supply prev = s.supply;
    for (int i = 0; i < 600; ++i) {
        const float noise = (float)((std::rand() % 2001) - 1000) / 100000.0f;  // +-10 mV
        s = poll(3.80f + noise);
        if (s.supply != prev) flips++;
        prev = s.supply;
    }
    expect(flips == 0 && s.supply == Supply::Battery, "10 min of +-10 mV noise: no flips");
}

void slow_drift_is_not_evidence() {
    boot_then_unplug();
    poll(3.80f, 3);
    BatteryState s{};
    for (int i = 0; i < 900; ++i) s = poll(3.80f + 0.00005f * (float)i);  // +45 mV / 15 min
    expect(s.supply == Supply::Battery, "45 mV over 15 min holds the supply (by design)");
}

void implausible_reading() {
    boot_then_unplug();
    poll(4.00f, 3);
    BatteryState s = poll(0.0f);
    expect(s.percent == -1, "0 V: no reading");
    expect(s.supply == Supply::Unknown, "a bad reading drops to Unknown (USB timings)");
    s = poll(4.10f);
    expect(s.supply == Supply::Unknown, "recovery is not compared against the bad reading");
}

void usb_plugged_during_bad_reading() {
    // PR #157 review: Battery at 4.05 V -> invalid -> steady USB at 4.17 V.
    // With no step after the gap, a held Battery would light-sleep on USB.
    boot_then_unplug();
    poll(4.05f, 3);
    BatteryState s = poll(0.0f);
    s = poll(4.17f, 30);
    expect(s.supply != Supply::Battery, "steady USB after a bad reading never runs battery timings");
}

void unplug_artifact_bleeds_off() {
    boot(4.15f);
    poll(4.15f, 3);
    poll(4.20f);  // plugged in
    const BatteryState top = poll(4.20f, 60);
    const BatteryState s0  = poll(4.05f);  // unplugged: raw 90 %
    const BatteryState s   = poll(4.05f, 60);
    std::printf("    display %d%% -> %d%% after 61 s\n", top.percent, s.percent);
    expect(top.percent == 100 && s0.supply == Supply::Battery, "starts at 100% on USB");
    expect(s.percent >= 96 && s.percent <= 98, "descends at 0.05 pp/s, not in one jump");
}

void high_voltage_on_battery_no_bolt() {
    boot(4.20f);
    poll(4.20f, 3);
    poll(4.10f);  // unplugged
    const BatteryState s = poll(4.10f, 5);
    expect(s.supply == Supply::Battery && !s.charging, "float voltage after a step: no bolt");
}

struct Scenario { const char *name; void (*run)(); };
const Scenario SCENARIOS[] = {
    {"boot_on_usb_full", boot_on_usb_full},
    {"unplug_step_means_battery", unplug_step_means_battery},
    {"plug_step_means_usb", plug_step_means_usb},
    {"dim_rise_is_not_usb", dim_rise_is_not_usb},
    {"wake_fall_is_not_unplug", wake_fall_is_not_unplug},
    {"unplug_while_dimmed", unplug_while_dimmed},
    {"usb_plugged_during_light_sleep", usb_plugged_during_light_sleep},
    {"rise_split_across_windows", rise_split_across_windows},
    {"fall_split_across_windows", fall_split_across_windows},
    {"noise_never_flips", noise_never_flips},
    {"slow_drift_is_not_evidence", slow_drift_is_not_evidence},
    {"implausible_reading", implausible_reading},
    {"usb_plugged_during_bad_reading", usb_plugged_during_bad_reading},
    {"unplug_artifact_bleeds_off", unplug_artifact_bleeds_off},
    {"high_voltage_on_battery_no_bolt", high_voltage_on_battery_no_bolt},
};

}  // namespace

int main(int argc, char **argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: %s --list | <scenario>\n", argv[0]);
        return 2;
    }
    if (std::strcmp(argv[1], "--list") == 0) {
        for (const Scenario &sc : SCENARIOS) std::printf("%s\n", sc.name);
        return 0;
    }
    for (const Scenario &sc : SCENARIOS) {
        if (std::strcmp(argv[1], sc.name) == 0) {
            std::printf("%s\n", sc.name);
            sc.run();
            return g_failures ? 1 : 0;
        }
    }
    std::fprintf(stderr, "unknown scenario: %s\n", argv[1]);
    return 2;
}

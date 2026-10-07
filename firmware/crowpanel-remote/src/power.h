// Light-sleep power management for the CrowPanel ESP32 7" HMI.
//
// Why BOOT-button wake (GPIO 0), not touch wake:
//   - The CrowPanel's GT911 touch controller has its INT pin tied to -1 in
//     this codebase (see src/touch_panel.cpp). The board's INT line isn't
//     wired to an RTC-capable GPIO, so we can't wake from a touch directly.
//   - A previous attempt used timer-wake + I2C polling, but the GT911
//     returns false-positive `isTouched` for several samples after ESP32
//     light sleep — likely I2C state corruption across the sleep boundary.
//     The chip would wake itself within ~1 s of entering sleep with no
//     real touch having happened.
//   - GPIO 0 (BOOT button) is RTC-capable and is only used at boot for
//     download mode, so repurposing it as a wake source at runtime is
//     safe. Wake is instantaneous (<1 ms) and the GT911 isn't in the
//     wake path at all.
//
// Why light sleep, not deep sleep:
//   - Light sleep preserves RAM and Wi-Fi association (via DTIM modem
//     sleep). Execution resumes right after esp_light_sleep_start() with
//     all UI state intact, so wake feels like flipping a light switch.
//   - Deep sleep would cold-reboot, costing 3-5 s of black screen and a
//     full Wi-Fi reconnect.
#pragma once

// Block until the BOOT button (GPIO 0) is pressed, then return.
// While blocked:
//   - Backlight is off (already the dominant power load).
//   - ESP32 in light sleep at ~1-2 mA.
//   - Wi-Fi modem-sleeps but stays associated; no reconnect on wake.
// On return:
//   - Backlight is restored to full.
//   - Caller is responsible for resetting any dim/idle-tracking state so
//     the dim timer starts fresh after wake.
void enter_light_sleep_until_boot();

# crowpanel-remote — BM83 wireless remote (bring-up stage)

The solar-monitor wall HMI (Elecrow CrowPanel 7.0", ESP32-S3-WROOM-1-N4R8,
800x480 RGB, GT911 touch) repurposed as a wireless remote for the BM83 audio
unit. Display/touch/power bring-up is copied verbatim from
`solar-monitor/firmware/crowpanel-hmi` — same physical panel; the previous
solar firmware stays recoverable from that repo at any time.

## Current stage: bring-up

This build renders a nine-button remote layout (Prev / Play-Pause / Next /
Vol- / Vol+ / EQ / Power / Pair / E-Bind) and logs the **same token
vocabulary the Nextion emits
over UART** (`BT_VOLUP_P` / `BT_VOLUP_R` press-release pairs for
hold-and-repeat, single tokens otherwise — see `../../NEXTION_SETUP.md`).
Tokens go to serial only. A heartbeat line prints every 5 s.

**Next stage:** carry those tokens over ESP-NOW to the audio unit
(CircuitPython has native `espnow`), plus metadata/state pushed back to the
remote. The audio-unit side lands as its own hardware-gated PR.

## Build & flash

shell (PowerShell, B-Intel)
```
cd C:\Users\brian\Repos\BM83-ESP32-S3-Nextion\firmware\crowpanel-remote; pio run -t upload --upload-port COM3
```

- Flash from Windows, not WSL (COM access; old apt platformio is broken).
- The CrowPanel's CH340 port **moves** (COM3 on 2026-10-01) — identify it by
  `VID_1A86&PID_7523` in Device Manager before flashing.
- **Never** upload to the BM83 audio board's CircuitPython console
  (`VID_303A&PID_7003`, COM6 on 2026-10-01).
- Monitor: `pio device monitor -p COM3 -b 115200`. Logs go to both USB CDC
  and UART0, so the CH340 port always shows them.

## Restoring the solar firmware

shell (PowerShell, B-Intel)
```
cd C:\Users\brian\Repos\solar-monitor\firmware\crowpanel-hmi; pio run -t upload --upload-port COM3
```

(Needs that project's `include/config.h` filled in — see its README.)

## Power behavior

The ported `power`/idle machinery is active: backlight dims after
`SCREEN_DIM_AFTER_MS` (10 min USB / 2 min battery), light-sleeps after 30/10
min, and wakes on the BOOT button (GPIO 0; GT911 touch-wake is unreliable
across light sleep on this hardware).

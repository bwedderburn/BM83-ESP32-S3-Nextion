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
cd C:\Users\brian\Repos\BM83-ESP32-S3-Nextion\firmware\crowpanel-remote; pio run -t upload
```

- Flash from Windows, not WSL (COM access; old apt platformio is broken).
- No `--upload-port` needed: `select_port.py` (wired in via
  `platformio.ini`) resolves the CrowPanel's CH340 by USB VID:PID
  (`1A86:7523`) at upload time, so the right port is found wherever it
  lands — and the BM83 audio board's CircuitPython console
  (`VID_303A&PID_7003`) can never match. If the panel is unplugged or a
  second CH340 is attached, the upload refuses to run rather than guess.
- Monitor: `pio device monitor -b 115200`. Logs go to both USB CDC and
  UART0, so the CH340 port always shows them.

## Restoring the solar firmware

shell (PowerShell, B-Intel)
```
cd C:\Users\brian\Repos\solar-monitor\firmware\crowpanel-hmi; pio run -t upload --upload-port COM3
```

(Needs that project's `include/config.h` filled in — see its README — and
the CH340's current COM number from Device Manager.)

## Power behavior

The ported `power`/idle machinery is active and pinned to USB mode
(`screen_set_battery_mode(false)` in `setup()`): backlight dims after
10 min, light-sleeps after 30 min, and wakes on the BOOT button (GPIO 0;
GT911 touch-wake is unreliable across light sleep on this hardware).
Tapping a dimmed screen only wakes it — the whole wake gesture is swallowed
until the finger lifts, so no button can fire by accident. The shorter
battery timings (2 min dim / 10 min sleep) are ported but stay dormant
until the battery stage adds supply detection.

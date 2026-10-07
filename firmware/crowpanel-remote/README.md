# crowpanel-remote — BM83 wireless remote

The solar-monitor wall HMI (Elecrow CrowPanel 7.0", ESP32-S3-WROOM-1-N4R8,
800x480 RGB, GT911 touch) repurposed as a wireless remote for the BM83 audio
unit. Display/touch/power bring-up is copied verbatim from
`solar-monitor/firmware/crowpanel-hmi` — same physical panel; the previous
solar firmware stays recoverable from that repo at any time.

## Current stage: Stage 2 — ESP-NOW sender

Nine-button remote layout (Prev / Play-Pause / Next / Vol- / Vol+ / EQ /
Power / Pair / E-Bind) emitting the **same token vocabulary the Nextion
sends over UART** (`BT_VOLUP_P` / `BT_VOLUP_R` press-release pairs for
hold-and-repeat, single tokens otherwise — see `../../NEXTION_SETUP.md`).

Every token is logged to serial AND transmitted over ESP-NOW, unicast to
the audio unit (unassociated STA mode, power-save off). The unit's WiFi
channel isn't fixed, so the remote finds it at boot by probing every
channel 1–13 three times for a hardware ACK and taking the centre of the
best-scoring run (neighbouring channels sometimes ACK at bench range):
`[espnow] audio unit found on chN (acks per ch1-13: ...)`. Each token is
retried up to 4× until ACKed (same `<seq>`, so the receiver drops repeats);
two undelivered tokens in a row trigger a rescan (at most every 10 s). The
heartbeat shows `espnow=<delivered>/<sent> rt=<retries> ch=<channel>`
(`ch=0` = not found).

- token frame, remote → unit: `BMR1:<seq>:<token>`
- state frame, unit → remote: `BMS1:<seq>:<key>=<val>` (reserved — Stage 3)

`<seq>` lets the receiver drop duplicates. The status line shows each
token's delivery: `link: ok` (the unit's radio ACKed it) / `no-ack` (the
unit is off, out of range, or running firmware without the receiver, whose
radio stays off) / `off` (ESP-NOW failed to start here). The peer MAC in
`espnow_link.cpp` is the audio unit's WiFi STA MAC (`DC:B4:D9:0C:6E:8C`,
printed by the unit's `[REMOTE] ESP-NOW receiver up: own-sta=...` boot
line) — not the `MAC:` value in its `boot_out.txt`, which differs.

**Audio-unit side (Stage 3):** the CircuitPython receiver
(`firmware/circuitpython/lib/remote`) merges these tokens into the exact
Nextion dispatch in `main.py`. Next: state/metadata frames back to the
remote so its screen can show what is playing.

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

## Battery and power

The panel keeps its solar-HMI battery setup: a 1S Li-ion cell on the XH
battery header, charged from USB by the onboard 4054A, and Brian's divider
`BAT+ → 100 k → IO17 → 100 k → GND` (calibrated ratio 2.485 in
`platformio.ini`). `battery.cpp`, ported from the solar HMI's
`hmi_battery.cpp`, reads it at 1 Hz: a 32-sample trimmed mean (reads that
collide with the radio on ADC2 are dropped), the 1S OCV curve, and a
rate-limited display. The header shows `98%  4.12 V`, with a bolt while
charging.

The detected supply picks the sleep policy:

| Supply | Screen dims after | Light sleep |
|---|---|---|
| USB, or not known yet | 10 min | never: a tap always wakes the screen |
| Battery | 2 min | after 10 min idle; press BOOT to wake |

- **Detection.** The charger's CHRG pin isn't wired on this board
  revision, so the supply is learned from plug/unplug voltage steps
  (≥ 40 mV between polls, or ≥ 40 mV over 15 s). The backlight switching
  moves the voltage too, so across a dim or wake only the step direction
  the load change could not cause is trusted.
- **Unknown at boot.** The remote runs USB timings until a step shows it's
  on battery. A remote reset while unplugged therefore stays on USB timings
  until the next plug/unplug, which costs battery but never strands it
  behind the BOOT button.
- **Light sleep** (battery only). Touch can't wake it (the GT911
  misbehaves across light sleep, see `power.h`), so press BOOT. After
  waking, touches are ignored until the finger lifts, so a phantom touch
  can't fire a button, and the remote rescans for the audio unit's channel.
  Plugging USB into a sleeping remote doesn't wake it; after BOOT it
  switches to USB timings from the voltage step.
- **Dim.** Tapping a dimmed screen only wakes it: the whole wake gesture
  is swallowed until the finger lifts, so no button can fire by accident.
- **Tuning.** The heartbeat logs `batt=<V>/<pct> supply=<usb|bat|?>`, and
  every supply change logs the rule and step that caused it.

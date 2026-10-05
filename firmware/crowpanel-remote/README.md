# crowpanel-remote — BM83 wireless remote

The solar-monitor wall HMI (Elecrow CrowPanel 7.0", ESP32-S3-WROOM-1-N4R8,
800x480 RGB, GT911 touch) repurposed as a wireless remote for the BM83 audio
unit. Display/touch/power bring-up is copied verbatim from
`solar-monitor/firmware/crowpanel-hmi` — same physical panel; the previous
solar firmware stays recoverable from that repo at any time.

## Current stage: Stage 2 — ESP-NOW sender

The 800×480 screen is titled **BM83 Remote**. Compact 200×64 secondary
buttons use 18-pixel labels, with Prev / EQ / Next above Power / Pair /
E-Bind. The bottom row is **Play/Pause → Vol − → volume slider → Vol +**.
The 20-pixel title and smaller battery readout have separate header space.

The remote emits the **same token vocabulary the Nextion sends over
UART** (`BT_VOLUP_P` / `BT_VOLUP_R` press-release pairs for the volume
buttons' hold-and-repeat, single tokens otherwise — see
`../../NEXTION_SETUP.md`). Volume buttons release on both finger lift and
press loss. The existing screen-wake gesture suppression remains in place.

The slider is a **relative adjustment**, not an actual-volume indicator:
drag left or right to request one to five steps, then release. Its thumb
returns to center immediately. Standalone `BT_VOLDN` / `BT_VOLUP` tokens
are sent one at a time, at least 200 ms apart measured from each send's
completion. New gestures or button presses cancel remaining slider steps;
press loss cancels the drag. Failed radio delivery or a three-second
deadline discards unfinished work, so reconnecting cannot replay an old
queue. The source may still ignore a delivered BLE HID key; counting
requests cannot establish its actual volume.

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

`<seq>` lets the receiver drop duplicates. The footer shows the last
action and whether it was sent or got no response. Serial logs retain
the exact token and `ok` / `no-ack` / `off` delivery status. A radio ACK
only confirms delivery to the peer radio; it does not prove playback,
audio-unit power state, or a resulting source-volume change. The peer MAC in
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
- `select_port.py` resolves a single CH340 (`1A86:7523`) automatically.
  Confirm that this adapter is the CrowPanel before uploading, and use
  `--upload-port COMx` explicitly. If no CH340 or multiple adapters are
  found, stop and identify the panel rather than relying on PlatformIO's
  fallback discovery. The audio board's native CircuitPython console
  uses a different VID:PID (`303A:7003`).
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

# crowpanel-remote — BM83 wireless remote

The solar-monitor wall HMI (Elecrow CrowPanel 7.0", ESP32-S3-WROOM-1-N4R8,
800x480 RGB, GT911 touch) repurposed as a wireless remote for the BM83 audio
unit. Display/touch/power bring-up is copied verbatim from
`solar-monitor/firmware/crowpanel-hmi` — same physical panel; the previous
solar firmware stays recoverable from that repo at any time.

## Now Playing and Settings

The main 800×480 page shows title, artist, album, playback state, elapsed
time, total time and a display-only progress bar. A 200×200 artwork placeholder
reserves space for a future image source. The **Settings** button opens a
second page containing Power, Pair, EQ and Erase BLE bonds. Compact Previous,
Play/Pause, Next and Volume −/+ controls remain available on both pages.
Battery/supply indication and screen-wake gesture suppression are preserved.
The current EQ mode is displayed beneath the battery, using the audio unit's
latest state rather than counting remote button presses.

Windows PC and iPhone playback are the intended verification targets. The
source must provide AVRCP metadata and timing to BM83: forwarding cannot
recover data withheld by the source. Missing values show unavailable text or
`--:--`; they never start a clock from the connection time. Mac support is
optional and its previously observed missing metadata is not repaired here.

The progress bar replaces the relative volume slider. It does **not** accept
drag-to-seek input: there is no arbitrary-position seek command in this build.
The panel can render artwork, but the documented BM83 UART path does not
support cover-art retrieval. This build neither fetches images online nor
transfers image data; no Mac/helper application is needed for the text/time link.

The remote emits the **same token vocabulary the Nextion sends over
UART** (`BT_VOLUP_P` / `BT_VOLUP_R` press-release pairs for the volume
buttons' hold-and-repeat, single tokens otherwise — see
`../../NEXTION_SETUP.md`). Volume buttons release on both finger lift and
press loss. The existing screen-wake gesture suppression remains in place.

The volume buttons keep their existing press/release hold-and-repeat
behavior. The source may still ignore a delivered BLE HID key; counting
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
- state frame, unit → remote: binary `BMS2` snapshot fragments (see below)

`<seq>` lets the receiver drop duplicates. The footer shows the last
action and whether it was sent or got no response. Serial logs retain
the exact token and `ok` / `no-ack` / `off` delivery status. A radio ACK
only confirms delivery to the peer radio; it does not prove playback,
audio-unit power state, or a resulting source-volume change. The peer MAC in
`espnow_link.cpp` is the audio unit's WiFi STA MAC (`DC:B4:D9:0C:6E:8C`,
printed by the unit's `[REMOTE] ESP-NOW receiver up: own-sta=...` boot
line) — not the `MAC:` value in its `boot_out.txt`, which differs.

The CircuitPython receiver (`firmware/circuitpython/lib/remote`) merges control
tokens into the existing Nextion dispatch. Its state publisher separately
forwards cached BM83 observations, without adding AVRCP requests or changing
the audio, AUX, power or volume backend.

### State return channel

`remote/now_playing.py` and `include/now_playing.h` define BMS2. Each binary
frame is at most 64 bytes: magic `BMS2`, boot-session u32, snapshot-sequence
u16, fragment index/count u8, total payload length u16, CRC16-CCITT-FALSE u16,
then up to 48 payload bytes. Multi-byte integers are big-endian. The payload
contains source flags, playback status, EQ mode, duration/position/sample-age
in milliseconds and three UTF-8 strings bounded to 96 bytes each.

Only a complete validated snapshot changes the display. The paired-unit MAC
is checked before frames enter a bounded 16-frame queue; WiFi callbacks never
call LVGL. Sequences and boot sessions reject duplicates and old snapshots.
Periodic full snapshots heal loss and refresh a waking panel. Rescanning after
wake discards buffered frames and the display awaits fresh source state.

The controller permits one outstanding state send and spaces frames by at
least 40 ms. Ordinary timing updates do not abort a snapshot in flight;
track, playback-state and transport boundaries do. A snapshot has a bounded
two-second send window. CircuitPython's native send API can itself retry for
up to two seconds on driver memory exhaustion, despite the completion guard;
actual-unit UART/coexistence timing must be checked before release.

Snapshots expire after six seconds without a new complete update. Playing
time advances only from a genuine source position, for at most five seconds
without another source sample; radio refreshes do not make old timing fresh.
An explicit clock-motion flag permits interpolation only after actual source
positions advance. Equal positions persisting at least 500 ms hold the clock,
even if a source still reports Playing. Closely spaced duplicate observations
do not freeze a coarse source clock. Unicode spacing is normalized to ordinary
spaces; meaningful UTF-8 names are retained, with missing glyphs diagnosed on
serial when text changes.
Pause, seek and track changes use subsequent source observations. Off, AUX,
disconnect and suspended AVRCP sessions clear the old remote track cache.

### Hardware acceptance checks

Host tests and a successful firmware build do not establish Windows/iPhone
correctness. Check iPhone first, then Windows: title/artist/album, elapsed and
total time, pause/resume, Next/Previous, a source-side seek and reconnect in
the middle of a track. Verify that Settings, volume hold/release, screen
dim/wake and lost-link expiry still work and the controller UART remains
healthy. These checks are pending until recorded on the actual hardware.

## Build & flash

Identify the CrowPanel's current COM port from its CH340 (`1A86:7523`)
before uploading. The example uses the verified bench port `COM3`; replace
it if the panel's current port differs.

shell (PowerShell, B-Intel)
```
cd C:\Users\brian\Repos\BM83-ESP32-S3-Nextion\firmware\crowpanel-remote
pio run -t upload --upload-port COM3
```

- Flash from Windows, not WSL (COM access; old apt platformio is broken).
- Although `select_port.py` can select a single adapter automatically,
  explicitly specifying the verified port is recommended. If no CH340
  or multiple adapters are
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

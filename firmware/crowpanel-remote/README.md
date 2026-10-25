# crowpanel-remote — BM83 wireless remote

The solar-monitor wall HMI (Elecrow CrowPanel 7.0", ESP32-S3-WROOM-1-N4R8,
800x480 RGB, GT911 touch) repurposed as a wireless remote for the BM83 audio
unit. Display/touch/power bring-up is copied verbatim from
`solar-monitor/firmware/crowpanel-hmi` — same physical panel; the previous
solar firmware stays recoverable from that repo at any time.

## Now Playing and Settings

The controller recovers separate artist and album fields from the captured
Windows web-player form `Plini — Sunhead - EP`. Recovery requires a missing
album, only AVRCP attributes 1/2/4 (optionally a blank 3), track number `0`,
and exactly one spaced em dash in the artist field. Existing album fields and
other reply profiles remain unchanged. Album suffixes such as ` - EP` stay
intact, so artwork lookup receives the complete album name. The Nextion uses
an ASCII dash for unavailable text rather than sending its internal Unicode
placeholder to the display.

CrowPanel metadata labels include matching Montserrat glyphs for accented
European Latin letters such as `é` and `â`, plus European punctuation. Original
UTF-8 text is preserved for artwork searches. See [font coverage and source
provenance](fonts/README.md) for the supported ranges and reproducible assets.

The main 800×480 page shows title, artist, album, playback state, elapsed
time, total time and a display-only progress bar. The 200×200 artwork area
automatically shows a matching cached or downloaded cover when available,
and a status placeholder otherwise. The **Settings** button opens a
second page containing Power, Pair, EQ, Erase BLE bonds and **Wi-Fi / Artwork**. Compact Previous,
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
The documented BM83 UART path does not support cover-art retrieval. Optional
artwork instead comes from an online catalog lookup on the CrowPanel, using
the forwarded track text; see [Automatic artwork](#automatic-artwork). No
computer or helper application is needed during playback.

The remote emits the **same token vocabulary the Nextion sends over
UART** (`BT_VOLUP_P` / `BT_VOLUP_R` press-release pairs for the volume
buttons' hold-and-repeat, single tokens otherwise — see
`../../NEXTION_SETUP.md`). Volume buttons release on both finger lift and
press loss. The existing screen-wake gesture suppression remains in place.

The volume buttons keep their existing press/release hold-and-repeat
behavior. The source may still ignore a delivered BLE HID key; counting
requests cannot establish its actual volume.

Every token is logged to serial AND transmitted over ESP-NOW, unicast to
the audio unit, with modem power-save off on the remote. Without artwork
Wi-Fi configured, both boards use unassociated STA mode. The unit's WiFi
channel isn't fixed, so the remote finds it at boot by probing every
channel 1–13 three times for a hardware ACK and taking the centre of the
best-scoring run (neighbouring channels sometimes ACK at bench range):
`[espnow] audio unit found on chN (acks per ch1-13: ...)`. Each token is
retried up to 4× until ACKed (same `<seq>`, so the receiver drops repeats);
two undelivered tokens in a row trigger a rescan (at most every 10 s). The
heartbeat shows `espnow=<delivered>/<sent> rt=<retries> ch=<channel>`
(`ch=0` = not found).

With artwork Wi-Fi enabled, both boards join the same 2.4 GHz access-point
BSSID and ESP-NOW follows that AP's channel. The remote does not hop channels
while associated, scanning or joining. A lost audio-unit link causes Wi-Fi
to pause so local ESP-NOW discovery can recover controls; use **Retry both**
in Wi-Fi setup after the link returns.

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
After expiry, a new fragment-zero-led, validated snapshot can resynchronize
the sequence even after a long outage; partial frames cannot revive old state.

The controller permits one outstanding state send and spaces frames by at
least 40 ms. Ordinary timing updates do not abort a snapshot in flight;
track, playback-state and transport boundaries do. A snapshot has a bounded
two-second send window. CircuitPython's native send API can itself retry for
up to two seconds on driver memory exhaustion, despite the completion guard.
Actual Windows web-player playback kept the BM83 UART healthy and snapshots
fresh during associated-Wi-Fi artwork fetching; that check does not force the
driver's memory-exhaustion path.

Snapshots expire after six seconds without a new complete update. Playing
time advances only from a genuine source position, for at most five seconds
without another source sample; radio refreshes do not make old timing fresh.
This source-age limit also applies to paused or stalled displayed positions.
Genuine nonzero source positions remain usable when the total duration is
unknown; a zero position with unknown duration remains unavailable.
An explicit clock-motion flag permits interpolation only after actual source
positions advance. Equal positions persisting at least 500 ms hold the clock,
even if a source still reports Playing. Closely spaced duplicate observations
do not freeze a coarse source clock. Unicode spacing is normalized to ordinary
spaces; meaningful UTF-8 names are retained, with missing glyphs diagnosed on
serial when text changes.
Pause, seek and track changes use subsequent source observations. Off, AUX,
disconnect and suspended AVRCP sessions clear the old remote track cache.

## Automatic artwork

The CrowPanel searches MusicBrainz using artist and album; when the source
omits the album, it can use artist and track title instead. A sufficiently
high search score alone is not accepted: normalized names must match and
the candidates must identify one release group. Album/track comparison permits
an omitted in-word apostrophe, such as `Dreams` versus `Dream's`; artist identity
remains strict. Only a complete successful empty album search permits one
bounded fallback query, followed by the same identity and uniqueness checks.
Apple Music's trailing album labels ` - EP` and ` - Single` can match an
unlabelled catalog title only when its release type also matches. Literal full
titles and genuine hyphens are preserved; track-title labels are not stripped.
Ambiguous results,
compilations, generic artist names and incomplete or oversized results keep
the placeholder. This is a catalog match, so a cover is not guaranteed for
every track or edition. The matching cover is fetched from the Cover Art
Archive's `front-250` endpoint, decoded as JPEG and fitted into the artwork
area. When MusicBrainz identifies an album but Cover Art Archive returns no
cover (HTTP 404), the worker also searches Deezer for that exact artist and
album. It accepts only one matching album identity and never substitutes
live/deluxe versions or another artist. This second provider requires album
metadata; title-only searches keep the existing MusicBrainz/CAA path. Primary
network/TLS failures remain retryable rather than triggering another catalog.
Deezer's medium JPEG is tried first; if its encoding is unsupported, the worker
tries the provider's canonical smaller thumbnail once. No audio is downloaded.
Online searches send the relevant track text to these public services.

A background worker owns network requests, decoding and SD operations;
LVGL updates remain in the main task. Lookup failures, missing artwork,
unavailable Wi-Fi, invalid network time or TLS errors leave the placeholder
and do not change the metadata, playback clock or control backend. New
track requests retire old artwork results. Requests use verified HTTPS,
bounded responses and rate limiting. TLS fetching requires network time
and the explicit maintained CA bundle; there is no insecure fallback.
Provider references, trust-store regeneration and third-party notices are
in [lib/artwork_trust/README.md](lib/artwork_trust/README.md).
Temporary network failures display `Retrying artwork...` while the worker
retries automatically after one minute. Rapid track changes retain the
controller's required metadata refresh until the existing AVRCP throttle and
stream-start quiet window permit it; they must not discard that refresh and
leave the CrowPanel without track details or a cover until another track event.

### SD cache

The existing SD card is mounted over the board's SPI connection (SCK 12,
MISO 13, MOSI 11, CS 10). The firmware never formats the card. Its cache
uses only `/bm83-artwork/aw-<SHA256>.*`; unrelated files and directories
are preserved. The cache is bounded to 64 entries and 8 MiB, with old
entries evicted as needed. Misses are cached for 24 hours when network
time is available. Positive cached covers can be displayed offline,
including before time synchronization. A missing or unwritable card
disables persistent caching; an online cover can still be displayed.
The matching-policy update retries older cached misses while preserving
existing positive covers and their filenames.
The second-provider update likewise retries earlier misses. Successfully decoded
Deezer covers use the same bounded SD cache and verified MusicBrainz album ID;
returning to an album needs no computer, provider account or runtime helper.
Deezer API content is used for this private, noncommercial unit under its
[developer terms](https://developers.deezer.com/termsofuse) and
[firmware guidelines](https://developers.deezer.com/guidelines).

### One-time Wi-Fi setup

Both boards have one 2.4 GHz radio shared by Wi-Fi and ESP-NOW. They must
join the **same BSSID**, not merely the same SSID: two mesh access points
can share a name while using different channels. Enterprise Wi-Fi is not
supported. Router channel changes can be followed by rejoining the saved
BSSID; replacing the AP requires enrollment again.

1. Install the artwork-capable firmware on both boards and connect both
   boards to a macOS or Linux setup computer by USB. The utility requires
   POSIX private-file permissions and checks support before changing anything.
   This enrollment-host requirement does not restrict Windows playback after setup.
   Windows remains a supported playback source without a runtime helper.
   Pause playback for setup, which
   briefly restarts the audio controller. Ensure its writable `CIRCUITPY`
   volume is mounted and Python with `pyserial` is available.
2. Close serial monitors and captures. From the repository root, start the
   one-time utility with a **new** private rollback directory:

   ```sh
   python3 tools/provision_artwork_wifi.py --volume /Volumes/CIRCUITPY --output /private/tmp/bm83-artwork-setup
   ```

   Adjust the volume and output paths for the host. If necessary, identify
   the devices with `--controller-serial` and `--crow-port`; the utility
   requires exactly one matching controller (`303A:7003`) and CrowPanel
   CH340 (`1A86:7523`).
3. Open **Settings → Wi-Fi / Artwork**, select **Scan**, choose the desired
   2.4 GHz access point, enter its password and press **Save**. Save stages
   a pending profile; it does not immediately switch the live radio.
4. The utility transfers the profile over physical USB, joins the
   controller, trial-joins the CrowPanel, verifies fresh ESP-NOW snapshots
   and commits the panel's profile. Resume playback after it reports
   success. Disconnecting the computer afterward is supported; the utility
   is not a runtime helper.

Credentials are stored locally in CrowPanel NVS and the controller's
`.artwork_wifi.json`; these stores are not encrypted at rest. The utility
does not print credentials, and its host rollback directory/files use
private permissions. Keep that directory private. The USB profile response
contains credentials, so do not record the setup serial stream or publish
its raw contents. Profiles are not transferred through ESP-NOW.

Before a commit is sent, a failed setup restores the previous controller
profile and aborts the panel's trial; a trial also times out automatically.
Commit requests are retried with the same session nonce to recover a lost
acknowledgment. If the final commit acknowledgment remains unconfirmed,
the utility records that outcome and retains the new controller profile:
the panel may already have committed. Do not restore just one board in
that state. Check the on-panel connection and live metadata, then repeat
the complete two-board enrollment with a new private output directory if
needed. Loss of power between the two devices' writes cannot be made atomic.

Wi-Fi association and scans share radio time with ESP-NOW. The firmware
prioritizes the audio-unit link, so a failed connection can leave artwork
offline until **Retry both** is selected. Cached art remains useful in
that state; the text/time link still depends on fresh BM83 source data.

### Verification status

The installed metadata/clock baseline has actual iPhone and Windows
verification, including displayed track details and advancing time.
iPhone pause/resume, Next and source-side seek passed. The latest Windows
clock-motion, spacing and EQ changes were also confirmed on the hardware;
a paused clock remained fixed in the recorded telemetry.

The artwork revision is installed on the actual ESP32-S3 boards. Two-board
Wi-Fi enrollment, SD mounting, a verified HTTPS cover download and positive
SD-cache reads passed. The user confirmed the correct cover, a stationary
paused clock, CrowPanel pause/resume and source-side seeking with the Windows
Apple Music web player. Telemetry confirms `ready cache=1 sd=1` on returning
to the album and a held displayed clock despite increasing raw paused samples.
The user also confirmed iPhone covers, metadata, clocks, CrowPanel pause/resume
and Next, and source-side seeking. Both displays followed all four checks.
The final punctuation correction downloaded the correct Chimp Spanner cover
on the actual panel. The user then confirmed that both the Chimp Spanner and
Sithu Aye covers appeared correctly and returned promptly when switching
between the new and previously saved albums.
The typed release-label correction also found Plini's `Sunhead` cover from
Apple Music's `Sunhead - EP` metadata. The user confirmed the correct cover,
metadata, clocks and CrowPanel pause/resume on iPhone with that revision.
With the final controller and CrowPanel updates, the user confirmed that all
three covers—Sithu Aye's `Senpai III`, Chimp Spanner's `At the Dreams Edge`
and Plini's `Sunhead - EP`—returned correctly and promptly. The final Windows
web-player check also passed for artwork, metadata and clocks, including a
ten-second pause and resume. The final iPhone check included a five-second
pause and resume with correct Plini artwork and metadata.

The public host suite, real target build, production JPEG decoder and cache
compatibility checks pass. Battery sleep/wake with associated Wi-Fi, offline
cache display and unavailable-AP recovery still need dedicated hardware checks.
The SD mount disables formatting and all cache operations stay in its reserved
directory; the app-only flash preserves the saved Wi-Fi configuration.

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
  can't fire a button. Sleep waits for artwork/SD/network work to quiesce,
  then stops ESP-NOW and Wi-Fi. Manual light sleep does not preserve AP
  association. On wake the remote rebuilds the radio, awaits fresh track
  state and rejoins a previously enabled committed network; an offline
  profile remains in local control mode until **Retry both**. This new
  artwork sleep/wake path still needs a battery hardware check.
  Plugging USB into a sleeping remote doesn't wake it; after BOOT it
  switches to USB timings from the voltage step.
- **Dim.** Tapping a dimmed screen only wakes it: the whole wake gesture
  is swallowed until the finger lifts, so no button can fire by accident.
- **Tuning.** The heartbeat logs `batt=<V>/<pct> supply=<usb|bat|?>`, and
  every supply change logs the rule and step that caused it.

## Paused playback position

The current Windows Apple Music **web player** test reports PAUSED over
Bluetooth while its raw position counter continues to increase. The browser
has not been identified. Earlier Windows PC testing did not establish which
player was in use.

When the source explicitly reports PAUSED, the CrowPanel holds the first valid
paused position across fresh snapshots for that track. It retains the raw
samples for diagnostics and does not invent a different playback status.
Resume, track invalidation/identity changes, controller sessions, transport
changes, unknown timing and snapshot expiry retire the hold. The earlier
handling of PLAYING with a genuinely frozen source clock remains in place.

A seek while paused is displayed on resume, consistent with the Nextion; an
advancing source counter alone cannot distinguish a real seek from this source
bug. Starting or reconnecting while the source is already paused cannot recover
the true pause point if that source counter is already wrong. Verification
therefore resumes playback first, then pauses again to establish a fresh anchor.

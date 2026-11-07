# BM83 Remote — ESP32-S3, Nextion and CrowPanel

An audio controller and touchscreen remote built around the Microchip BM83.
The BM83 carries Bluetooth audio; an ESP32-S3 running CircuitPython sends UART
control commands, reads playback metadata and drives a Nextion display. An
optional CrowPanel adds a wireless Now Playing screen, playback controls and
album artwork.

## Hardware and connections

| Component | Role |
| --- | --- |
| ESP32-S3 DevKitC-1 | CircuitPython controller, UART interfaces and BLE HID Consumer Control |
| Microchip BM83 module / breakout | Bluetooth audio and AVRCP transport/metadata |
| Nextion NX3224F028 | Local UART touchscreen |
| Elecrow CrowPanel 7-inch ESP32-S3 | Optional 800×480 ESP-NOW remote and Wi-Fi artwork display |
| UDA1334A I²S DAC and Adafruit PCM5100 I²S DAC | External audio-output hardware used in the project; select the wiring and configuration for the actual board |

The BM83 audio connection and the ESP32's **B's Groovy BT CTRL** BLE volume
connection are separate. Audio can continue even if the controller or metadata
path fails. Pin assignments in
[`firmware/circuitpython/main.py`](firmware/circuitpython/main.py) are the source
of truth for the controller wiring. Both DAC boards are part of the project's
hardware inventory; match each board's wiring to the actual audio configuration.
See the [hardware reference](docs/reference/hardware.md).

## Current functionality

- BM83 UART power, playback, track and EQ control, plus AVRCP metadata/timing.
- Nextion metadata, playback clock, EQ and AUX indication.
- BLE HID relative volume up/down controls on the connected source.
- CrowPanel Now Playing, compact transport/volume buttons, Settings and battery
  indication; its progress bar displays playback position and does not seek.
- Optional Wi-Fi album artwork lookup on CrowPanel using track metadata.
- Bond-preserving Pause/Enable controls for handing the volume remote between
  saved hosts, with confirmed state rather than radio-delivery inference.
- An optional [Mac metadata bridge](docs/guides/mac-metadata-bridge.md) for sources
  that omit native AVRCP track text. Bluetooth continues to carry the audio.

**Mute synchronization has not been pursued and is not a supported feature.**
The code contains a source-native HID mute command, but there is no reported
source mute state to synchronize. There is also no verified absolute-volume
feedback: counting HID requests cannot produce a trustworthy volume percentage.

The optional [Universe badge add-on](addons/universe-badge/README.md) and matching
authenticated receiver source are included. The
[November 4 B-Intel Phase 1 run](docs/reliability/phase1-bintel-2026-11-04.md)
passed its agreed measured, physical and restoration/recovery scope. Other
platforms and power-order cases remain subject to the
[acceptance gates](docs/reliability/README.md). Host tests do not establish stable
radio, audio or screen behavior.

## Start here

1. Read the [documentation index](docs/README.md) and
   [Nextion setup](docs/guides/nextion-setup.md).
2. Use the [deployment guide](docs/guides/deployment.md) for baseline `.py` setup,
   backups and rollback. It includes the installed-controller recovery exception.
3. Read the [CrowPanel guide](firmware/crowpanel-remote/README.md) for its separate
   firmware, ESP-NOW pairing and one-time USB Wi-Fi/artwork setup.
4. Use the [BLE handoff guide](docs/guides/ble-volume-handoff.md) to switch saved
   hosts without erasing bonds. A competing host can reconnect first.

For compiled project libraries, follow the
[pinned CircuitPython build guide](docs/guides/building.md). Keep `boot.py` and
`main.py` as source, and regenerate `dist/` from canonical firmware rather than
editing generated files.

## Repository layout

```text
firmware/circuitpython/    Canonical audio-controller source
firmware/crowpanel-remote/ CrowPanel Arduino/LVGL source and build configuration
addons/universe-badge/     Optional badge client, assets and host tests
dist/                     Generated CircuitPython deployment artifacts
docs/                     Guides, reviews, validation, troubleshooting and references
scripts/                  Host checks and build/support scripts
tests/                    Host regression tests
tools/                    Provisioning, diagnostics and pinned native-build recipes
```

Vendor manuals, firmware packages and utilities are consolidated under
[`docs/reference/vendor/bm83/`](docs/reference/vendor/bm83/README.md), with a
byte-hash inventory. They retain their upstream terms and are not project
release assets.

## Development and validation

```sh
python -m pip install -r requirements-reliability.txt
python -m pytest -q
python scripts/check_reliability_setup.py
```

The complete host suite targets Linux; some fixtures depend on POSIX permissions
and native build tools. See [testing](docs/guides/testing.md) for optional compiler
gates, and [scan status](docs/security/SCAN-STATUS.md) for security-scan coverage.
Host tests, native compilation and physical acceptance are separate evidence.

## Known limits and release status

- Windows Apple Music can retain a stalled audio session after BM83 power cycling.
  The successful recovery used a source-side Bluetooth audio disconnect/reconnect;
  unit-side retries did not establish automatic recovery. See the
  [hardware test record](docs/validation/hardware-test-limitations.md).
- BLE/AVRCP contention, native runtime teardown and receiver reliability still have
  explicit investigation and acceptance gates in the
  [reliability runbook](docs/reliability/README.md).
- Metadata availability, including genre and playback timing, depends on the source.
  Online artwork is a lookup result, not artwork retrieved from BM83 UART.
- The [first-release draft](docs/releases/v0.1.0.md) describes the candidate scope,
  proposed assets and remaining gates. Drafting a release does not qualify it for
  unattended deployment.

Project code is provided under [LICENSE](LICENSE); bundled third-party material
retains its own terms. See [security reporting](SECURITY.md) and the
[code of conduct](CODE_OF_CONDUCT.md).

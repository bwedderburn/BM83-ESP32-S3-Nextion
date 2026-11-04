# Hardware inventory and integration boundaries

The project combines a BM83 audio board, an ESP32-S3 controller, a Nextion
touchscreen and an optional CrowPanel wireless remote. The owner's audio-output
hardware includes **both the UDA1334A DAC and the Adafruit PCM5100 I²S DAC**.
The [Adafruit PCM5100 product reference](https://www.adafruit.com/product/6251)
identifies that board; it should not be silently substituted with a similarly
named PCM5102A board in diagrams or the bill of materials.

| Component | Current project role |
| --- | --- |
| Microchip BM83 / BM83M1 breakout | Bluetooth audio, AVRCP metadata and transport control over UART |
| ESP32-S3 DevKitC-1 | CircuitPython control, BM83 and Nextion UARTs, separate BLE HID volume connection |
| Nextion NX3224F028 | Local touchscreen controls and metadata display |
| Elecrow CrowPanel 7-inch, ESP32-S3, 800×480 | Optional ESP-NOW remote with Wi-Fi artwork lookup |
| UDA1334A I²S DAC | Audio-output hardware in the owner's inventory |
| Adafruit PCM5100 I²S DAC | Additional audio-output hardware in the owner's inventory |

The inventory does not establish that every board is simultaneously wired into
one signal path. Confirm the actual DAC board, power rails, I²S source, pin
labels and output levels before drawing or changing a connection. The current
repository is not a universal pin-compatible wiring specification for both DACs.
Controller pin definitions remain in
[`firmware/circuitpython/main.py`](../../firmware/circuitpython/main.py).

BM83's A2DP audio path runs independently of the ESP32's controller application.
The separate ESP32 BLE HID connection supplies relative source volume requests;
it does not report absolute volume or synchronized mute state. A playing source
clock or a radio acknowledgement alone does not prove audible audio.

The [vendor archive](vendor/bm83/README.md) retains previously tracked manuals and
packages. The [validation records](../validation/hardware-test-limitations.md)
and [reliability runbook](../reliability/README.md) define the limits of existing
physical evidence. Repository maintenance does not authorize hardware probes,
resets or firmware installation.

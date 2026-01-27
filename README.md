# ESP32-S3 Audio Remote Control (BM83 + Nextion + BLE HID)

This project implements a CircuitPython-based remote control system for audio devices using:

- **ESP32-S3 DevKitC-1**
- **BM83 Bluetooth module** (A2DP, AVRCP, HID)
- **Nextion NX3224F028** UART touchscreen
- **BLE HID** volume/mute support (for iOS/macOS)

## 📦 Features

- AVRCP metadata polling and playback control
- AUX input detection (inferred via AVRCP silence)
- BLE HID consumer control (volume, mute)
- Nextion UI for metadata, EQ, AUX indication
- Robust BLE bond recovery and advertising

## 📁 Project Structure

```
esp32_project/
├── main.py                  # Main control loop
├── utils/
│   └── common.py            # Shared helpers (dprint, formatting)
├── nextion/
│   └── display.py           # Nextion screen interface
├── blehid/
│   └── ble.py               # BLE HID (volume/mute) logic
└── bm83/
    └── bm83.py              # BM83 Bluetooth AVRCP/A2DP interface
```

## 🚀 Deployment Instructions

1. Flash **CircuitPython 10.x** to your ESP32-S3 DevKitC-1.
2. Copy all project files into the mounted `CIRCUITPY` USB drive.
3. Install required libraries:
   - `adafruit_ble`
   - `adafruit_hid`
4. Connect:
   - **BM83** via UART (IO17/IO18)
   - **Nextion** via UART (IO15/IO16)
5. Reset the board. `main.py` will execute and start all services.

## 🧪 Testing

Unit tests live under `tests/` and can be run with `pytest` on compatible platforms.

## 🆘 Troubleshooting

- If BLE doesn't work on iOS, try **Forget Device** and trigger `BT_EBIND`.
- If metadata stops updating, ensure AVRCP is supported by the source device.
- If CircuitPython auto-reloads on file save, it's disabled in code.

## Open investigations (keep issues open)

- **#35 Hard crash after EQ/power interactions** – crash observed while cycling EQ presets and power events; awaiting on-device confirmation of any fix before closure.
- **#37 E-BIND button crash with BLE pairing** – crash seen when pressing E-BIND with repeated AVRCP metadata requests and BLE pairing attempts; will remain open until validated on hardware.

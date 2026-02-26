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

Deployment is intentionally split into two explicit modes:

### 1) Baseline Mode (.py, recommended first)

Use this mode while bringing up new hardware, debugging regressions, or reproducing bugs.

1. Flash **CircuitPython 10.x** to your ESP32-S3 DevKitC-1.
2. Copy all files from `firmware/circuitpython/` into the mounted `CIRCUITPY` USB drive.
3. Install required libraries:
   - `adafruit_ble`
   - `adafruit_hid`
4. Connect:
   - **BM83** via UART (IO17/IO18)
   - **Nextion** via UART (IO15/IO16)
5. **Configure Nextion HMI buttons** - See [NEXTION_SETUP.md](NEXTION_SETUP.md) for press/release event configuration.
6. Reset the board. `main.py` will execute and start all services.

### 2) Optimized Mode (.mpy, production)

Switch to this mode only after baseline `.py` deployment is validated on-device.

1. Build optimized output with `./build_mpy.sh`.
2. Copy the contents of `dist/circuitpython/` to `CIRCUITPY`.
3. Ensure required Adafruit libraries are still present in `CIRCUITPY/lib/`:
   - `adafruit_ble/`
   - `adafruit_hid/`
4. Reset and validate runtime behavior.

**For deployment workflows, rollbacks, and troubleshooting, see [DEPLOYMENT.md](DEPLOYMENT.md).**

### 📦 Building Optimized .mpy Files

The repository includes a `build_mpy.sh` script to compile Python modules into bytecode (`.mpy` files) for improved performance and reduced memory usage on CircuitPython devices.

#### Prerequisites

You need `mpy-cross` installed:

```bash
# Install via pip
pip install mpy-cross

# Or download from CircuitPython releases
# https://github.com/adafruit/circuitpython/releases
```

#### Building with bash (Linux/macOS/Git Bash)

```bash
# Run the build script
./build_mpy.sh

# Output will be in dist/circuitpython/
# ├── main.py           (kept as .py - entry point must not be compiled)
# ├── settings.toml     (config file, if present)
# └── lib/              (compiled modules)
#     ├── bm83/
#     │   ├── __init__.mpy
#     │   └── bm83.mpy
#     ├── nextion/
#     │   ├── __init__.mpy
#     │   └── display.mpy
#     ├── blehid/
#     │   ├── __init__.mpy
#     │   └── ble.mpy
#     └── utils/
#         ├── __init__.mpy
#         └── common.mpy
```

#### Building with WSL (Windows Subsystem for Linux)

```bash
# Open WSL terminal (Ubuntu, Debian, etc.)
cd /mnt/c/path/to/BM83-ESP32-S3-Nextion

# Install mpy-cross if not already installed
pip install mpy-cross

# Run the build script
./build_mpy.sh

# The output in dist/circuitpython/ can be copied to your CIRCUITPY drive
# from Windows Explorer at the WSL path shown after build completes
```

#### Deployment After Build

1. Copy the entire contents of `dist/circuitpython/` to your `CIRCUITPY` drive.
2. Make sure the required Adafruit libraries are present in `CIRCUITPY/lib/`:
   - `adafruit_ble/`
   - `adafruit_hid/`
3. Reset the board.

**Recommended flow**: Always validate first with plain `.py` files from `firmware/circuitpython/`, then switch to compiled `.mpy` artifacts from `dist/circuitpython/` for production.

**Note**: The build script preserves `main.py` as `.py` (CircuitPython entry points cannot be bytecode-compiled). All other modules under `firmware/circuitpython/` are compiled to `.mpy` and placed in `lib/`.

**Important compatibility warning**: The `mpy-cross` version used for compilation must match the CircuitPython firmware version on your device. If you encounter `ValueError: incompatible .mpy file` errors, reinstall `mpy-cross` matching your CircuitPython version.

**Quick rollback (.mpy → .py)**:
1. Delete deployed project folders/files from `CIRCUITPY` (`lib/bm83`, `lib/nextion`, `lib/blehid`, `lib/utils`, and project `main.py` if needed).
2. Re-copy `firmware/circuitpython/*` to `CIRCUITPY`.
3. Reset the board and re-test in baseline `.py` mode.

## 🧪 Testing

Unit tests live under `tests/` and can be run with `pytest` on compatible platforms.

## 📚 Documentation

- **[NEXTION_SETUP.md](NEXTION_SETUP.md)** - Complete guide for configuring Nextion HMI button press/release events
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Firmware deployment and update instructions
- **[CODE_REFERENCE.md](CODE_REFERENCE.md)** - Detailed code reference and API documentation

## 🆘 Troubleshooting

- If BLE doesn't work on iOS, try **Forget Device** and trigger `BT_EBIND`.
- If metadata stops updating, ensure AVRCP is supported by the source device.
- If CircuitPython auto-reloads on file save, it's disabled in code.

### 🔄 Recovery Helper for Lost Branches

If you lose feature branches but still have a local clone, use `scripts/recover_git_candidates.sh` to scan reflog and dangling objects for recoverable commit SHAs and optionally create rescue branches.

```bash
# Show likely candidates
./scripts/recover_git_candidates.sh

# Create rescue/auto-* branches for candidates (default prefix)
./scripts/recover_git_candidates.sh --create-branches

# Or use a custom prefix, e.g. rescue/* instead of rescue/auto-*
./scripts/recover_git_candidates.sh --create-branches --branch-prefix rescue/
```

This is especially useful when your board still runs (`main.py` + `lib/*.mpy`) but you've deleted your local feature branches.

## 🐛 Known Issues & Current Investigations

### Active Issues

- **#37 E-BIND button crash with BLE pairing** – Hard crash observed when pressing E-BIND button during active BLE pairing attempts combined with repeated AVRCP metadata requests. The crash appears to be related to memory exhaustion ("Nimble out of memory") when BLE operations overlap with intensive BM83 UART traffic.
  
  **Symptoms**:
  - Device freezes when BM83 is powered on while BLE HID is connected
  - Hard crash when E-BIND button is pressed during metadata polling
  - CircuitPython connection lost (Thonny shows "PROBLEM IN THONNY'S BACK-END: Exception while handling 'Run' (ConnectionError: EOF)")
  
  **Possible Implementations to Fix**:
  1. **Rate Limiting for AVRCP Requests**: Add throttling to reduce metadata request frequency during BLE operations
     - Implement minimum time between AVRCP requests (e.g., 500ms)
     - Skip metadata requests if BLE operations are in progress
  
  2. **Memory Management for BLE Operations**: Improve memory allocation handling
     - Add explicit `gc.collect()` calls before BLE operations (advertising, pairing)
     - Reduce buffer sizes for UART operations during BLE activity
     - Implement backoff strategy for BLE reconnection attempts
  
  3. **Debouncing and Button Handling**: Prevent rapid-fire button events
     - Increase debounce delay for E-BIND button to reduce event frequency
     - Disable E-BIND during active BLE pairing attempts
     - Add state machine to prevent overlapping BLE operations
  
  4. **Async Operation Coordination**: Better synchronization between BLE and UART
     - Add semaphore/flag to indicate active BLE operation
     - Queue BM83 commands when BLE is busy instead of sending immediately
     - Implement timeout and recovery for stuck operations
  
  5. **Error Recovery**: Add fault tolerance for memory exhaustion
     - Catch and handle BLE "out of memory" errors gracefully
     - Implement soft reset mechanism instead of hard crash
     - Add watchdog timer to detect and recover from freezes

### Previously Resolved (Monitoring for Regression)

- **#35 Hard crash after EQ/power interactions** – Crash observed while cycling EQ presets and power events. Issue was addressed but monitoring continues for regression. If the crash reappears during EQ cycling or power state transitions, it may be related to the same memory management issues as #37.
  
  **Status**: Closed, awaiting on-device validation of stability over extended use.

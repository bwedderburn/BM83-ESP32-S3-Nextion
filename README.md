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
firmware/circuitpython/
├── main.py                  # Main control loop (entry point)
├── blehid/
│   └── ble.py               # BLE HID (volume/mute) logic
├── bm83/
│   └── bm83.py              # BM83 Bluetooth AVRCP/A2DP interface
├── nextion/
│   └── display.py           # Nextion screen interface
└── utils/
    ├── common.py            # Shared helpers (dprint, formatting)
    └── compat.py            # Compatibility helpers

dist/circuitpython/
├── main.py                  # Optimized deployment entry point (.py)
└── lib/                     # Compiled project modules (.mpy)
```

**Source of truth:** Pin assignments are defined in `firmware/circuitpython/main.py`.

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
   - **BM83** via UART (`IO17` / `IO18`)
   - **Nextion** via UART (`IO43` / `IO44`)
5. **Configure Nextion HMI buttons** - See [NEXTION_SETUP.md](NEXTION_SETUP.md) for press/release event configuration.
6. Reset the board. `main.py` will execute and start all services.

### 2) Optimized Mode (.mpy, production)

Switch to this mode only after baseline `.py` deployment is validated on-device.

1. Build optimized output with `./build_mpy.sh`.
2. Copy all contents of `dist/circuitpython/` to the root of `CIRCUITPY` (includes `main.py`, compiled `.mpy` modules in `lib/`, `settings.toml` if present, and any other non-`.py` assets).
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
2. Alternatively, if you only want to update the libraries (and are not copying the whole `dist/circuitpython/` tree), copy `dist/circuitpython/lib/` contents into `CIRCUITPY/lib/`.
3. Make sure the required Adafruit libraries are present in `CIRCUITPY/lib/`:
   - `adafruit_ble/`
   - `adafruit_hid/`
4. Reset the board.

**Recommended flow**: Always validate first with plain `.py` files from `firmware/circuitpython/`, then switch to compiled `.mpy` artifacts from `dist/circuitpython/` for production.

**Note**: The build script preserves `main.py` as `.py` (CircuitPython entry points cannot be bytecode-compiled). All other modules under `firmware/circuitpython/` are compiled to `.mpy` and placed in `lib/`.

**Important compatibility warning**: The `mpy-cross` version used for compilation must match the CircuitPython firmware version on your device. If you encounter `ValueError: incompatible .mpy file` errors, reinstall `mpy-cross` matching your CircuitPython version.

**Quick rollback (.mpy → .py)**:
1. Delete deployed project folders/files from `CIRCUITPY` (`lib/bm83`, `lib/nextion`, `lib/blehid`, `lib/utils`, and project `main.py` if needed).
2. Re-copy `firmware/circuitpython/*` to `CIRCUITPY`.
3. Reset the board and re-test in baseline `.py` mode.

## 🧪 Testing

Host tests live under `tests/` and can be run with `pytest` on compatible platforms.

### Test categories

| Category | Scope | File(s) |
| --- | --- | --- |
| Core unit tests | Core host-simulatable logic and regressions | `tests/test_*.py` (excluding specialized suites below) |
| Parser stress tests | Noisy/fragmented parser burst behavior | `tests/test_parser_stress.py` |
| Host artifact parity | Verifies generated host artifacts match expected outputs | `tests/test_host_artifact_parity.py` |
| Optional `.mpy` build checks | Verifies `.mpy` build flow when explicitly enabled | `tests/test_mpy_build.py` with `RUN_MPY_TESTS=1` |

### Example commands

```bash
# Normal CI-like host run
pytest -q

# Optional .mpy verification run (requires mpy-cross)
RUN_MPY_TESTS=1 pytest -q tests/test_mpy_build.py

# Full run including optional .mpy checks
RUN_MPY_TESTS=1 pytest -q
```

Hardware behavior is only partially covered by host tests; see [docs/hardware-test-limitations.md](docs/hardware-test-limitations.md) for details.

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

### Implemented safeguards

The mitigations below are already in code and should be treated as current protections (not open work items):

- **BLE operation gating + retry/backoff hardening** in `firmware/circuitpython/blehid/ble.py`.
  - Critical-section windows gate overlapping heavy BLE operations.
  - Pairing/advertising/erase paths use retry accounting and bounded backoff.
  - E-BIND handling is deferred/throttled (`request_erase_bonds`) to avoid re-entrant erase flow.

- **Metadata scheduling guard during BLE-critical windows** in `firmware/circuitpython/main.py`.
  - `schedule_attrs_with_ble_guard(...)` delays AVRCP attribute requests when BLE is in a critical section.
  - Main loop also reduces AVRCP polling aggressiveness while BLE critical activity is active.

- **Parser/queue protection against burst/noise traffic** in:
  - `firmware/circuitpython/nextion/display.py` (queue cap, token dedupe/throttle, burst limits), and
  - `firmware/circuitpython/bm83/bm83.py` (RX buffer ceiling/overflow reset, poll burst limiting, request throttles).

### Active Issues

- **#37 Residual instability under worst-case BLE + AVRCP contention**
  - Status: **Open** (risk reduced by current safeguards, but not fully eliminated under all hardware/load combinations).
  - Scope: freeze/crash risk when BLE bond-management/pairing work overlaps sustained BM83 traffic and rapid UI events.

  **How to reproduce/observe**:
  - Start with BM83 connected and metadata actively updating.
  - Generate high event load (rapid Nextion presses including repeated `BT_EBIND` while BLE pairing/reconnect is active).
  - Observe serial logs for repeated BLE retry/backoff activity followed by stalled UI updates or watchdog-like freeze symptoms.
  - Mark pass/fail by run length (e.g., no freeze over a defined soak window such as 15-30 minutes under repeated stress).

### Previously Resolved (Monitoring for Regression)

- **#35 Hard crash after EQ/power interactions** – Mitigated in current firmware; retained here only for regression watch.

  **How to reproduce/observe**:
  - Repeatedly cycle EQ and power actions from Nextion while connected/disconnected transitions occur.
  - Confirm no hard crash, no interpreter disconnect, and continued responsiveness of metadata + controls.
  - Treat any recurrence as regression and reopen with captured logs.

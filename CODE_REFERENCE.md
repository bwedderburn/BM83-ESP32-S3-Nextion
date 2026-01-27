# Code Reference - BM83-ESP32-S3-Nextion

## Table of Contents
- [Repository Structure](#repository-structure)
- [Main Application](#main-application)
- [Core Modules](#core-modules)
- [Testing](#testing)
- [Configuration Files](#configuration-files)
- [Documentation & References](#documentation--references)

---

## Repository Structure

```
BM83-ESP32-S3-Nextion/
├── firmware/circuitpython/         # CircuitPython firmware for ESP32-S3
│   ├── main.py                     # Main application entry point
│   ├── settings.toml               # CircuitPython configuration
│   ├── bm83/                       # BM83 Bluetooth module interface
│   │   ├── __init__.py             # Module exports (Bm83, EQ constants)
│   │   └── bm83.py                 # BM83 UART protocol implementation
│   ├── nextion/                    # Nextion HMI display interface
│   │   ├── __init__.py             # Module exports (Nextion, constants)
│   │   └── display.py              # Nextion UART protocol & UI updates
│   ├── blehid/                     # BLE HID ConsumerControl (volume/mute)
│   │   ├── __init__.py             # Empty module marker
│   │   └── ble.py                  # BLE HID implementation
│   ├── utils/                      # Shared utility functions
│   │   ├── __init__.py             # Module exports (sanitize, fmt_ms, etc.)
│   │   └── common.py               # Text sanitization, time formatting
│   └── lib/                        # CircuitPython libraries (adafruit_ble, etc.)
├── tests/                          # Unit tests (pytest)
│   ├── __init__.py
│   ├── conftest.py                 # Test configuration & fixtures
│   ├── test_avrcp_metadata.py      # AVRCP metadata parsing tests
│   ├── test_blehid.py              # BLE HID basic tests
│   ├── test_blehid_advanced.py     # BLE HID advanced scenarios
│   ├── test_bm83.py                # BM83 module tests
│   ├── test_bm83_uart.py           # BM83 UART protocol tests
│   ├── test_modules.py             # Module import/structure tests
│   ├── test_nextion.py             # Nextion display tests
│   └── test_utils.py               # Utility function tests
├── Documents/                      # Vendor datasheets & reference PDFs
│   ├── AudioUARTCommandSet_v2.09.pdf
│   ├── BM83_Host_MCU_Firmware_Development_Guide_DS50002896A.pdf
│   └── ... (other BM83/Bluetooth references)
├── docs/                           # Project documentation
│   └── index.html                  # Documentation homepage
├── .github/                        # GitHub configuration
│   ├── copilot-instructions.md     # GitHub Copilot instructions
│   └── workflows/                  # CI/CD workflows
│       └── python-package.yml      # Lint & test automation
├── setup.py                        # Python package setup
├── pyproject.toml                  # Project metadata & dependencies
├── pytest.ini                      # pytest configuration
├── README.md                       # Project overview & setup instructions
├── SECURITY.md                     # Security policy
├── LICENSE                         # MIT License
├── coverage.sh                     # Code coverage script
└── deploy.sh                       # Deployment script

```

---

## Main Application

### `firmware/circuitpython/main.py`

**Purpose**: Main entry point and orchestration loop for the ESP32-S3 firmware.

**Key Components**:
- **Hardware Configuration**:
  - Nextion UART: TX=IO15, RX=IO16, Baud=9600
  - BM83 UART: TX=IO17, RX=IO18, Baud=115200
  - BLE HID: Optional volume/mute control

- **Main Loop**:
  - Initializes all hardware interfaces (Nextion, BM83, BLE)
  - Polls BM83 for AVRCP metadata (title, artist, album, position)
  - Updates Nextion display with metadata and EQ status
  - Detects AUX mode via AVRCP silence periods
  - Handles button presses from Nextion (play, pause, next, prev, etc.)
  - Synchronizes BLE HID volume/mute with user interactions

- **Key Functions**:
  - `main()`: Main orchestration loop
  - `flush_page(pageid)`: Updates Nextion display page with current state
  - `maybe_track_changed(pos_ms, total_ms)`: Detects track changes
  - `enter_aux_mode()`: Switches UI to AUX input mode
  - `exit_aux_mode()`: Returns UI to Bluetooth mode

**Dependencies**:
```python
from utils.common import dprint, _fmt_ms, _sanitize_text
from nextion.display import Nextion, NX_RUNTIME, EQ_OBJ_PAGE0, EQ_OBJ_PAGE1, AUX_OBJ_PAGE1
from blehid.ble import BleHid
from bm83.bm83 import Bm83
```

---

## Core Modules

### BM83 Module (`firmware/circuitpython/bm83/`)

#### `bm83/__init__.py`
**Exports**: `Bm83`, `EQ_OFF`, `EQ_USER`, `EQ_LABELS`, `EQ_SEQ`

Provides package-level exports for the BM83 module, including EQ constants used throughout the codebase.

#### `bm83/bm83.py`
**Purpose**: BM83 Bluetooth module interface over UART.

**Class**: `Bm83`

**Key Features**:
- Binary UART protocol with framing and checksums
- AVRCP metadata (title, artist, album, position, duration) via async updates
- Playback control (play/pause toggle, next, prev, stop)
- Volume control and mute
- EQ mode management (OFF, ROCK, POP, JAZZ, etc.)
- Event notifications (pairing, connection, power state)

**Key Methods**:
- `send(op, params)`: Sends UART command with framing
- `poll(max_read=768)`: Reads and parses incoming BM83 events
- `avrcp_get_element_attributes(db=0)`: Request AVRCP metadata; parsed metadata is updated asynchronously from `poll()` events
- `play_pause()`, `next()`, `prev()`: Playback control (toggle play/pause, skip forward/backward)
- `next_eq()`: Cycle to the next EQ preset and return the new mode index

**EQ Constants**:
```python
EQ_OFF = 0
EQ_LABELS = {0: "OFF", 1: "SOFT", 2: "BASS", 3: "TREBLE", 4: "CLASSICAL",
             5: "ROCK", 6: "JAZZ", 7: "POP", 8: "DANCE", 9: "RNB", 11: "USER"}
EQ_SEQ = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11)  # Cycle order
```

---

### Nextion Module (`firmware/circuitpython/nextion/`)

#### `nextion/__init__.py`
**Exports**: `Nextion`, `TERM`, `TOKENS`, `TOK_BT`, `TOK_EQ`, `EQ_MAP`, `ascii_upper_uscore`, `NX_RUNTIME`, `EQ_OBJ_PAGE0`, `EQ_OBJ_PAGE1`, `AUX_OBJ_PAGE1`

Package-level exports for Nextion display components.

#### `nextion/display.py`
**Purpose**: Nextion HMI display interface over UART.

**Class**: `Nextion`

**Key Features**:
- ASCII UART protocol with `0xFF 0xFF 0xFF` terminators
- Button press event parsing (BT_PLAY, BT_NEXT, BT_EQ, etc.)
- Text field updates with sanitization
- Command queue for non-blocking UI updates
- Page synchronization and boot sequence
- `sendme` polling for consistent UI state

**Key Methods**:
- `boot_sync(delay_s)`: Waits for Nextion to boot and synchronizes
- `read(max_tokens=6, debounce_s=0.10)`: Reads and parses button press tokens; returns `(tokens, page_changed)`
- `enqueue(cmd)`: Queues a command string to be sent to the display
- `set_text_active_page(obj_name, text)`: Updates text field on current page (queues sanitized command)
- `tick()`: Non-blocking processing; sends queued commands to the display
- `current_page` (attribute): Current page ID

**UI Object IDs**:
```python
EQ_OBJ_PAGE0 = "tEQ0"  # EQ label on page 0
EQ_OBJ_PAGE1 = "tEQ1"  # EQ label on page 1
AUX_OBJ_PAGE1 = "tAUX1"  # AUX indicator on page 1
NX_RUNTIME = {
    "title": "tTitle",
    "artist": "tArtist",
    "album": "tAlbum",
    "genre": "tGenre",
    "time_cur": "tTIME_CUR",
    "time": "tTime",
    "track_num": "tTrack_num",
    "total_tracks": "tTotalTracks"
}
```

**Button Tokens**:
```python
TOKENS = {
    b"BT_POWER", b"BT_POWEROFF", b"BT_PAIR", b"BT_PLAY", b"BT_PREV",
    b"BT_NEXT", b"BT_EQ", b"BT_VOLUP", b"BT_VOLDN", b"BT_EBIND"
}
```

---

### BLE HID Module (`firmware/circuitpython/blehid/`)

#### `blehid/__init__.py`
Empty module marker (no exports).

#### `blehid/ble.py`
**Purpose**: BLE HID ConsumerControl for volume/mute on iOS/macOS.

**Class**: `BleHid`

**Key Features**:
- BLE HID profile with ConsumerControl service
- Volume up/down/mute HID reports
- Bond management (erase, recovery)
- Advertisement and pairing handling
- Persistent connections

**Key Methods**:
- `setup()`: Initializes BLE and starts advertising
- `volume(up: bool)`: Sends volume up (`True`) or volume down (`False`) HID report
- `mute()`: Sends mute toggle HID report
- `erase_bonds()`: Clears paired devices
- `start_advertising()`: Begins BLE advertisement

---

### Utils Module (`firmware/circuitpython/utils/`)

#### `utils/__init__.py`
**Exports**: `hexdump`, `sanitize_text`, `fmt_ms`, `_sanitize_text`, `_fmt_ms`, `dprint`

Package-level exports for utility functions.

#### `utils/common.py`
**Purpose**: Shared utility functions for text processing and debugging.

**Key Functions**:

**`dprint(*a)`**  
Debug print wrapper (controlled by `DEBUG` flag).

**`_sanitize_text(txt, max_len=48)`**  
Sanitizes text for Nextion display:
- Replaces non-ASCII/control characters with spaces
- Escapes double quotes to single quotes
- Truncates to `max_len` with ellipsis (…)
- Returns "—" for None/empty strings

**`sanitize_text(txt, max_len=48)`**  
Public alias for `_sanitize_text()`.

**`_fmt_ms(ms)`**  
Formats milliseconds as time string:
- Returns "M:SS" for times < 1 hour
- Returns "H:MM:SS" for times ≥ 1 hour
- Returns "—" for None/invalid values

**`fmt_ms(ms)`**  
Public alias for `_fmt_ms()`.

**`hexdump(data, prefix="")`**  
Prints hexadecimal dump of byte data for debugging.

---

## Testing

### Test Suite (`tests/`)

All tests use `pytest` and can be run in a standard Python environment (not CircuitPython).

**Test Files**:

- **`test_modules.py`**: Verifies module imports and structure
- **`test_bm83.py`**: Tests BM83 class methods, EQ logic, and event handling
- **`test_bm83_uart.py`**: Tests BM83 UART protocol framing and parsing
- **`test_avrcp_metadata.py`**: Tests AVRCP metadata extraction and parsing
- **`test_nextion.py`**: Tests Nextion display class and token parsing
- **`test_blehid.py`**: Tests BLE HID basic functionality
- **`test_blehid_advanced.py`**: Tests BLE HID advanced scenarios
- **`test_utils.py`**: Tests utility functions (`sanitize_text`, `fmt_ms`, etc.)

**Running Tests**:
```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_bm83.py

# Run with coverage
pytest --cov=firmware/circuitpython
```

**Test Configuration**:
- `pytest.ini`: pytest configuration (test paths, options)
- `conftest.py`: Shared fixtures and test utilities

---

## Configuration Files

### `firmware/circuitpython/settings.toml`
CircuitPython configuration file for environment variables and settings.

### `pyproject.toml`
Python project metadata and build configuration:
- Project name, version, description
- Dependencies and development dependencies
- Build system configuration

### `setup.py`
Alternative Python package setup configuration:
```python
setup(
    name="esp32-audio-remote",
    version="1.0.0",
    description="CircuitPython-based audio remote with BM83, BLE HID, and Nextion display",
    packages=find_packages(where="firmware/circuitpython"),
    package_dir={"": "firmware/circuitpython"},
    python_requires=">=3.7",
)
```

### `.github/workflows/python-package.yml`
CI/CD workflow for automated testing:
- Runs on Python 3.9, 3.10, 3.11
- Executes flake8 linting (syntax check + style check)
- Runs pytest test suite

---

## Documentation & References

### Datasheets (`Documents/`)

**BM83 Module References**:
- `AudioUARTCommandSet_v2.09.pdf`: Complete UART command reference
- `BM83_Host_MCU_Firmware_Development_Guide_DS50002896A.pdf`: Firmware development guide
- `AN3118-IS2083-BM83-Bluetooth-Applications-Design-Guide-DS00003118.pdf`: Application design guide
- `BM83 Getting Started Guide.pdf`: Quick start guide
- `AudioUARTCommandSet_Summary_table_V2.09.xlsx`: Command reference table

**Firmware Files**:
- `Bluetooth_Basic_Demo_BM83_EVB.X.MSPK2v1.3.4.hex`: BM83 demo firmware
- `IS208x_UI_1.3.25_Demo_Package_MCU_Mode_SPP_Rehex_0F19.HEX`: BM83 UI firmware

### Project Documentation

- **`README.md`**: Project overview, features, setup instructions, deployment
- **`SECURITY.md`**: Security policy and vulnerability reporting
- **`LICENSE`**: MIT License
- **`docs/index.html`**: Project documentation homepage

---

## Build & Deployment

### Linting
```bash
# Strict pass (syntax errors, undefined names)
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics

# Style pass (warnings only)
flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics
```

### Coverage
```bash
# Run coverage script
./coverage.sh
```

### Deployment
```bash
# Deploy to CircuitPython device
./deploy.sh
```

**Manual Deployment**:
1. Flash CircuitPython 10.x to ESP32-S3 DevKitC-1
2. Copy `firmware/circuitpython/*` to `CIRCUITPY` drive
3. Install required libraries in `lib/`:
   - `adafruit_ble`
   - `adafruit_hid`
4. Connect hardware:
   - BM83 UART: IO17 (TX), IO18 (RX)
   - Nextion UART: IO15 (TX), IO16 (RX)
5. Reset board; `main.py` executes automatically

---

## API Quick Reference

### BM83 AVRCP Metadata
```python
bm = Bm83(uart)

# Request AVRCP metadata from the active device (DB index 0)
bm.avrcp_get_element_attributes(db=0)

# In your main loop, poll for events and parse metadata frames:
for event, params in bm.poll():
    if event == "GEA_0x5D":  # AVRCP Get Element Attributes response
        meta = bm.parse_gea_0x5d(params)
        # meta = {
        #   "title": "Song Title",
        #   "artist": "Artist Name",
        #   "album": "Album Name",
        #   "track_num": "1",
        #   "total_tracks": "10",
        #   "genre": "Rock",
        #   "play_time_ms": 125000,  # Current position
        #   "total_len_ms": 240000   # Total duration
        # }
        break
```

### Nextion Display Updates
```python
nx = Nextion(uart)
nx.set_text_active_page("tTitle", "Song Title")  # Queue update for current page

# Or manually queue commands and process them
nx.enqueue('tTitle.txt="Song Title"')  # Queue custom command
nx.tick()  # Process queued commands (call repeatedly in main loop)
```

### BLE HID Volume Control
```python
ble = BleHid(enabled=True, name="AmpBench Remote")
ble.setup()
ble.volume(True)   # Volume up
ble.volume(False)  # Volume down
ble.mute()
```

### Text Sanitization
```python
from utils.common import sanitize_text, fmt_ms

safe_text = sanitize_text("Artist — Name", max_len=30)
time_str = fmt_ms(125000)  # "02:05"
```

---

## Module Import Paths

All firmware modules are located under `firmware/circuitpython/`:

```python
# Main application
from main import main

# BM83 module
from bm83.bm83 import Bm83
from bm83 import EQ_OFF, EQ_USER, EQ_LABELS, EQ_SEQ

# Nextion module
from nextion.display import Nextion, NX_RUNTIME, EQ_OBJ_PAGE0, EQ_OBJ_PAGE1, AUX_OBJ_PAGE1
from nextion import TERM, TOKENS, TOK_BT, TOK_EQ, EQ_MAP, ascii_upper_uscore

# BLE HID module
from blehid.ble import BleHid

# Utils module
from utils.common import dprint, sanitize_text, fmt_ms, hexdump
from utils import _sanitize_text, _fmt_ms
```

---

## Version Information

- **CircuitPython**: 10.x
- **Python (for tests)**: 3.9, 3.10, 3.11
- **Hardware**: ESP32-S3 DevKitC-1
- **BM83 Firmware**: MSPK2 v1.3.4+
- **Nextion Display**: NX3224F028 (or compatible)

---

*Last Updated: 2026-01-25*

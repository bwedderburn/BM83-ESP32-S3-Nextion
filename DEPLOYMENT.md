# Firmware Deployment Guide

This guide explains how to deploy updated firmware to your ESP32-S3 device.

## When to Update Firmware

You need to update the firmware on your ESP32-S3 when:
- You've pulled latest changes from GitHub
- You're seeing garbage bytes in serial output (e.g., `b'BT_POWERf\x00'` instead of `b'BT_POWER'`)
- You want to use new features or bug fixes

## Quick Update (Recommended)

### Step 1: Connect to Your Device

Connect your ESP32-S3 to your computer via USB. It should appear as a drive named `CIRCUITPY`.

### Step 2: Update the Changed Files

Copy the updated files from your local repository to the `CIRCUITPY` drive:

```bash
# From your repository directory
cp -r firmware/circuitpython/* /path/to/CIRCUITPY/
```

**Important files to update** (if you've made changes):
- `nextion/display.py` - Token parsing fixes (commit 90c0cdb)
- `main.py` - Main application logic
- `bm83/bm83.py` - BM83 module updates
- `blehid/ble.py` - BLE HID updates

### Step 3: Verify the Update

1. Open a serial terminal to view output:
   ```bash
   # Linux/Mac
   screen /dev/ttyACM0 115200
   
   # Or use your preferred serial terminal
   ```

2. Press **Ctrl+D** in the serial terminal (or press the RESET button on the ESP32-S3) to reload the code

3. Check the serial output - if tokens are being cleaned properly, you should see:
   ```
   [NX] Token: b'BT_POWER'      ← Clean token (good!)
   [NX] Token: b'BT_PLAY'       ← Clean token (good!)
   ```
   
   NOT:
   ```
   [NX] Token: b'BT_POWERf\x00'  ← Garbage bytes (old firmware!)
   ```

## Full Deployment (Clean Install)

If you want to do a complete fresh install:

### Step 1: Flash CircuitPython

If you haven't already, flash CircuitPython 10.x to your ESP32-S3 DevKitC-1:
1. Download the appropriate CircuitPython .uf2 file for ESP32-S3
2. Put the board into bootloader mode
3. Copy the .uf2 file to the USB drive that appears

### Step 2: Install Required Libraries

Copy the required CircuitPython libraries to the `lib` folder on your `CIRCUITPY` drive:
- `adafruit_ble`
- `adafruit_hid`

These can be downloaded from the [CircuitPython Library Bundle](https://circuitpython.org/libraries).

### Step 3: Copy Firmware Files

Copy all files from `firmware/circuitpython/` to your `CIRCUITPY` drive:

```bash
cp -r firmware/circuitpython/* /path/to/CIRCUITPY/
```

### Step 4: Verify Installation

1. The board should auto-reset and start running
2. Connect via serial terminal to view output
3. Check that tokens are being parsed correctly (no garbage bytes)

## Troubleshooting

### Still Seeing Garbage Bytes After Update

If you're still seeing tokens like `b'BT_POWERf\x00'` after updating:

1. **Verify the files were copied correctly:**
   ```bash
   # Check the modification time of display.py on the device
   ls -l /path/to/CIRCUITPY/nextion/display.py
   ```
   
2. **Ensure code reloaded:**
   - Press **Ctrl+D** in the serial terminal
   - Or press the **RESET** button on the board
   - Or disconnect/reconnect USB

3. **Check you copied the right version:**
   ```bash
   # On your computer, verify you have the latest code
   cd /path/to/BM83-ESP32-S3-Nextion
   git pull origin copilot/add-nextion-press-release-events
   git log --oneline -3
   ```
   
   You should see commit `90c0cdb` or later with message "Fix token parsing to extract clean tokens without garbage bytes"

4. **Clear any cached bytecode:**
   Sometimes CircuitPython caches compiled code. Delete the `.mpy` files if present:
   ```bash
   # On the CIRCUITPY drive
   rm -rf nextion/__pycache__
   rm nextion/*.mpy
   ```

### Buttons Still Don't Work

If tokens are clean (`b'BT_POWER'`) but buttons don't trigger actions:

1. **Check BLE pairing** (for volume buttons):
   - Ensure ESP32-S3 is paired with your device
   - Look for `[BLE] Connected` and `[BLE] Paired/encrypted` in serial output
   - Volume buttons require BLE HID connection

2. **Check token allowlist:**
   - Verify your tokens are in `TOKENS` set in `nextion/display.py`
   - For volume: `BT_VOLUP_P`, `BT_VOLUP_R`, `BT_VOLDN_P`, `BT_VOLDN_R`

3. **Check Nextion configuration:**
   - Verify Touch Press and Touch Release events are configured
   - Use `print "TOKEN"` commands (not `printh`)

### Board Won't Start After Update

If the board shows errors or won't start:

1. **Check serial output for errors:**
   Connect via serial terminal and look for Python tracebacks

2. **Verify file integrity:**
   Ensure all files copied completely (no truncated files)

3. **Test with known-good code:**
   Copy files from a known-working commit

4. **Factory reset:**
   - Reflash CircuitPython
   - Redeploy from scratch following "Full Deployment" steps

## Quick Reference

### File Locations on Device

```
CIRCUITPY/
├── main.py              # Main entry point
├── settings.toml        # Configuration
├── lib/                 # CircuitPython libraries
│   ├── adafruit_ble/
│   └── adafruit_hid/
├── nextion/
│   ├── __init__.py
│   └── display.py       # ← TOKEN PARSING FIX HERE
├── bm83/
│   ├── __init__.py
│   └── bm83.py
├── blehid/
│   ├── __init__.py
│   └── ble.py
└── utils/
    ├── __init__.py
    └── common.py
```

### Serial Terminal Commands

**Reload code without hardware reset:**
```
Ctrl+D
```

**Stop execution:**
```
Ctrl+C
```

**Access REPL:**
```
Ctrl+C (twice if code is running)
```

## Related Documentation

- [README.md](README.md) - Project overview and setup
- [NEXTION_SETUP.md](NEXTION_SETUP.md) - Nextion button configuration
- [CODE_REFERENCE.md](CODE_REFERENCE.md) - Code structure and API reference

---

**Last Updated**: 2026-01-28

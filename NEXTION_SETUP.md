# Nextion HMI Setup Guide - Press and Release Events

This guide explains how to configure your Nextion HMI display to send press and release events for volume controls (and other buttons) that work with the ESP32-S3 firmware.

## Quick Start

**For volume buttons, configure TWO events in Nextion Editor:**

1. **Touch Press Event**: `print "BT_VOLUP_P"` (for volume up) or `print "BT_VOLDN_P"` (for volume down)
2. **Touch Release Event**: `print "BT_VOLUP_R"` (for volume up) or `print "BT_VOLDN_R"` (for volume down)

**For other buttons** (Play, Next, Prev, EQ, etc.): Just one Touch Press Event with `print "TOKEN"` (e.g., `print "BT_PLAY"`)

**Common Issue**: If tokens are received but volume doesn't change, ensure BLE HID is enabled, paired, and connected to your device.

---

## Overview

The firmware uses **press (`_P`) and release (`_R`) event tokens** for volume buttons to support hold-and-repeat functionality. When you press and hold a volume button, it:
1. Sends an immediate volume change on button press (`_P`)
2. After 500ms, begins repeating volume commands every 80ms
3. Stops when you release the button (`_R`)

## Required Nextion Button Configuration

For each button that needs press/release events (especially volume up and volume down), you must configure **two separate events** in the Nextion Editor:

### 1. Touch Press Event

**When to trigger**: When the button is first pressed down

**Where to configure**: In the Nextion Editor, select your button component, go to the **Event** tab

**Event**: `Touch Press Event`

**Command to send**:
```
print "TOKEN_NAME"
```

Replace `TOKEN_NAME` with the actual token. For the volume buttons:

- **Volume Up Press**: `print "BT_VOLUP_P"`
- **Volume Down Press**: `print "BT_VOLDN_P"`

### 2. Touch Release Event

**When to trigger**: When the button is released

**Where to configure**: Same button component, **Event** tab

**Event**: `Touch Release Event`

**Command to send**:
```
print "TOKEN_NAME"
```

Replace `TOKEN_NAME` with the actual token. For the volume buttons:

- **Volume Up Release**: `print "BT_VOLUP_R"`
- **Volume Down Release**: `print "BT_VOLDN_R"`

---

## Complete Examples

### Volume Up Button

**Touch Press Event**:
```
print "BT_VOLUP_P"
```
This sends the token `BT_VOLUP_P` followed by the Nextion terminator (`FF FF FF`)

**Touch Release Event**:
```
print "BT_VOLUP_R"
```
This sends the token `BT_VOLUP_R` followed by the Nextion terminator (`FF FF FF`)

### Volume Down Button

**Touch Press Event**:
```
print "BT_VOLDN_P"
```
This sends the token `BT_VOLDN_P` followed by the Nextion terminator (`FF FF FF`)

**Touch Release Event**:
```
print "BT_VOLDN_R"
```
This sends the token `BT_VOLDN_R` followed by the Nextion terminator (`FF FF FF`)

**Note**: The Nextion `print` command automatically appends the `FF FF FF` terminator bytes. You do NOT need to manually add them.

---

## ⚠️ IMPORTANT: Do NOT Add Manual Terminators

**The `print` command automatically terminates - DO NOT add `printh FF FF FF` after it!**

### ❌ WRONG - Double Termination (Don't do this!)
```
print "BT_VOLUP_P"
printh FF FF FF      ← WRONG! This adds a second set of terminators
```

This will send: `BT_VOLUP_P + FF FF FF + FF FF FF` which could cause parsing issues or empty frames.

### ✅ CORRECT - Let print Handle Termination
```
print "BT_VOLUP_P"
```

This automatically sends: `BT_VOLUP_P + FF FF FF`

### Why This Matters

The Nextion `print` command is specifically designed to send ASCII text followed by the standard protocol terminator. If you add `printh FF FF FF` manually:
1. You create a double terminator sequence
2. The parser might interpret the second `FF FF FF` as an empty frame
3. This wastes bandwidth and could cause timing issues

**If you see examples online showing both `print` and `printh FF FF FF` together, they are incorrect or outdated.**

---

## Understanding the Nextion `print` Command

The Nextion `print` command sends ASCII text over UART followed by the standard Nextion terminator bytes (`FF FF FF`) **automatically**.

**Format**:
```
print "TOKEN_NAME"
```

**What gets sent over UART**:
```
TOKEN_NAME + FF FF FF
```

**IMPORTANT:** The terminator is added automatically by the `print` command. You do NOT need to add it manually with `printh FF FF FF`.

The ESP32-S3 firmware receives these bytes and:
1. Looks for the `FF FF FF` terminator to identify frame boundaries
2. Extracts the token name (e.g., `BT_VOLUP_P`)
3. Validates it against the allowlist in `TOKENS`
4. Passes it to the main loop for handling

**Example** for `print "BT_VOLUP_P"`:
- Bytes sent: `42 54 5F 56 4F 4C 55 50 5F 50 FF FF FF`
  - `42 54 5F 56 4F 4C 55 50 5F 50` = ASCII for "BT_VOLUP_P"
  - `FF FF FF` = Nextion terminator (added automatically by `print`)

**Comparison with `printh`:**
- `print "TEXT"` → sends ASCII TEXT + automatic `FF FF FF` terminator
- `printh 42 54` → sends raw hex bytes `42 54` with NO automatic terminator
- `printh FF FF FF` → sends only the terminator bytes (useful for manual protocols)

---

## Quick Reference: All Supported Tokens

The firmware recognizes these button tokens. For hold-and-repeat functionality, use the `_P` and `_R` variants:

### Volume Controls (with Press/Release)
| Button | Press Token | Release Token |
|--------|-------------|---------------|
| Volume Up | `BT_VOLUP_P` | `BT_VOLUP_R` |
| Volume Down | `BT_VOLDN_P` | `BT_VOLDN_R` |

### Legacy Volume Controls (single event, no hold-and-repeat)
| Button | Token |
|--------|-------|
| Volume Up | `BT_VOLUP` |
| Volume Down | `BT_VOLDN` |

### Other Control Buttons (single Touch Press Event only)

For these buttons, configure only the **Touch Press Event** with `print "TOKEN"`. No release event is needed.

**Example for Play/Pause button**:
- Touch Press Event: `print "BT_PLAY"`

| Button | Token | Function |
|--------|-------|----------|
| Power | `BT_POWER` | Toggle power on/off |
| Power Off | `BT_POWEROFF` | Force power off |
| Pair | `BT_PAIR` | Enter pairing mode |
| Play/Pause | `BT_PLAY` | Toggle playback |
| Previous | `BT_PREV` | Previous track |
| Next | `BT_NEXT` | Next track |
| EQ | `BT_EQ` | Cycle EQ preset |
| Erase Bonds | `BT_EBIND` | Erase BLE pairings |

### EQ Selection Tokens
`EQ_OFF`, `EQ_SOFT`, `EQ_BASS`, `EQ_TREBLE`, `EQ_CLASSICAL`, `EQ_ROCK`, `EQ_JAZZ`, `EQ_POP`, `EQ_DANCE`, `EQ_RNB`, `EQ_USER`

---

## Token Format Rules

For a token to be recognized by the firmware:
1. Must use **UPPERCASE letters, digits, and underscores only**
2. Must be in the allowlist (see `TOK_BT` and `TOK_EQ` in `firmware/circuitpython/nextion/display.py`)
3. Must be sent using Nextion's `print "TOKEN"` command (which automatically adds `FF FF FF` terminator)

---

## Testing Your Configuration

After configuring your Nextion buttons:

1. **Upload the Nextion HMI file** to your display
2. **Connect to the ESP32-S3** and monitor the serial output
3. **Press and hold a volume button** - you should see:
   - Immediate volume change on press
   - Repeated volume changes after 500ms (every 80ms while holding)
   - Stop when released
4. **Check the debug output** - if debug printing is enabled, you'll see clean token reception messages like:
   ```
   [NX] Token: b'BT_VOLUP_P'
   [NX] Token: b'BT_VOLUP_R'
   ```

**Note**: In firmware versions prior to 2026-01-28, tokens may have appeared with garbage bytes like `b'BT_VOLUP_Pf\x00'`. This has been fixed - tokens are now properly cleaned before processing.

---

## Troubleshooting

### Button doesn't respond
- Verify the `print "TOKEN"` command syntax is correct (include the quotes!)
- Check that the token is in the firmware's allowlist (`TOK_BT` in `display.py`)
- Ensure UART baud rate is 9600 for Nextion communication
- Check the serial debug output to see if the token is being received

### Should I add `printh FF FF FF` after `print "TOKEN"`?
**NO!** This is a common misconception. The `print` command automatically appends `FF FF FF` terminators. Adding `printh FF FF FF` creates double terminators which could cause:
- Empty frame parsing
- Token detection issues
- Wasted UART bandwidth

**Correct:** `print "BT_VOLUP_P"` (terminator added automatically)  
**Wrong:** `print "BT_VOLUP_P"` followed by `printh FF FF FF`

If you see examples elsewhere showing both commands together, they are incorrect.

### Tokens appear with garbage bytes (e.g., `b'BT_VOLUP_Pf\x00'`)

**This means you're running old firmware!** The token cleaning fix was added in firmware builds after 2026-01-28.

**Solution:** Update your ESP32-S3 firmware:
1. Pull the latest code from GitHub
2. Copy `firmware/circuitpython/nextion/display.py` to your `CIRCUITPY` drive
3. Press **Ctrl+D** in serial terminal or press RESET button to reload
4. Verify you now see clean tokens: `b'BT_POWER'` instead of `b'BT_POWERf\x00'`

**See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed firmware update instructions.**

### Token is received but volume doesn't change
This is usually a **BLE HID** issue, not a Nextion issue:
- **Ensure BLE is enabled and connected** to your device (iOS, macOS, etc.)
- Check that the ESP32-S3 is paired with your audio device
- Some devices may not support BLE HID volume control
- Try the volume buttons on a known-working BLE HID device to confirm compatibility
- Check the serial output for BLE-related error messages

### Volume doesn't repeat when held
- Verify BOTH press (`_P`) and release (`_R`) events are configured
- Check that Touch Release Event is actually firing (test by adding a debug `print "RELEASE_TEST"` command)
- Some Nextion components may need specific settings to trigger release events properly
- Ensure the button component is set to "Press" or "Touch" mode, not "Click" mode

### Volume keeps repeating after release
- Ensure Touch Release Event is properly configured and sending
- Check UART connection stability
- The firmware has a 2-second safety timeout that will stop repeating automatically
- This could indicate that release tokens are being throttled (150ms window) - try adding a small delay before release

---

## Alternative: Using `printh` for Custom Protocols

**Note**: For standard button tokens, use the simple `print "TOKEN"` command shown above. The `printh` method is only needed if you want to send binary data, non-ASCII sequences, or implement a custom protocol that requires precise byte control.

The `print` command handles ASCII strings and automatically adds terminators. If you need to send raw bytes (e.g., for binary protocols or special control sequences), use `printh`:

**Example** - Sending a custom binary sequence:
```
printh 01 02 03 FF FF FF
```

**Example** - Sending the same token as `print "BT_VOLUP_P"` using `printh`:
```
printh 42 54 5F 56 4F 4C 55 50 5F 50 FF FF FF
```
Where `42 54 5F 56 4F 4C 55 50 5F 50` is the ASCII hex for "BT_VOLUP_P" and `FF FF FF` is the terminator.

But again, **this is unnecessary for standard tokens** - just use `print "BT_VOLUP_P"` which is simpler and does the same thing. The `printh` approach is only useful if you need to send non-printable bytes or construct complex binary protocols.

---

## Related Files

- `firmware/circuitpython/nextion/display.py` - Token allowlist and parsing logic
- `firmware/circuitpython/main.py` - Press/release event handlers and hold-and-repeat logic
- `CODE_REFERENCE.md` - Complete code reference documentation

---

**Last Updated**: 2026-01-28

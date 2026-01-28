# Nextion HMI Setup Guide - Press and Release Events

This guide explains how to configure your Nextion HMI display to send press and release events for volume controls (and other buttons) that work with the ESP32-S3 firmware.

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

## Understanding the Nextion `print` Command

The Nextion `print` command sends ASCII text over UART followed by the standard Nextion terminator bytes (`FF FF FF`).

**Format**:
```
print "TOKEN_NAME"
```

**What gets sent over UART**:
```
TOKEN_NAME + FF FF FF
```

The ESP32-S3 firmware receives these bytes and:
1. Looks for the `FF FF FF` terminator to identify frame boundaries
2. Extracts the token name (e.g., `BT_VOLUP_P`)
3. Validates it against the allowlist in `TOKENS`
4. Passes it to the main loop for handling

**Example** for `print "BT_VOLUP_P"`:
- Bytes sent: `42 54 5F 56 4F 4C 55 50 5F 50 FF FF FF`
  - `42 54 5F 56 4F 4C 55 50 5F 50` = ASCII for "BT_VOLUP_P"
  - `FF FF FF` = Nextion terminator (added automatically)

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
4. **Check the debug output** - if debug printing is enabled, you'll see token reception messages

---

## Troubleshooting

### Button doesn't respond
- Verify the `print "TOKEN"` command syntax is correct (include the quotes!)
- Check that the token is in the firmware's allowlist (`TOK_BT` in `display.py`)
- Ensure UART baud rate is 9600 for Nextion communication
- Check the serial debug output to see if the token is being received

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

**Note**: For standard button tokens, use the simple `print "TOKEN"` command shown above. The `printh` method is only needed if you want to send custom byte sequences or implement a different protocol.

If you need to send custom tokens with additional protocol bytes, you can use `printh` to send hex bytes:

```
printh FF FF FF
```

This sends the three bytes `FF FF FF` (the Nextion terminator). For ASCII text tokens, you'd need to convert each character to hex:

**Example** to send "BT_VOLUP_P" with `printh`:
```
printh 42 54 5F 56 4F 4C 55 50 5F 50 FF FF FF
```

But again, **this is unnecessary** - just use `print "BT_VOLUP_P"` which is simpler and does the same thing.

---

## Related Files

- `firmware/circuitpython/nextion/display.py` - Token allowlist and parsing logic
- `firmware/circuitpython/main.py` - Press/release event handlers and hold-and-repeat logic
- `CODE_REFERENCE.md` - Complete code reference documentation

---

**Last Updated**: 2026-01-28

# Nextion HMI Setup Guide - Press and Release Events

This guide explains how to configure your Nextion HMI display to send press and release events for volume controls (and other buttons) that work with the ESP32-S3 firmware.

## Quick Start

**For volume buttons, configure TWO events in Nextion Editor:**

1. **Touch Press Event**: `print "BT_VOLUP_P"` (for volume up) or `print "BT_VOLDN_P"` (for volume down)
2. **Touch Release Event**: `print "BT_VOLUP_R"` (for volume up) or `print "BT_VOLDN_R"` (for volume down)

**For other buttons** (Play, Next, Prev, EQ, etc.): Just one Touch Press Event with `print "TOKEN"` (for example, `BT_PLAY`)

For every custom token above, add `printh FF FF FF` on the next line in the same event. Use one delimiter per token.

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
printh FF FF FF
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
printh FF FF FF
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
printh FF FF FF
```
This sends the token `BT_VOLUP_P` followed by the Nextion terminator (`FF FF FF`)

**Touch Release Event**:
```
print "BT_VOLUP_R"
printh FF FF FF
```
This sends the token `BT_VOLUP_R` followed by the Nextion terminator (`FF FF FF`)

### Volume Down Button

**Touch Press Event**:
```
print "BT_VOLDN_P"
printh FF FF FF
```
This sends the token `BT_VOLDN_P` followed by the Nextion terminator (`FF FF FF`)

**Touch Release Event**:
```
print "BT_VOLDN_R"
printh FF FF FF
```
This sends the token `BT_VOLDN_R` followed by the Nextion terminator (`FF FF FF`)

---

## Understanding the Nextion `print` Command

Nextion's [instruction set](https://nextion.ca/nis/) distinguishes raw UART output from native Return Data. `print "TOKEN_NAME"` sends only the text bytes. The following `printh FF FF FF` sends exactly three `0xFF` bytes, which the ESP32-S3 receiver uses to separate custom button tokens.

For example, the two commands in the Volume Up press event send:

- `42 54 5F 56 4F 4C 55 50 5F 50`: ASCII for `BT_VOLUP_P`
- `FF FF FF`: frame terminator added by `printh`

Native replies such as the `sendme` page return and serial `get` responses already have their own framing. Do not append a terminator to those replies. A native reply can sometimes close an unfinished custom token frame, making a missing terminator look intermittent. Two unterminated button tokens can also run together and be dropped.

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

For these buttons, configure only the **Touch Press Event**. No release event is needed.

**Example for Play/Pause button**:
```
print "BT_PLAY"
printh FF FF FF
```

| Button | Token | Function |
|--------|-------|----------|
| Power | `BT_POWER` | Toggle power on/off |
| Power Off | `BT_POWEROFF` | Force power off |
| Pair | `BT_PAIR` | Enter pairing mode |
| Play/Pause | `BT_PLAY` | Toggle playback |
| Previous | `BT_PREV` | Previous track |
| Next | `BT_NEXT` | Next track |
| EQ | `BT_EQ` | Cycle EQ preset |
| Erase Bonds | `BT_EBIND` | Legacy runtime: erase BLE pairings. Under host-policy ownership, show CrowPanel Volume hosts > Disconnect > select host > Forget guidance |

### EQ Selection Tokens
`EQ_OFF`, `EQ_SOFT`, `EQ_BASS`, `EQ_TREBLE`, `EQ_CLASSICAL`, `EQ_ROCK`, `EQ_JAZZ`, `EQ_POP`, `EQ_DANCE`, `EQ_RNB`, `EQ_USER`

---

## Token Format Rules

For a token to be recognized by the firmware:
1. Must use **UPPERCASE letters, digits, and underscores only**
2. Must be in the allowlist (see `TOK_BT` and `TOK_EQ` in `firmware/circuitpython/lib/nextion/display.py`)
3. Send the ASCII token followed by exactly one `FF FF FF` delimiter.

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

In a UART capture or the Nextion Editor debugger, verify that both press and release tokens end with their own three `FF` bytes. A quick tap should produce two separate frames even when no page reply occurs between them.

---

## Troubleshooting

### Button doesn't respond
- Verify the `print "TOKEN"` syntax and the following `printh FF FF FF` in the same event.
- Check that the token is in the firmware's allowlist (`TOK_BT` or `TOK_EQ` in `display.py`).
- Ensure UART baud rate is 9600 for Nextion communication.
- Check serial debug output to see if the token is received.

### Should I add `printh FF FF FF` after `print "TOKEN"`?
Yes. Add it once to each custom token event. `print` sends no delimiter.

### Tokens show unexpected bytes (e.g., `b'BT_VOLUP_Pf\x00'`)
Check the raw UART bytes before changing firmware. A trailing `66 00` is a page-0 reply; seeing it directly after token text with no intervening delimiter can indicate that the event omitted `printh FF FF FF`. Verify the event's own frame first.

### Token is received but volume doesn't change
This is usually a **BLE HID** issue, not a Nextion issue:
- **Ensure BLE is enabled and connected** to your device (iOS, macOS, etc.)
- Check that the ESP32-S3 is paired with your audio device
- Some devices may not support BLE HID volume control
- Try the volume buttons on a known-working BLE HID device to confirm compatibility
- Check the serial output for BLE-related error messages

### Volume doesn't repeat when held
- Verify BOTH press (`_P`) and release (`_R`) events are configured
- Check that Touch Release Event is firing by looking for the framed `_R` token in a UART capture.
- Some Nextion components may need specific settings to trigger release events properly
- Ensure the button component is set to "Press" or "Touch" mode, not "Click" mode

### Volume keeps repeating after release
- Ensure Touch Release Event sends its own framed `_R` token.
- Check UART connection stability
- The firmware has a 2-second safety timeout that will stop repeating automatically

---

## Alternative: Send the Whole Token with `printh`

You can send the complete frame as raw hex instead of using two commands:

```
printh 42 54 5F 56 4F 4C 55 50 5F 50 FF FF FF
```

This is equivalent to `print "BT_VOLUP_P"` followed by `printh FF FF FF`. Use one form or the other, not both.

---

## Related Files

- `firmware/circuitpython/lib/nextion/display.py` - Token allowlist and parsing logic
- `firmware/circuitpython/main.py` - Press/release event handlers and hold-and-repeat logic
- `docs/reference/code-reference.md` - Complete code reference documentation

---

**Last Updated**: 2026-11-26

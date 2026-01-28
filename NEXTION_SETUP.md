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
printh 23 02 54 XX
```

Where `XX` is the hex ASCII representation of your token name. For the volume buttons:

- **Volume Up Press**: Send token `BT_VOLUP_P`
- **Volume Down Press**: Send token `BT_VOLDN_P`

### 2. Touch Release Event  

**When to trigger**: When the button is released

**Where to configure**: Same button component, **Event** tab

**Event**: `Touch Release Event`

**Command to send**:
```
printh 23 02 54 XX
```

Where `XX` is the hex ASCII representation of your token name. For the volume buttons:

- **Volume Up Release**: Send token `BT_VOLUP_R`
- **Volume Down Release**: Send token `BT_VOLDN_R`

---

## Complete Examples

### Volume Up Button

**Touch Press Event**:
```
printh 23 02 54 42 54 5F 56 4F 4C 55 50 5F 50
```
This sends `BT_VOLUP_P` (hex: `42 54 5F 56 4F 4C 55 50 5F 50`)

**Touch Release Event**:
```
printh 23 02 54 42 54 5F 56 4F 4C 55 50 5F 52
```
This sends `BT_VOLUP_R` (hex: `42 54 5F 56 4F 4C 55 50 5F 52`)

### Volume Down Button

**Touch Press Event**:
```
printh 23 02 54 42 54 5F 56 4F 4C 44 4E 5F 50
```
This sends `BT_VOLDN_P` (hex: `42 54 5F 56 4F 4C 44 4E 5F 50`)

**Touch Release Event**:
```
printh 23 02 54 42 54 5F 56 4F 4C 44 4E 5F 52
```
This sends `BT_VOLDN_R` (hex: `42 54 5F 56 4F 4C 44 4E 5F 52`)

---

## Understanding the `printh` Command

The `printh` command sends hexadecimal bytes over UART. The format is:

```
printh 23 02 54 [ASCII_HEX_OF_TOKEN]
```

**Breakdown**:
- `23` = `#` (start marker for the firmware's token parser)
- `02` = STX (Start of Text control character)
- `54` = `T` (Token identifier)
- Remaining bytes = ASCII hex representation of your token name

**Example conversion** for `BT_VOLUP_P`:
```
B  = 0x42
T  = 0x54
_  = 0x5F
V  = 0x56
O  = 0x4F
L  = 0x4C
U  = 0x55
P  = 0x50
_  = 0x5F
P  = 0x50
```

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
3. Must be sent with the correct `printh` prefix (`23 02 54`)

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
- Verify the `printh` command has the correct hex bytes
- Check that the token is in the firmware's allowlist (`TOK_BT` in `display.py`)
- Ensure UART baud rate is 9600 for Nextion communication

### Volume doesn't repeat when held
- Verify BOTH press (`_P`) and release (`_R`) events are configured
- Check that Touch Release Event is actually firing (some Nextion components may need specific settings)

### Volume keeps repeating after release
- Ensure Touch Release Event is properly configured and sending
- Check UART connection stability
- The firmware has a 2-second safety timeout that will stop repeating automatically

---

## Converting Token Names to Hex

If you need to add a custom token, use this Python snippet to convert:

```python
token = "BT_VOLUP_P"
hex_bytes = " ".join(f"{ord(c):02X}" for c in token)
print(f"printh 23 02 54 {hex_bytes}")
```

Or use an online ASCII to hex converter and manually format the `printh` command.

---

## Related Files

- `firmware/circuitpython/nextion/display.py` - Token allowlist and parsing logic
- `firmware/circuitpython/main.py` - Press/release event handlers and hold-and-repeat logic
- `CODE_REFERENCE.md` - Complete code reference documentation

---

**Last Updated**: 2026-01-28

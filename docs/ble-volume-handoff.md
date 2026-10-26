# Switch the BLE volume remote between saved hosts

CrowPanel **Settings → Pause volume remote** releases the audio unit's BLE
Consumer Control connection and stops advertising. Wait for **Paused (bonds
kept)** before switching hosts. Volume/mute reports remain disabled until
**Enable volume remote** or an audio-unit reset; the pause is not saved across
reset. Saved bonds, the BLE name and the HID report descriptor are preserved.

This controls the ESP32's BLE volume/mute link. BM83's audio, transport and
metadata connection is separate. Pausing the volume remote does not disconnect
BM83 audio or stop playback. The operating system's Bluetooth menus are unchanged;
some HID-device menus offer only Remove/Forget rather than Disconnect.

## Normal handoff

1. Tap **Pause volume remote** and wait for **Paused (bonds kept)**.
2. Make the previous host stop reconnecting, using its device-specific Disconnect
   control when available. If it has no Disconnect control, turn off that host's
   Bluetooth when practical; this also disconnects its other Bluetooth devices.
   Keep all saved pairing entries. Do not use Forget, Remove or Erase BLE bonds.
3. Prepare the next previously paired host, then tap **Enable volume remote**.
   Connect from its saved device entry if needed and verify volume up/down and
   mute. Switch the separate BM83 audio connection as needed.

Enable allows ordinary connections from saved hosts; it cannot select a target.
The previous host can reconnect first if it is still trying. If that happens,
Pause again, release the previous host and Enable when the desired host is ready.
Pair a genuinely new host normally after enabling; existing hosts stay bonded.

The panel reports completion from fresh observations of the audio unit, not from
a wireless delivery acknowledgement. **Request unconfirmed** means completion
was not confirmed; **Volume remote unavailable** or a disabled button can mean
the status link is stale or the controller lacks this feature. Do not treat a
"sent" message as proof that the BLE link has been released. An error or
disconnect timeout also does not establish Paused.

## Install the matching application files

Deploy the updated CrowPanel firmware and the matching CircuitPython `boot.py`,
`main.py` and project libraries. A library-only update omits startup suppression
of CircuitPython's maintenance advertiser. `boot.py` disables that advertiser
before it starts; the application also checks it when servicing Pause/Enable.
The existing HID profile stays Consumer Control only.

Normal `.py`/`.mpy` updates do not erase the bond store. For four saved hosts,
the stock three-bond runtime is insufficient: use the reviewed eight-bond,
24-CCCD runtime and [bond-preserving app-only updater](ble-runtime-update.md).
Capacity increases cannot restore keys already evicted or erased. Diagnose such
a host separately rather than using a bond wipe as a handoff step.

## Keep the startup name stable

[settings.example.toml](../firmware/circuitpython/settings.example.toml) is an
inactive example. Merge its settings into `CIRCUITPY/settings.toml`; preserve
existing device-local values and never replace private settings wholesale.
The example matches the default `BLE_NAME` in `main.py`. If this installation
already has a different app name, use that established name instead.

`CIRCUITPY_BLE_NAME` supplies CircuitPython's startup/default adapter name and
avoids its fallback `CIRCUITPYxxxx` name. `CIRCUITPY_BLE_WORKFLOW = false` disables
the maintenance workflow; it does not disable application HID. These are
[CircuitPython 10.3.1 settings](https://github.com/adafruit/circuitpython/blob/10.3.1/docs/environment.rst#keys-that-affect-circuitpython-behavior).
Use a physical reset after changing startup settings.

The application sets its own advertised/GAP name from `BLE_NAME`. An existing
suffix from the explicit **Erase BLE bonds** recovery path is also retained.
Keep the startup setting consistent with the installed name; changing the setting
does not rename the app or repair a bond. Pause/Enable never increments a name
counter, and ordinary application updates should preserve that counter file.

## Verify each saved host

For Mac, Windows, Raspberry Pi/Linux and iPhone, repeat a handoff away and back
using the existing saved entry. Confirm Paused before leaving, a connected state
after return, and actual volume up/down/mute on the intended host. Check BM83
audio/transport/metadata separately. Retain the same name and saved entries
throughout; host tests alone cannot establish successful reconnection.

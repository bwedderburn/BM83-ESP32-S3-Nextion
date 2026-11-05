# Switch the BLE volume remote between saved hosts

The Disconnect + Select host implementation is a development candidate. Its
separate [build and physical acceptance record](../reliability/phase2-host-selection.md)
must pass before installation is treated as accepted. The instructions below
describe the matching candidate; an older eight-bond runtime alone cannot
provide host selection.

Open CrowPanel **Settings → Volume hosts**. **Disconnect** requests a saved pause
of the BLE volume connection. Wait for **Disconnected. Saved pairings are kept.**
before leaving that host. The pause remains through a controller reset.
**Connect** enables only the saved identity selected in the dialog. The selected
host is also used after a normal boot or an unexpected connection loss.

This controls the ESP32's BLE volume link. BM83's audio, transport and
metadata connection is separate. Pausing the volume remote does not disconnect
BM83 audio or stop playback. The operating system's Bluetooth menus are unchanged;
some HID-device menus offer only Remove/Forget rather than Disconnect.

## Normal handoff

1. Tap **Disconnect** and wait for the confirmed disconnected message.
2. Leave each host's Bluetooth on and retain its saved pairing entry.
3. Choose the intended saved identity, then tap **Connect**. Wait for
   **Volume control connected to ...**, and verify one volume-down and one
   volume-up step on that host. **Waiting for ... to connect** means that AUTO is
   enabled but a ready connection has not yet been observed. A host that has
   stopped initiating connections may need its saved-entry Connect control.
4. Move the separate BM83 audio connection if the audio source should also change.

Saved hosts initially appear with opaque identifiers. **Rename** saves an
owner-defined label of at most 24 UTF-8 bytes. A label does not change the BLE
device name, keys or selected identity. The unit does not infer operating-system
names from a discovery address.

For a genuinely new host, use **Pair new host**, then pair from that host within
the 60-second window. Existing pairings remain saved. A full store, expired
window, unavailable native runtime or storage error must be resolved separately;
the unit does not evict another host to make the request succeed. **Disconnect**
cancels a pending connection or pairing operation. Merely closing the dialog
does not cancel it.

For first-time Windows pairing, choose **Add device → Bluetooth → Show all
devices** if the remote is absent from the initial list. Windows can filter this
volume-only remote from its default discovery results. This is initial setup;
subsequent handoffs use the saved entry and do not require removal or re-pairing.

The panel reports completion from fresh observations of the audio unit, including
the matching operation, durable policy and actual security/HID readiness. A
wireless delivery acknowledgement cannot complete the request. **Request
unconfirmed** means completion was not confirmed. A disabled control can mean
that status is stale, registration is incomplete, or the controller lacks the
native feature. An error or disconnect timeout does not establish a saved pause.

Use the explicit CrowPanel action for a deterministic stay-disconnected request.
The operating system may offer only Remove/Forget for this HID profile, and a
link-disconnect reason cannot reliably distinguish a human click from sleep or
another unexpected loss.

## Install the matching application files

Install the reviewed project native host-policy runtime, updated CrowPanel
firmware, and matching CircuitPython `boot.py`, `main.py` and project libraries.
Stage and verify these changes only at the agreed paused/safe-mode point. A
library-only update omits startup suppression
of CircuitPython's maintenance advertiser. `boot.py` disables that advertiser
before it starts; the application also checks it when servicing Pause/Enable.
The existing HID profile stays Consumer Control only.

Normal `.py`/`.mpy` updates do not erase the bond store. The candidate native
runtime retains the reviewed eight-bond, 24-CCCD capacity and requires a
[bond-preserving app-only update](ble-runtime-update.md) with the separate
[scoped native write approval and rollback checks](../reliability/RUNTIME-FLASH-GUARDS.md).
Capacity increases cannot restore keys already evicted or erased. Diagnose such
a host separately rather than using a bond wipe as a handoff step.

## Keep the startup name stable

[settings.example.toml](../../firmware/circuitpython/settings.example.toml) is an
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
does not rename the app or repair a bond. Disconnect/Connect never increments a name
counter, and ordinary application updates should preserve that counter file.

## Verify each saved host

For Mac, Windows, Raspberry Pi/Linux and iPhone, repeat a handoff away and back
using the existing saved entry. Confirm Disconnect before leaving, a connected state
after return, and actual volume up/down on the intended host. Check BM83
audio/transport/metadata separately. Retain the same name and saved entries
throughout; host tests alone cannot establish successful reconnection. Test a
controller reset while paused and while AUTO is selected as separate cases.
Keep other saved hosts in range with Bluetooth on to verify selected admission.

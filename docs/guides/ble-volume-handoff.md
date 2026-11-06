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

## Open the Windows companion from CrowPanel

**Settings → Volume hosts → Open Windows app** opens or restores **BM83 Volume
Remote** on the configured Windows PC. Wait for the panel to confirm the window.
The button uses the CrowPanel's existing Wi-Fi and becomes available when the
receiver is running in a signed-in Windows desktop session.

The [companion app](../../tools/bm83-windows-volume-host.py) uses Python 3.10 or
later with Tkinter. From the checkout, run the command below while the CrowPanel
is connected over USB. Install `pyserial` in that Python environment for this
one-time setup.

```powershell
py -3 .\tools\windows_volume_app_receiver.py --configure
```

The [receiver](../../tools/windows_volume_app_receiver.py) creates
`.bm83_windows_receiver.json` in the signed-in user's
`%LOCALAPPDATA%\BM83VolumeRemote` directory. For the companion's **Status** and
**Disconnect** buttons, make a private copy of the controller's
`.badge_remote.json` profile named `.bm83_windows_companion.json` in that same
directory. Add a `host` field with the controller's LAN address and keep its
existing `v`, `key`, `port` and optional `client_ip` fields. If the profile sets
`client_ip`, the companion must run from that address. The companion uses the
BMW1 control key in its own profile.

Run the receiver in the signed-in user's desktop session. To start it at login,
add a shortcut to `pythonw.exe` with the absolute receiver script path as its
argument in the user's Startup folder. An existing installation can supply
`--config <private-local-json>` and can pass its local companion path after
`--configure`. Keep these files in an owner-only directory outside Git.
The receiver polls over authenticated UDP and needs no inbound Windows firewall
rule. If the panel's LAN address changes, rerun setup and restart the receiver.

## Use Volume hosts from the badge

On the badge, open **BM83 Remote → Menu → Volume hosts**. **Disconnect** keeps
saved pairings. **Select saved host** reconnects the chosen host. **Pair new
host** opens a 60-second enrollment window that **Disconnect** can cancel.
**Open Windows app** shows a launch result after the Windows receiver confirms its window.

The matching controller application exposes these controls through the badge's
existing authenticated connection. For Windows launch, provision a separate
random 32-byte key as 64 hex characters in the controller's private
`/.badge_windows_launch.key` file. In the Windows receiver's private JSON, add a
`controller` object with the controller's `host`, badge receiver `port`, and
matching `key`. Restart the signed-in receiver after updating its configuration.
The badge's BMW1 clients can request a launch. The separate launch key
authenticates the Windows receiver's polls. Keep both key files private and
leave the existing badge and CrowPanel keys in place.

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

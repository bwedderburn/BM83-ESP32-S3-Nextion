# Mac Now Playing metadata over Wi-Fi

The Mac bridge sends the current title, artist, album, playback state and timing
to the BM83 controller over the existing Wi-Fi network. Audio continues over
Bluetooth. The controller forwards the metadata to the Nextion and CrowPanel
displays through its existing display paths. The bridge reads macOS Now Playing,
so supported browser players can supply metadata without opening Apple Music.

When the Bluetooth session supplies no native track text, the display uses the
Wi-Fi title, artist, album, elapsed/total time and playing/paused status. Native
AVRCP metadata from an iPhone, Windows or Linux takes priority for the session.
Power, Bluetooth connection, AUX selection and playback commands remain BM83
decisions.

The Mac sends a complete snapshot every two seconds by default. The controller
updates the Nextion clock once per second between packets; the CrowPanel uses
the same source position and its age. After successive playing samples show
advancing positions, both displays can project normal-speed elapsed time.
Pausing stops projection, and new seek positions rebase the source clock.
Unknown timing fields appear as `--:--`. Elapsed position expires after five
seconds without a fresh position sample; bridge metadata clears after eight
seconds without a fresh packet. Repeating a cached packet locally never makes
its clock sample newer.

This clock is the Mac's **OS-estimated playback position**. Apple documents that
elapsed time is calculated from a stored elapsed-time anchor and playback rate,
so the underlying metadata timestamp may legitimately stay unchanged throughout
a song. Fresh bridge snapshots can still contain advancing estimates. This is
not an independent measurement that audio is moving. See Apple's
[elapsed playback time documentation](https://developer.apple.com/documentation/mediaplayer/mpnowplayinginfopropertyelapsedplaybacktime).

The Mac sends metadata only while its selected audio output is named **BM83**.
Switching to another output sends a clear/stopped snapshot. The bridge does not
play, pause, skip tracks, change volume or change the Mac's audio output.

## Prerequisites and why they matter

| Requirement | How to check or configure it | Why it is needed |
| --- | --- | --- |
| Controller firmware with the bridge | Deploy the firmware containing `main.py`, `remote/metadata_bridge.py` and `bm83/link_probe.py`, or matching compiled modules. | The Mac sender needs a receiver on the audio controller. `.py` and `.mpy` are both valid; a missing `.mpy` alone is not a missing module. |
| Controller joined to the saved 2.4 GHz access point | Keep `/.artwork_wifi.json`; startup should report `[NET] artwork Wi-Fi ready` and an IPv4 address. | Bluetooth carries audio; the LAN carries the Mac's metadata. Local ESP-NOW controls can still work without a LAN address. |
| Reachable, stable controller address | Set the sender's destination with `--host`; reserve that address for the controller in the router's DHCP settings. | The sender targets one IPv4 address and does not discover address changes automatically. The Mac can use Ethernet or Wi-Fi on the reachable LAN. |
| BM83 selected as the Mac audio output | Select **BM83** in macOS audio output controls. | The bridge uses the selected output to avoid displaying metadata from an unrelated playback session. |
| Now Playing fields supplied by the player | Run the local `--snapshot` command below and check title and artist. | The bridge can only forward fields macOS receives. Some browser players supply a station title without an artist. |
| Mac sender running and allowed on the LAN | Check the LaunchAgent and allow Python under macOS Local Network privacy settings if prompted. | The login service reads Now Playing and sends UDP updates every two seconds. A running process alone does not prove packets reach the controller. |
| Matching private pairing profiles | The installer maintains the same token on the Mac and controller. | The receiver rejects metadata from an unpaired sender. |

USB is needed for initial provisioning and firmware maintenance. It is not
needed for normal metadata forwarding. Internet access is needed for new
artwork downloads; the local metadata bridge only needs the LAN.

## One-time setup

1. Deploy the controller firmware containing `lib/remote/metadata_bridge.py` or
   its compiled `.mpy` version.
2. Connect the ESP32-S3 controller's **native USB** port to the Mac. Confirm that
   its `CIRCUITPY` volume appears. A USB-to-UART adapter alone does not provide
   the filesystem needed for this setup; its chip name does not identify which
   board it is attached to.
3. Keep the existing `/.artwork_wifi.json` profile on the controller. This bridge
   reuses its Wi-Fi connection and AP channel. If that profile has not been
   provisioned, complete the existing Wi-Fi setup first.
4. Find the controller's Wi-Fi IPv4 address from its startup serial output or
   the router's client list. Keep the Mac on a network that can reach that address.
   A router DHCP reservation for the controller keeps this destination stable.
5. Validate the setup from the repository folder, replacing the sample address:

   ```sh
   python3 tools/setup_mac_metadata_bridge.py --volume /Volumes/CIRCUITPY --host 192.168.1.40
   ```

6. Install and start the bridge with the same arguments and `--install`:

   ```sh
   python3 tools/setup_mac_metadata_bridge.py --volume /Volumes/CIRCUITPY --host 192.168.1.40 --install
   ```

Python 3.9 or newer, the macOS system Perl, and Xcode Command Line Tools are
required. The installer builds the native Now Playing reader locally; it does
not download packages. It starts a per-user LaunchAgent that also starts after
future logins. USB is needed for provisioning and firmware deployment; normal
metadata forwarding uses Wi-Fi.

macOS may ask to let **Python find devices on local networks**. Allow that
request for this installed bridge. The sender retries after approval and
reports network recovery in its private error log.

The controller attempts its saved Wi-Fi connection at startup. The receiver
opens only after Wi-Fi has an IPv4 address. If that initial attempt fails,
the bridge stays disabled for that boot; the Mac sender's retries cannot
reconnect the controller. Once the access point is available, use **Settings →
Wi-Fi / Artwork → Retry both** on the CrowPanel, or restart the audio controller, to
repeat the coordinated startup. This avoids a blocking Wi-Fi connection
attempt in the BM83's UART service loop. A later connection loss also breaks
metadata while Bluetooth audio can continue independently.

The command without `--install` only validates the setup. It changes no files.
Installation refuses a volume that does not identify itself as an ESP32-S3
CircuitPython controller. It never overwrites the artwork Wi-Fi profile.

## Files and pairing

The installer writes these files outside the repository:

| Location | Purpose |
| --- | --- |
| `~/Library/Application Support/BM83MetadataBridge/` | Installed sender, native helper, private configuration and logs |
| `~/Library/LaunchAgents/com.bwedderburn.bm83-metadata-bridge.plist` | Start the sender at login |
| `/Volumes/CIRCUITPY/.metadata_bridge.json` | Receiver port and matching pairing token |

The pairing token is generated locally and is never printed or included in
process arguments. The Mac directory uses mode `700`, and its configuration
uses mode `600`. The removable controller filesystem may not enforce POSIX
permissions; keep its hidden pairing profile private when copying its files.
The token authenticates datagrams but does not encrypt metadata on the LAN.

Rerunning setup preserves an existing matching token. Conflicting host and
controller tokens cause setup to stop without replacing either pairing.
Restore a matching private backup before retrying. Keep real pairing profiles
and Wi-Fi credentials out of Git and shared diagnostic bundles.

By default, the receiver accepts the matching token from any source address on
its network. For a Mac with a stable IP, add `--host-ip 192.168.1.20` to restrict
the receiver to that Mac's source IPv4 address. An existing source restriction
is preserved when that flag is omitted. If that address later changes, run
setup again with the new address. `--port` can change the UDP port from its
default of `8766` on both sides.

## Check the result

Select **BM83** as the Mac's audio output and play a track in a player that
publishes macOS Now Playing metadata. Check that the displayed title changes
when the track changes, elapsed/total time appears when available, pausing stops
the elapsed clock, and switching the Mac's audio output clears the Mac metadata.
Verify these behaviors on both hardware displays; a successful local helper
read alone does not verify the Wi-Fi path or the hardware clock.

The CrowPanel sends buttons to the audio controller over ESP-NOW. Play/Pause
and track changes then use the BM83's Bluetooth controls; volume and mute use
the controller's BLE media keys. Check these separately from metadata.
An ESP-NOW delivery acknowledgement alone does not prove that a command ran.
The controller logs an accepted button as `[REMOTE] BT_PLAY`, for example.

CircuitPython 10.3.1 can expose an incomplete native receive-buffer entry.
The receiver waits for its completed-packet counter before reading. If native
framing is nevertheless damaged (`Invalid buffer`), it rebuilds ESP-NOW's
receive buffer and restores the paired peer, with bounded retries. This
recovery preserves the joined Wi-Fi network, BLE connection and recent button
sequence history. Repeated receive errors or missing accepted-button logs
need investigation even if metadata still reaches the displays.

Local interpolation assumes normal-speed playback. Other playback rates are
reflected by each new Mac snapshot but may be less smooth between packets. The
CrowPanel also retains its existing protection against paused sources that
keep reporting drift: a seek while paused may remain at the first paused
position until playback resumes or the track changes.

To inspect one local snapshot without sending network traffic:

```sh
python3 "$HOME/Library/Application Support/BM83MetadataBridge/bridge.py" \
  --helper "$HOME/Library/Application Support/BM83MetadataBridge/now_playing.dylib" \
  --snapshot
```

The private `bridge-error.log` in the installed directory contains sender errors.
If local metadata is present but the displays do not update, check the
controller's Wi-Fi address, its startup diagnostics and whether the network
allows UDP between its clients. If the Mac output device has been renamed,
set `target_output` in the private Mac `config.json` to that exact output name
and restart the agent.

To stop the background sender:

```sh
launchctl bootout "gui/$(id -u)/com.bwedderburn.bm83-metadata-bridge"
```

To start it again:

```sh
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.bwedderburn.bm83-metadata-bridge.plist"
```

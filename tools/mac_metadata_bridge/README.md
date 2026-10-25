# Mac metadata sender

This optional bridge reads the Mac's current Now Playing metadata and sends it to
the ESP32 display controller over the LAN. Bluetooth audio and transport controls
continue through the BM83. It never sends playback commands, changes Bluetooth
pairings, modifies macOS security settings, or automates a user interface.

The sender transmits metadata only when the **default CoreAudio output name
exactly matches `target_output`**, ignoring case (`BM83` by default). Switching
the Mac to its speakers sends an explicit stopped/clear heartbeat so it cannot
replace a phone's metadata merely because the Mac is playing something locally.
The receiver separately gates bridge data on active Bluetooth, power, source,
and native AVRCP metadata. When native track text is absent, the Wi-Fi fallback
supplies title, artist, album, elapsed/total time and playing/paused display
status. Native AVRCP metadata takes priority for that Bluetooth session.

## Runtime

- macOS with `/usr/bin/perl`, Python 3.9 or later, and Xcode Command Line Tools.
- No Python packages, browser extension, or downloaded executable is required.
- The native helper uses Apple's installed private MediaRemote framework and
  `MRNowPlayingRequest.localNowPlayingItem.nowPlayingInfo` to read the same
  system Now Playing item. CoreAudio supplies the default output device name.
- Modern macOS restricts metadata access from standalone third-party processes.
  A small self-authored Objective-C helper runs inside the existing Apple-signed
  system Perl host through its standard `DynaLoader` API. This read-only host
  technique is described by [mediaremote-adapter](https://github.com/ungive/mediaremote-adapter).
  No vendor source or binary is bundled, and no entitlement is forged.
- Tested live on Intel macOS 26.7.1. MediaRemote is a private API and future
  macOS updates may require adapting the reader.

Build and inspect a local snapshot (no network traffic):

```bash
python3 tools/mac_metadata_bridge/bridge.py --build-helper
python3 tools/mac_metadata_bridge/bridge.py --snapshot
```

On first network use, macOS may ask whether **Python** may find devices on the
local network. Approve this request for the display bridge. The background sender
keeps retrying and reports recovery after approval; it never changes privacy
settings itself. A pending or denied request can appear as `EHOSTUNREACH` even
when another app can reach the receiver.

For an installed copy, pass `--helper /absolute/path/now_playing.dylib` to both
commands. Building requires only the local source and Apple toolchain.

## Private sender profile

The setup tool installs a profile separately from the source tree. Its JSON keys
are `host` (receiver IPv4 address), `port` (8766), `token` (shared random secret),
`target_output` (`BM83`), and `interval` (2 seconds). An optional `v: 1` field is
accepted. The file must be a regular, user-owned file with mode `0600` or stricter;
symlinks and group/world-readable profiles are rejected. Do not put tokens in
shell command arguments, commit them, or paste the profile into diagnostic logs.

Run using that profile:

```bash
python3 tools/mac_metadata_bridge/bridge.py --config /absolute/path/private-config.json
```

`--once` sends one heartbeat and exits. `--snapshot` only reads local information
and never reads a profile or transmits a packet. A user LaunchAgent may invoke
the same sender command with absolute paths; the setup tool owns installation.

## Wire format and failover

Each UTF-8 UDP JSON datagram is bounded to 1400 bytes and contains:

- `v: 1`, `token`, a fresh 16-hex-character process `session`, and increasing `seq`.
- `state`: `playing`, `paused`, or `stopped`.
- `title`, `artist`, `album`: strings bounded to 256 UTF-8 bytes each, with controls
  removed. Escaping is also accounted for in the full datagram size.
- `duration_ms`, `position_ms`: nonnegative integers or `null` when unknown.

While playing, the sender projects elapsed position from MediaRemote's timestamp
and playback rate and clamps it to a known duration. While paused, it sends the
reported position without extrapolating it. The default two-second packets feed
the controller's once-per-second Nextion display update and the CrowPanel's
existing clock model. Successive advancing positions permit local interpolation
at normal playback speed; pause and backward seeks stop that projection until
new movement is observed. Each fresh snapshot replaces timing completely, so
`null` clears a previously known value rather than retaining the old track's
clock. Missing timing appears as `--:--`.

Elapsed position becomes unknown after five seconds without a fresh timing
sample. Bridge metadata expires after eight seconds without a fresh packet.
These bounds use the receiver's monotonic clock, and repeated local reads or
radio retransmission never renew the source sample's age.

This is an **OS-estimated clock**, not a separate observation of audio motion.
[Apple's elapsed playback time documentation](https://developer.apple.com/documentation/mediaplayer/mpnowplayinginfopropertyelapsedplaybacktime)
explains that the system derives elapsed time from an earlier elapsed-time value
and playback rate without requiring frequent property updates. A constant
MediaRemote anchor timestamp during a whole song is therefore valid. The
bridge re-reads current metadata and computes a new estimate for each heartbeat;
it does not reject a valid anchor merely because the anchor itself is old.

Local display interpolation assumes 1x playback. A different positive playback
rate is reflected in the sender's next position estimate, but the display may
drift between packets. The existing CrowPanel paused-position hold also remains:
a seek while paused can remain at the first paused position until a track or
playback-state change. Nextion uses the new paused sample directly.

Reader failure, absent title/item, route changes, or normal shutdown send
stopped with empty text.
UDP delivery is best effort; the next complete heartbeat repairs a dropped one.
Transient send failures recreate the UDP socket before retrying. Error logs expose
only the OS errno and retry count, are limited to one entry per 30 seconds for an
unchanged error, and report recovery once. Profiles and tokens are never logged.
The shared token authenticates LAN traffic but does not encrypt listening data;
use only the intended trusted LAN.

## Application metadata limits

Native Music and web applications can be bridged when they publish a system Now
Playing item. The sender forwards the metadata actually present; it does not
invent an artist from a browser tab title. A web player that does not populate
Chrome's Media Session metadata may publish only its page title. In a live
Pandora snapshot during setup, Chrome supplied the station/page title, duration,
and position, with blank artist and album. The transport can forward those
fields, but showing Pandora's actual song/artist requires the site to publish
those values (or a separately implemented browser integration).

## Checks

```bash
python3 -m pytest -q tests/test_mac_metadata_bridge.py
```

These host tests use fake sockets and snapshots. A live `--snapshot` plus a
loopback datagram check can verify the native reader and sender without changing
playback or contacting the board. The Native Music reader supplies full timing
when the system publishes it. Display text and a local timing read do not prove
the elapsed clock works on hardware: play, pause, seek, source changes and
sender expiry still require actual-unit validation after firmware deployment.

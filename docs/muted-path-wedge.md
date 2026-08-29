# The muted-path wedge — consolidated field knowledge

Status: **accepted chip/stack quirk with known recovery**, not an open
firmware bug. This note consolidates what three hardware sessions
(2026-08-02, 2026-08-26, 2026-08-29) established, so the next person who
hits "everything says playing, no sound" does not re-derive it.

## Signature

After an **abnormal A2DP stream teardown** the BM83's audio path can come
back muted while every protocol layer above it stays healthy:

- chip pinned at BTM_Status `0x82` ("A2DP is my active source"),
- AVRCP fully alive — metadata, track time, play/pause control all work,
- the source app (observed with Apple Music on Windows) shows *playing*,
- **no audio output**, indefinitely.

Known triggers, all variants of "the stream died without a clean
suspend": a quick BT off/on reconnect; **a CircuitPython auto-reload while
audio is streaming** (every deploy to CIRCUITPY does this — deploys during
live playback wedge the stream essentially every time); the central
rebooting mid-stream.

## Windows-side signature (new, 2026-08-29)

The wedge is visible from the central too: while wedged, **the "Test"
sound option disappears from Windows Advanced sound settings** for the
BM83 endpoint. The Bluetooth A2DP driver still holds the dead AVDTP stream
object, so the endpoint reports itself non-renderable and Windows will not
offer test playback on it. This confirms the wedge lives on *both* ends —
the chip's internal routing and the host driver's stream state — which is
why only a source-side stream rebuild recovers it: that forces Windows to
close and re-open the AVDTP stream, un-wedging both ends at once.

## Recovery (source side only)

In the source app, in order of preference:

1. **Pause → wait 2 full seconds → Play.** The gap is the active
   ingredient (hardware-observed 2026-08-02): the source must fully tear
   the stream down before the restart re-engages the chip's routing. A
   quick pause/play does **not** work.
2. **Skip to the next track** (also rebuilds the stream).
3. **Toggle Bluetooth off/on on the central** — the guaranteed rebuild;
   also restores the Windows "Test" button.

**Sink-side recovery does not exist.** AVRCP PAUSE→2.5s→PLAY injected by
the firmware executes perfectly and changes nothing — proven on hardware
2026-08-02 (round 3 of [code-review-2026-08-02.md](code-review-2026-08-02.md)).
The machinery ships disabled behind `STREAM_KICK_ENABLED = False` in
`main.py` and should stay that way.

## Operational rules

- **Never deploy to CIRCUITPY during live playback** unless the person at
  the unit knows the stream will wedge and how to recover it.
- After any deploy, expect the first play attempt to be silent until a
  source-side rebuild is done.
- The firmware's job here is only to keep the *protocol* session healthy
  through the bounce (relink + AVRCP re-arm, PR #133) so metadata and
  controls survive; the audio path itself is chip + host-driver territory.

## If it needs a real fix someday

The likely levers are chip-side, not AVRCP-timing: BTM_Utility_Function /
vendor audio-path options, or MSPK2 errata behavior (see the Microchip
docs kept at the repo root). A control test with a second source app
(Spotify / browser) would size Apple Music's own contribution — Apple
Music on Windows has widely reported first-play Bluetooth dropouts no sink
can fix.

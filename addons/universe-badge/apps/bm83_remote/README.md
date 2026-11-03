# BM83 Remote

BM83 Remote brings the CrowPanel audio controls and Now Playing information to the GitHub Universe badge.

## Integration status

This is an optional badge client imported from the user's BADGER app snapshot.
The matching opt-in BMW1 UDP receiver lives in the BM83 repository at
`firmware/circuitpython/lib/remote/badge_remote.py`; this add-on does not deploy
it. Existing artwork Wi-Fi and ESP-NOW support alone cannot accept this client's
UDP commands. The controller always refuses `NET_RETRY`, and the Settings retry
here is badge-local only.

The client has been checked with host tests and in the official Universe 2026
badge simulator using fixture sockets. The simulator has no UDP sockets, HTTPS
fetch or `os.urandom`, so it covers rendering and button handling against
controlled replies, not real Wi-Fi/UDP, a BM83 unit, or the physical badge
display and buttons. Separate later
[Mac/helper validation](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/main/docs/validation/bm83-startup-artwork-validation-2026-11-01.md)
records scoped 30-minute physical acceptance with owner observations. That
result does not extend the simulator's scope or establish all platforms and
startup/recovery combinations.

Playback validation now rejects snapshots that omit
`duration_ms`, `position_ms`, or `position_age_ms`; these fields may explicitly
be `None`. Previously those malformed snapshots passed validation and could
raise `KeyError`. Volume gestures also retain their own press/release ordering:
rapidly releasing and pressing the same button sends press, release, press,
including when the first press is still in flight. Completed quick taps each
retain their release; a release awaiting retry still blocks newer commands.
Wi-Fi failures honor their retry deadlines across clock rollover, releasing an inactive volume button
does not stop the direction still being held, and accented metadata maps to the
correct display characters. Empty or invalid album metadata clears the previous
artwork identity so Retry cannot restore a stale cover.
An unfinished lookup interrupted by Wi-Fi loss resumes once when connectivity
returns; explicit cancellation and completed or failed lookups do not loop.
HOME cleanup discards unsent volume gestures and preserves the required releases
for presses already sent, rather than starting queued presses while exiting.

Artwork responses now use the public bounded `fetch.AsyncFetch` API, with a
32 KiB JSON limit, 128 KiB JPEG limit, 10-second inactivity timeout, and a
45-second overall budget checked between cooperative steps. Cancellation resets
the request and closes its socket. Only a completed, bounded response is written
to a temporary file. Firmware lacking this API shows a bounded-fetch-required
message; cached artwork and audio controls remain available. The upstream API
can block during DNS, which the cooperative deadline cannot preempt.

Artwork start, retry and cooperative pumping wait until the authenticated
remote has no transaction, queued control or volume gesture outstanding. The
latest album is selected when that work actually starts; a changed album is
not lost while the remote is busy. Each frame performs one artwork operation,
and rendering checks freshness again afterward. Offline cancellation still runs
immediately. This scheduling keeps potentially slow artwork work outside an
in-flight UDP reply window; it does not make the firmware's DNS, file I/O or
image decoder nonblocking, extend the 600 ms reply deadline, or establish
physical network or TLS behavior.

A targeted `F821` lint annotation also identifies the `image`
global supplied by badge firmware in `artwork.py`; it changes no behavior.
Internal command identifiers and pending-state fields use `command` so static
security scanners do not mistake public command strings for credentials. The
BMW1 wire JSON field remains `token` for receiver compatibility; this rename
changes no behavior. Text line endings are normalized to LF, and the original
menu icon is preserved.

## Badge runtime

This app needs the GitHub Universe badge firmware, its injected graphics/button
APIs, `wifi`, bounded `fetch.AsyncFetch`, and MicroPython socket/hash/time support. It has no pip
or npm dependencies and is not a standalone CPython application. The folder is
installed as `/system/apps/bm83_remote` on the badge; its existing launcher
discovers app folders. Do not replace the badge's launcher or `main.py`.

Open **BM83 Remote** from the badge menu while the badge and BM83 audio unit are on the same Wi-Fi network. The unit must run the matching BMW1 UDP receiver on port 8767 and have the same 32-byte key. The badge requests album artwork over HTTPS from MusicBrainz and Cover Art Archive, with Deezer as a fallback; a small cache is stored under `/state/bm83_art/`.

## Controls

- **Left / Right**: previous / next track.
- **Select**: play / pause.
- **Back**: mute on the Now Playing page; cancel/return on Settings.
- **Hold Up / Down**: volume up / down; release the button to stop the unit's repeat.
- **Menu**: open Settings. Use **Up / Down**, **Select**, and **Back** to navigate.
- Settings provide Power, Pair, EQ, confirmed bond erasure, a badge-local Wi-Fi/artwork retry, and BLE volume-remote pause/enable when a fresh BLE status permits the request. **Badge Wi-Fi / artwork retry** only reconnects the badge's Wi-Fi and requests a new artwork lookup (`Local retry: badge Wi-Fi/artwork only`). The lookup waits for the authenticated remote to become idle and uses its latest album; it never sends `NET_RETRY`, so the audio unit is not asked to reconnect or reload.
- **Menu → Volume hosts** offers **Disconnect**, **Select saved host**, **Pair new host**, and **Open Windows app**. Disconnect pauses the BLE volume link and keeps saved pairings. Select a saved host to reconnect it, or open the 60-second pairing window for a new host. Disconnect also cancels the pairing window. The main **Pair** action is for BM83 audio pairing.
- **Open Windows app** uses the badge's existing controller connection. The badge reports success when the Windows receiver confirms the app window. This feature needs the matching controller application update and a separate launch key shared with the receiver. See the [volume handoff guide](../../../../docs/guides/ble-volume-handoff.md).

The status line reports whether a command was sent and whether a reply arrived. A press made before the audio unit authenticates waits for it; if the handshake gets no reply, pending presses are dropped (`Audio unit: no reply - N not sent`) so they cannot fire later. A reply is delivery feedback, not proof that playback or volume changed. After a `STATUS: no reply` or UDP error, the next successful STATUS reply changes the line to `Audio unit responding`; command outcomes stay visible. A reply marked `"denied": true` is shown as refused instead, for example `Erase bonds: refused by audio unit` when the receiver keeps bond erasure local-only. Any reply to the legacy `NET_RETRY` token reads `Receiver retry unavailable`. BLE Pause/Enable is reported as Waiting, Confirmed, Failed, Refused, or Unconfirmed and only confirms when a newer BLE status echoes the matching request client/sequence; null correlation means there is no current Wi-Fi-owned BLE request. The immediate reply to a BLE request may carry `"ble": null`; confirmation then comes from a later STATUS reply.

When the receiver reports the proven origin of the title/artist text in the optional `np.src` field, Now Playing shows `via AVRCP` or `via Mac Wi-Fi` beneath the EQ line. An empty, missing, or unknown value shows nothing; the app never guesses the source.

## Configuration and network

Add these values to the badge's existing `secrets.py`; never put real credentials in this app or commit them:

```python
WIFI_SSID = "your network"
WIFI_PASSWORD = "your password"
BM83_HOST = "192.168.1.50"  # the audio unit's IPv4 address
BM83_PORT = 8767             # optional; defaults to 8767
BM83_KEY = "64 lowercase hex characters shared with the audio unit"
```

The BM83 unit and badge need LAN connectivity. Automatic cover downloads also need internet access. Missing settings, Wi-Fi failures, unavailable units, missing artwork and unsupported/progressive JPEGs are shown in the app rather than treated as success. The header shows a short link state (`Authenticated`, `Awaiting unit`, `Wi-Fi offline`, `No UDP socket`); details such as the Wi-Fi error appear on the bottom feedback line. When valid settings are present but the firmware has no `socket` module, the app shows `No UDP socket` and `Wi-Fi/UDP unavailable` feedback instead of asking for configuration. The simulator cannot use sockets or HTTPS; `inject_sample_state()` can be called from its REPL to preview Now Playing layout.

## BMW1 details

Datagrams use the `BMW1.` prefix, a 16-byte HMAC-SHA256 tag, and UTF-8 JSON. The app verifies the tag before decoding JSON, accepts only replies from the configured IPv4/port, serializes one command at a time, retries the same sequence, and preserves a pending volume release ahead of other commands. Timed-out non-idempotent commands are not replayed under a new client. Status snapshots expire after six seconds; elapsed time advances only for a fresh playing snapshot whose source clock is advancing and remains within the source-age limit.

Artwork uses exact artist/album identity, a MusicBrainz score threshold of 95, unique release-group matches, a minimum 1.1-second MusicBrainz request interval and bounded response/cache sizes. Requests are HTTPS-only and limited to MusicBrainz, Cover Art Archive, Archive.org and Deezer hosts. The badge's `fetch` does not follow redirects, so the app follows at most three itself within that same allow-list. A busy MusicBrainz (HTTP 429, 502, 503 or 504) is retried up to three times at the same request interval before the app reports that artwork is unavailable; Settings then offers a retry. Artwork data is untrusted; only matching artist/album data and baseline JPEGs with bounded dimensions are used.

The frozen upstream fetch connection uses `CERT_NONE`. This app instead uses
its own `verified_fetch` connection adapter with `CERT_REQUIRED`, the requested
hostname and the exact public CA roots already retained by CrowPanel. The
upstream insecure connection method is never dispatched. Unsupported APIs,
invalid UTC clocks and certificate failures stop artwork requests; there is no
insecure fallback. A reset badge's clock can recover through the existing NTP
module, at most three attempts with backoff, serviced only at the same
control-idle background gate. Settings' local retry rearms those attempts.
Cached covers still work without clock sync. See
[artwork trust and physical release gates](artwork_trust/README.md) for the
source/license, exact roots, bounded context cache and remaining acceptance.

## Host tests

Run these dependency-free tests from the repository root:

```bash
python3 -m unittest discover -s tests -p 'test_badge_bm83*.py'
```

The test files locate `addons/universe-badge/apps/bm83_remote` in the BM83
repository or `badge/apps/bm83_remote` in the Universe workshop repository.
Tests exercise authentication, malformed input, playback freshness, correlated
BLE confirmation, artwork validation, and a fake UDP socket. They do not execute
the badge entrypoint, contact networks/devices, or test a receiver. In the BM83
repository, `tests/test_badge_remote.py` runs this client's transport against
the receiver in-process with fake sockets. Badge UI rendering on hardware and
actual button/audio behavior still require separately authorized physical-device
validation.

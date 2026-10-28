# BM83 Remote

BM83 Remote brings the CrowPanel audio controls and Now Playing information to the GitHub Universe badge.

## Integration status

This is an optional badge client imported from the user's BADGER app snapshot.
BM83 `origin/main` at `d2e773d` does **not** include the matching BMW1 UDP
receiver. This add-on does not add or deploy that receiver. Existing artwork
Wi-Fi and ESP-NOW support alone cannot accept this client's UDP commands.
Receiver interoperability and physical badge/audio-unit operation have not been
verified by this import. Use the sample-state preview or host tests until a
matching receiver is available and separately validated.

Playback validation now rejects snapshots that omit
`duration_ms`, `position_ms`, or `position_age_ms`; these fields may explicitly
be `None`. Previously those malformed snapshots passed validation and could
raise `KeyError`. Volume gestures also retain their own press/release ordering:
rapidly releasing and pressing the same button sends press, release, press,
including when the first press is still in flight. Completed quick taps each
retain their release; a release awaiting retry still blocks newer commands.
Wi-Fi failures honor their retry deadlines, releasing an inactive volume button
does not stop the direction still being held, and accented metadata maps to the
correct display characters. Empty or invalid album metadata clears the previous
artwork identity so Retry cannot restore a stale cover.

Artwork responses now use the public bounded `fetch.AsyncFetch` API, with a
32 KiB JSON limit, 128 KiB JPEG limit, 10-second inactivity timeout, and a
45-second overall budget checked between cooperative steps. Cancellation resets
the request and closes its socket. Only a completed, bounded response is written
to a temporary file. Firmware lacking this API shows a bounded-fetch-required
message; cached artwork and audio controls remain available. The upstream API
can block during DNS, which the cooperative deadline cannot preempt.

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
- Settings provide Power, Pair, EQ, confirmed bond erasure, Wi-Fi/artwork retry, and BLE volume-remote pause/enable when a fresh BLE status permits the request.

The status line reports whether a command was sent and whether a reply arrived. A reply is delivery feedback, not proof that playback or volume changed. BLE Pause/Enable is reported as Waiting, Confirmed, Failed, or Unconfirmed and only confirms when a newer BLE status echoes the matching request client/sequence; null correlation means there is no current Wi-Fi-owned BLE request.

## Configuration and network

Add these values to the badge's existing `secrets.py`; never put real credentials in this app or commit them:

```python
WIFI_SSID = "your network"
WIFI_PASSWORD = "your password"
BM83_HOST = "192.168.1.50"  # the audio unit's IPv4 address
BM83_PORT = 8767             # optional; defaults to 8767
BM83_KEY = "64 lowercase hex characters shared with the audio unit"
```

The BM83 unit and badge need LAN connectivity. Automatic cover downloads also need internet access. Missing settings, Wi-Fi failures, unavailable units, missing artwork and unsupported/progressive JPEGs are shown in the app rather than treated as success. The simulator cannot use sockets or HTTPS; `inject_sample_state()` can be called from its REPL to preview Now Playing layout.

## BMW1 details

Datagrams use the `BMW1.` prefix, a 16-byte HMAC-SHA256 tag, and UTF-8 JSON. The app verifies the tag before decoding JSON, accepts only replies from the configured IPv4/port, serializes one command at a time, retries the same sequence, and preserves a pending volume release ahead of other commands. Timed-out non-idempotent commands are not replayed under a new client. Status snapshots expire after six seconds; elapsed time advances only for a fresh playing snapshot whose source clock is advancing and remains within the source-age limit.

Artwork uses exact artist/album identity, a MusicBrainz score threshold of 95, unique release-group matches, a minimum 1.1-second MusicBrainz request interval and bounded response/cache sizes. Requests are HTTPS-only and limited to MusicBrainz, Cover Art Archive, Archive.org and Deezer hosts. The badge's `fetch` does not follow redirects, so the app follows at most three itself within that same allow-list. A busy MusicBrainz (HTTP 429, 502, 503 or 504) is retried up to three times at the same request interval before the app reports that artwork is unavailable; Settings then offers a retry. Artwork data is untrusted; only matching artist/album data and baseline JPEGs with bounded dimensions are used.

The [referenced upstream fetch implementation](https://github.com/pimoroni/tufty2350/blob/ee84772fb7f7d5424e9593029caba815c6f89c80/modules/common/fetch.py)
uses `CERT_NONE`: its HTTPS connection does not authenticate server certificates.
The app's URL allow-list does not replace certificate verification. Downloaded
metadata and images are treated as untrusted data; verified TLS on a physical
badge has not been established by this import.

## Host tests

Run these dependency-free tests from the repository root:

```bash
python3 -m unittest discover -s tests -p 'test_badge_bm83*.py'
```

The test files locate `addons/universe-badge/apps/bm83_remote` in the BM83
repository or `badge/apps/bm83_remote` in the Universe workshop repository.
Tests exercise authentication, malformed input, playback freshness, correlated
BLE confirmation, artwork validation, and a fake UDP socket. They do not execute
the badge entrypoint, contact networks/devices, or test a receiver. No receiver
interoperability test was executed. Badge UI rendering and actual button/audio
behavior still require separately authorized physical-device validation.

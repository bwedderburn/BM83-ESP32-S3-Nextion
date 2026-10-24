# CrowPanel Now Playing validation

Tested 2026-10-24 with the audio-unit ESP32-S3 running CircuitPython 10.3.1
and the existing 7-inch CrowPanel ESP32-S3 remote.

## Implemented behavior

The audio controller forwards cached BM83 metadata, playback state and genuine
position samples over the existing ESP-NOW link. CrowPanel has a Now Playing
page with title/artist/album, elapsed/total time and a display-only progress bar.
Utility controls are on Settings; transport and Volume -/+ remain available.
Artwork is a placeholder; no image acquisition or arbitrary-position seek is
implemented. This feature requires no host helper application.

Complete CRC-checked snapshots, bounded queues, sequence/session handling,
source-age limits and explicit invalidation prevent partial or stale data from
being displayed as current. AVRCP INTERIM notifications seed state without
clearing the track or re-registering; CHANGED notifications complete and rearm
the registration. No additional BM83 metadata polling is introduced.

## Host verification

- 534 tests passed, including the actual CircuitPython MPY build test.
- Python-to-C++ protocol tests cover malformed/lost/reordered fragments,
  duplicate/replayed sequences, reboot sessions, UTF-8 limits, pause/seek,
  unknown timing and counter wrap.
- Publisher tests cover send completion, pacing and multipart starvation.
- Fatal Python lint passed with generated build/dist capture artifacts excluded.
  The repository's nonfatal style pass retains warnings.
- CrowPanel PlatformIO build passed: RAM 100,856/327,680 bytes (30.8%),
  flash 1,163,361/3,145,728 bytes (37.0%).

## Hardware verification

Both firmware updates were backed up and installed. Controller files were
read back and matched to source; no other original controller files changed.
The CrowPanel app at 0x10000 was independently verified after writing. Its
first 64 KB matched the complete pre-update rollback, preserving bootloader,
NVS, partition table and OTA selection data.

The user confirmed on the physical displays with iPhone playback:

- Audio and Nextion metadata/advancing clock continued working after updating.
- CrowPanel showed correct title, artist, album, elapsed/total time and progress.
- CrowPanel pause held both clocks stopped for five seconds; resume worked.
- CrowPanel Next changed the track correctly.
- Seeking on the iPhone moved both displays to the new position.

CrowPanel serial logs recorded 22 delivered control tokens, stable memory and
continuous uptime during these checks. Controller receive heartbeats remained
healthy during playback. One host USB-console capture lost its device handle;
the same console reappeared and passive capture resumed. The physical playback
checks passed; a continuous USB capture across that interval is not available.

Windows verification is pending. Mac support is optional and is not claimed.
Battery-powered dim/sleep/wake behavior has host coverage but has not been
retested physically in this session.

Local backups, build provenance, installed hashes, serial captures and dated
physical-check records are retained under `build/crowpanel-now-playing/`.
That folder is intentionally excluded from Git.

## Remaining release consideration

The controller allows one outstanding ESP-NOW frame, with a minimum 40 ms
between sends. CircuitPython's native API can nevertheless retry for up to
two seconds on a driver memory-allocation failure. The observed playback
checks passed; they do not prove the absence of that vendor-level failure in
every radio or memory condition.

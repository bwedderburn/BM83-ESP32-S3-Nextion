# CrowPanel startup recovery and badge artwork validation

This candidate addresses the owner's first receiver-enabled check after the
native SHA cleanup update. Initial badge connection, transport controls,
HOME/reopen and Nextion playback worked. CrowPanel required **Retry both** after
startup; badge STATUS and artwork subsequently alternated between working and
unavailable before recovering. That check did not pass physical acceptance.

## Changes

CrowPanel treats validated playback **or** BLE-status packets as transport
health, without treating BLE status as fresh playback metadata. After pausing
Wi-Fi to restore local controls, it can rejoin its already committed access
point when the audio-unit link is stable. This recovery never sends NET_RETRY
and never restarts the audio controller. It has three attempts per unstable
episode, bounded backoff, and a 30-second stable-link rearm. Trial profiles,
manual disable, setup transactions and sleep transitions retain their guards.
The correct-access-point check is cached for at most one second; disconnect,
new IP, profile and sleep transitions invalidate the cache immediately.

The badge defers artwork start, retry, clock recovery and download pumping
until no authenticated UDP transaction, queued control or held-volume release
is outstanding. It performs one background operation per frame and draws using
a fresh clock afterward. The UDP reply deadline remains 600 ms. DNS and existing
NTP internals can still consume an indivisible interval; this does not promise
fully nonblocking networking.

The installed badge's frozen downloader was observed creating a TLS context
without certificate verification. The app adapter retains its HTTP parser but
replaces connection creation with CERT_REQUIRED, hostname validation, the
existing project CA roots and a valid UTC clock. It has no HTTP, insecure-TLS or
date-check fallback. The deterministic DER store contains the same 118 roots as
the retained project sources, with their licenses; no system trust is changed.
On a cache miss with an invalid clock, the app can use the badge's existing NTP
setter at most three times, in separate idle turns. Cached artwork works without
clock synchronization. Manual local retry rearms bookkeeping only.

## Host and native checks

- Complete BM83 host suite: **1,503 passed, one skipped, 157 subtests passed**.
- Focused badge/receiver/native-hash checks: **198 passed, 125 subtests passed**;
  dependency-free badge discovery: **135 tests passed**.
- Independent badge review found no blocking source findings. Strict Python
  lint, Bandit and the pinned HYB26 app validator passed; validator warnings: zero.
- CrowPanel policy/parser sanitizer checks and host recovery tests passed.
- Two clean offline CrowPanel builds using the frozen historical dependency
  set produced identical application, ELF, partition and bootloader artifacts.

CrowPanel application: **1,633,472 bytes**, SHA-256
`0afa260cfe6ecafbf4c270680d1a00b656ae4d899da15e17d033971879ce861d`.
The 4 MiB layout retains the 3 MiB app partition at `0x10000`; NVS, OTA
metadata, bootloader, partition table, SPIFFS and coredump are outside the write.
The 62-file frozen production source manifest is
`652dd5958f712e0ef22d42834260108f09250d614561ca35b7422ebbf2d4bf02`.

The actual badge is RP2350, MicroPython 1.29.0-preview. Its TLS loader accepts
individual DER certificates positionally. Native checks established that
successive loads append roots to one context, valid HTTPS works, and incorrect
root, hostname and expired-date cases are rejected. All 118 roots loaded with
verification required in 95 ms. Clock recovery from a deliberately invalid RTC
worked in 122 ms using the existing NTP timeout and server.

A RAM-only probe then ran the exact app adapter against the badge's actual
frozen HTTP parser, using the exact public DER-store bytes through an in-memory
file seam. An invalid clock was refused before CA loading or DNS. App clock
recovery succeeded in 121 ms. Verified HEAD requests to MusicBrainz and
archive.org both returned HTTP 200. The largest measured update steps were
275 ms and 226 ms; one cached CA context served both requests. These are
component compatibility measurements, not a complete app or stability pass.

## Delivery and acceptance boundaries

The native BM83 image and three receiver application files were already
installed and readback-verified separately; see
`tools/circuitpython-runtime/VALIDATION-HASH-CLOSE-2026-11-01.md`. The original
failed native diagnostic is preserved alongside the successful follow-up.
Ctrl-C/VM teardown remains a distinct unresolved fault and is not used during
normal operation or the physical acceptance run.

The owner approved the separate CrowPanel application update. Initial attempts
stopped at a read-only identity check, before any flash write. A long cable
intended mainly for charging was replaced, but cable causation is unproven.
The delivery tooling also needs the explicit retained-stub option: esptool
5.6.0's `--after no-reset` can issue a software reset to exit its RAM helper;
`--after no-reset-stub` leaves that helper running. These behaviors must not be
described as equivalent.

A five-minute receiver diagnostic had fresh authenticated replies and advancing
matching playback, but opening CrowPanel's diagnostic serial port coincided
with a real panel reboot. The five-minute window began afterward; it is not the
required uninterrupted 30-minute physical acceptance run. Future observation
must account for serial-open/close effects rather than infer electrical silence
from a zero-byte-write counter.

Updated badge installation, CrowPanel flash/readback and boot, unassisted
startup recovery, live uncached artwork/control checks, and a receiver-enabled
uninterrupted 30-minute window remain pending. Private backups, hardware
identifiers, credentials and raw device captures are deliberately outside Git.

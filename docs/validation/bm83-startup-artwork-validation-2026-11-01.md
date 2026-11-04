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
`--after no-reset-stub` leaves that helper running. The delivery used 115200 baud
consistently, with no automatic reset or rollback.

Two initial matching full-flash backups revealed valid existing OTA boot
records and non-erased data beyond the parsed original app. The initial empty
metadata/tail assumptions were rejected. Independent checks of IDF 4.4.7 and
the actual saved bytes established that the records select the sole OTA0 app,
the original image is valid, and the retained bootloader is byte-identical to
the candidate build's bootloader. The final guard was restricted to this exact
original full-flash, OTA, app-slot and original-image snapshot, and obtained two
fresh matching backups before writing. It did not generalize an exception for
unknown populated boot records or unknown app data.

The candidate is 80 bytes longer than the original valid 1,633,392-byte image.
Its sector erase extent ends at `0x19f000`. All 912 bytes between the old image
end and that boundary were already erased; non-erased retained data begins at
the boundary. Verification therefore protects every byte outside
`[0x10000, 0x19f000)`, a stricter boundary than the entire application slot.

The single app write from the Mac completed in 97.9 seconds and passed
esptool's written-data hash check. The first full verification read then failed
on a 4,063-byte SLIP frame where 4,096 bytes were required. Its empty output and
failed report remain preserved. This identifies a transfer failure, not its
electrical or software cause. No automatic second flash or reset occurred.

A separately reviewed verification-only helper performed one new complete
4 MiB read, with fresh identity/security checks before and after. It rechecked
the old evidence unchanged and compared the entire readback byte for byte with
the original snapshot plus only the new candidate and erased final-sector
padding. The complete result matched the exact private reference image; its
device-specific full-flash digest remains outside Git.
Bootloader, partition table, NVS/Wi-Fi settings, OTA metadata, retained unknown
app-slot data, SPIFFS and coredump bytes were unchanged. This establishes the
Mac flash and preservation result for this delivery; it does not establish a
general cure for the occasional USB transfer failure.

The owner then pressed normal RESET on CrowPanel and confirmed current track,
advancing time and artwork without **Retry both**. This startup check had the
audio controller already playing; it is not a complete cold-start-order matrix.

The badge's 15-file app was installed from BM83 commit `9cf00e8`, byte-identical
to the Universe mirror at `c785801`. A fresh complete badge backup and the
previous app backup were verified. All 470 current files outside the app stayed
unchanged, including credentials, other apps, saved state and artwork cache.
The badge was safely ejected. The owner confirmed metadata/time/artwork,
pause/resume, next/previous, volume and HOME/reopen, with Nextion still updating.

A five-minute receiver diagnostic had fresh authenticated replies and advancing
matching playback, but opening CrowPanel's diagnostic serial port coincided
with a real panel reboot. The five-minute window began afterward; it is not the
required uninterrupted 30-minute physical acceptance run. Future observation
must account for serial-open/close effects rather than infer electrical silence
from a zero-byte-write counter.

The updated acceptance observer separately records requested operations and
detected boot/restart evidence. It opens each serial connection once, requires
20 continuous seconds of fresh matching metadata and advancing clocks before
arming, and rejects post-arm boots, unit/uptime changes, stale source/transport
data, clock drift, UART faults, route/helper/volume changes or a six-second
observer scheduling gap. The final timestamp repeats freshness checks and
requires at least 1,800 actual monotonic seconds; cleanup time cannot extend a
short run into a pass. It sends no serial bytes or control commands.

The receiver-enabled run armed at **2026-11-02 09:43:57 UTC** and passed after
**1,800.010162 uninterrupted monotonic seconds**, ending at about 10:13:57 UTC.
There were no detected post-arm boots, UART degradation or UART silence events.
The largest observer scheduling gap was 214.7 ms. Route, helper process, volume,
metadata/source freshness and clock-progress checks remained within their
specified bounds. The final endpoint independently rechecked those conditions.

Within the timed window, the saved records contain **1,767 unique fresh
authenticated replies**, **1,762 matching replies** and **seven natural track
changes**. Another 33 replies and one track change belong to preflight and are
not timed-window evidence. The last-send reply latency was 167 ms at the 95th
percentile; whole-transaction latency was 216 ms at the 95th percentile.

This was a bounded health pass, not a zero-retry network result. Two raw panel
clock decreases correspond to old/new track-duration handoffs, not established
same-track rewinds. The five-second periodic panel clock reports straddled
those transitions; source drift recovered within the unchanged six-second
sustained-mismatch limit. The preserved raw drift maximum compares clocks from
different tracks and must not be presented as steady-state timing accuracy.
Five periodic host snapshots also recorded `STATUS: no reply` while cached
playback remained fresh and matching. They are real transient observations,
not a complete failed-transaction count or proof of the badge's UI behavior.
The longest successful whole transaction was 625 ms across four sends, with
125 ms since the final send. The transport processes buffered replies before
its nominal 600 ms timeout check; not every whole transaction was below 600 ms.

After the run and diagnostic release, the owner confirmed that Music was still
audible, all three screens showed current metadata, advancing time and artwork,
and badge SELECT still paused and resumed playback without Retry both, power or
reset. Combined with the earlier controls/HOME checks, this passes the scoped
Mac-route delivery and 30-minute physical acceptance gate.

The independent host STATUS client cannot establish actual badge UI, artwork,
button or audio behavior by itself. Its raw host result therefore retains
`overall_physical_acceptance_passed=false`; the owner's start/end observations
and the host pass are combined in a separate private acceptance record rather
than rewriting that evidence. Private backups, hardware identifiers,
credentials and raw device captures remain outside Git.

## Remaining limits

- The Ctrl-C/VM teardown fault remains a separate unresolved maintenance issue;
  normal operation and this run did not invoke it.
- This is not a zero-retry or zero-packet-loss network result. The transient
  host observations and timing semantics above are retained explicitly.
- CrowPanel startup was verified with the audio controller already playing.
  Every cold-start order, power interruption and prolonged outage has not been
  physically retested by this window.
- This Mac route uses the existing metadata helper. Helper-free AVRCP delivery,
  Windows/Pi behavior and cross-platform BLE handoff are separate validation
  scopes, not implied by this result.
- The successful complete readback does not identify or cure the cause of the
  earlier USB framing failure. Future updates still require complete verified
  backups, a valid rollback and protected-range readback.

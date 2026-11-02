# Native Hash lifetime validation — 2026-11-01

This record distinguishes an observed allocation defect and host validation
from delivery or physical acceptance. Raw device captures, machine details,
credentials and generated binaries remain outside Git.

## Original application and bounded diagnosis

The owner resumed hardware testing. Before enabling the badge receiver, the
installed original entrypoint and all 20 project libraries were verified
against the true original application. A 1,800-second uninterrupted baseline
completed with six natural Music track changes, fresh CrowPanel playback and
advancing source positions. There were no recorded UART degradation events or
native faults. The owner separately confirmed the actual Nextion and CrowPanel
title/artist and advancing time. The badge remained at its launcher.

On the stopped controller, two idle native-heap readings were identical. Eight
completed native SHA-256 operations followed by Python garbage collection left
1,060 bytes unrecovered; another 16 left 1,920 bytes unrecovered. This establishes
an allocation lifetime defect on the installed runtime. It does not by itself
prove that every earlier radio failure had the same cause. Native 8-bit heap
and Python GC heap are distinct observations; DMA-specific metrics were not
available through the public Python API.

A reviewed Adafruit software-only SHA-256 alternative passed host vectors and
wire-compatibility checks, but actual HMAC measurements were approximately
175.6 ms, 265.4 ms and 711.8 ms for 64-, 256- and 1,200-byte synthetic payloads.
The maximum case exceeds the existing 600 ms reply deadline and provides no
margin against the configured UART receive-buffer wire-time limit. That
alternative was rejected and is not part of this change or deployment.

The original application was subsequently restarted once through the verified
hard-reset path after a safe host unmount. Existing metadata, playback and the
encrypted BLE connection returned without changing application files, profiles,
keys or bonds. The separately observed VM teardown fault remains distinct;
this candidate does not establish that soft reload is safe.

## Candidate and reproducible build

The native patch adds deterministic `Hash.deinit()`, safe finalization,
closed-operation checks and PSA error-path cleanup while preserving repeated
digest and later update semantics. The receiver releases each hash in `finally`
and refuses unsupported embedded runtimes before opening its listener or
creating a native probe hash.

- CircuitPython: `c9dee12beed76e4ffa11d2d6d99ff104fc976c3a` (10.3.1).
- IDF: `2b900d1222cfce5dfa340ed99375af69ec1ee192`.
- NimBLE: `7075927f97c648af650a288e94a8c80dd7f00c27`.
- Native patch SHA256: `03b79f04f9d4ac3575512647856d9b7ce341acc45b83a27a516ec22527932a14`.
- Immutable builder: `sha256:7adf55fa8693c225abe0467f02ffcbda84bd086df2e2e3957c7fae9499d83816`.
- Application: 1,947,056 bytes in the unchanged 2,097,152-byte partition.
- Application SHA256: `a081b8b2bbd5d90c4dbb5007e48edad5aa632a37ecfe5b27baaa61646edff1f4`.
- ELF SHA256: `e42c6da41a294130fe2a20472321e852276ecc2c1bbfd5a51c6debe65a40f491`.

Two fresh, network-disabled build containers produced byte-identical output for
all ten recorded artifacts and equal recorded provenance. Whole-source checks
ran before and after both builds; the repeat comparator alone does not attest
to the truth of source pins. Existing compiler, dependency, board, bond-count,
CCCD, NVS persistence, partition and deterministic web-asset settings remain
unchanged. The six complete native source outputs and new patch digest are
explicitly guarded. Original build images and evidence are retained.

## Host validation

- Full pinned suite: 1,469 tests and 116 subtests passed, real compiler enabled.
- Native/receiver/provenance preflight: 181 tests passed, including the patched
  HAL compiled against a bounded ownership/error model. This is not the actual
  ESP32 hardware backend or MicroPython collector.
- Updater: 64 tests passed, including an observed failed-before/passed-after
  missing-approval regression and backup/security/readback refusal cases.
- Strict lint and policy checks passed. Production Bandit had no medium/high
  findings; one pre-existing low finding remains.
- Both generated images passed the offline ESP32-S3 application validator.

## Approved native installation and target checks

The owner explicitly approved the native update and entered ROM download mode.
The guarded updater verified the target identity, 8 MiB flash, unsigned and
unencrypted configuration, exact application and partition table, and a
validated original rollback image. Two independent full-flash backups matched.
The application image above was written only within the 2 MiB application slot;
a third full-flash readback verified the new image and every byte outside that
slot unchanged. Bootloader, partition table, NVS, bonds, profiles and files were
outside the write area. The owner then reset the controller into CircuitPython.
See [runtime flash guards](../../docs/reliability/RUNTIME-FLASH-GUARDS.md).

The first stopped-runtime probe confirmed the new capability, SHA-1/SHA-256
known answers, repeated digest/update, idempotent deinitialization and closed
operation errors. Its 128 explicitly closed hashes showed zero native loss.
Its strict first-collection acceptance failed: one discarded native context
retained 120 bytes at that reading and recovered fully by the last reading.
The original helper collected internally, so its label suggesting a second
collection actually followed three collections. That failed result is retained
unchanged. A later 33,048-byte allocation step in that first experiment remains
unattributed; it is not presented as a permanent leak or explained away.

A separate, fixed follow-up used the exact production hash/HMAC helpers,
public vectors, a no-Hash allocation control and explicit collection labels.
It warmed the same maximum workload sizes before establishing the baseline.
The predeclared decision required every second-collection native-free value to
meet its batch, phase and common warm baseline; the third collection could not
rescue a failure. Actual results were:

- 256 discarded hashes: each batch held 32 × 120 bytes before collection and
  released all of it by the first recorded post-batch collection.
- 256 explicitly closed hashes, 384 measured production HMACs and the no-Hash
  controls: zero native loss even before a post-batch collection.
- All 26 measured batches and the complete warmed run: zero native loss.
- 1,446 total native hash constructions including fixed warmup; 81 explicit
  collections. Automatic collection remained enabled.
- Maximum measured HMAC: 4.425056 ms; complete diagnostic: 4.642639161 seconds.
- Matching largest-block brackets throughout; derived usable Python GC-pool
  capacity stayed 62,976 bytes. Overlapping Python/native figures are not
  added together or represented as DMA-specific headroom.

The scoped native hash checks passed through a separate aggregate record that
binds the new raw measurements and preserves the original failure. The observed
VM-teardown HARD_FAULT remains unresolved; these results do not establish safe
soft reload.

## Receiver delivery and remaining physical acceptance

The exact three-file application update (`main.py`, `artwork_wifi.mpy`, and
`badge_remote.mpy`) was hash-verified against the committed reproducible build.
The tested receiver source is commit `95dde864b08d44b07bfbe75d26f583fa316a2099`.
The complete sixty-file snapshot verified every other file unchanged. After a
safe host unmount and one controller hard reset, Wi-Fi, the metadata bridge and
the authenticated badge receiver all reported ready without a startup fault.
Apple Music's saved playback state, route and volumes were restored.

A read-only authenticated client received nine fresh status samples matching
Music's title and artist, with genuinely advancing cached source positions.
This did not send playback, volume, power, pairing or retry commands.

Physical badge controls, actual screen observations and a new uninterrupted
1,800-second receiver-enabled run remain pending. CrowPanel's cold-start join
and shared retry behavior, native AVRCP without the helper, VM teardown and
cross-platform BLE handoff are separate gates. No broad hardware or platform
acceptance is inferred from this native or client-level record.

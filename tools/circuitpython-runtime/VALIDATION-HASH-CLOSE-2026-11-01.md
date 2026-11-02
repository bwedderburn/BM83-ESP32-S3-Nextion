# Native Hash lifetime candidate — 2026-11-01

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

## Host validation and remaining delivery gates

- Full pinned suite: 1,469 tests and 116 subtests passed, real compiler enabled.
- Native/receiver/provenance preflight: 181 tests passed, including the patched
  HAL compiled against a bounded ownership/error model. This is not the actual
  ESP32 hardware backend or MicroPython collector.
- Updater: 64 tests passed, including an observed failed-before/passed-after
  missing-approval regression and backup/security/readback refusal cases.
- Strict lint and policy checks passed. Production Bandit had no medium/high
  findings; one pre-existing low finding remains.
- Both generated images passed the offline ESP32-S3 application validator.

Native flashing has not yet been approved or performed for this candidate.
The guarded updater requires a separately scoped owner approval, exact tool
identity, physical chip/security/flash checks, two identical full backups, a
validated rollback image, and verification of every byte outside the app slot.
See [runtime flash guards](../../docs/reliability/RUNTIME-FLASH-GUARDS.md).

After a successful write, actual native cleanup, GC behavior, HMAC latency,
unchanged device files and bonds, real badge controls, fresh metadata and a new
1,800-second receiver-enabled observation are still required. No issue or
cross-platform acceptance gate is closed by this host record.

# BM83 controller and badge source — v1.0.0-rc.1

Status: local release candidate for review. No tag, GitHub Release, upload,
hardware installation, native-runtime update, or website deployment is made by
this preparation. Python package metadata uses `1.0.0rc1`; the proposed Git tag
is `v1.0.0-rc.1`.

## Included behavior and scope

The existing CircuitPython controller coordinates the BM83 audio module,
Nextion touchscreen, BLE consumer controls, and remote state/control paths.
The optional Universe badge app communicates with the controller's implemented
BMW1 authenticated UDP receiver. Playback metadata, press/release volume
gestures, connection handling, bounded work, and native hash cleanup admission
are represented by the existing source and host tests.

This candidate changes release metadata, licensing, and documentation. It does
not introduce new controller behavior or represent a new hardware validation
run. Historical documentation is corrected to recognize the receiver and the
later scoped Mac/helper acceptance record.

## Candidate downloads

- `bm83-controller-badge-v1.0.0-rc.1-source.zip`: selected controller and badge
  source, public trust assets and their notices, license, installation guidance,
  relevant validation records, compiler pin, and release-packaging helper.
- `bm83-controller-v1.0.0-rc.1-mpy.zip`: controller `main.py` and `boot.py`, public
  inactive example settings, and libraries built with pinned CircuitPython
  mpy-cross **10.3.1**, optimization **-O2**. The separate `BUILD_INFO.txt`
  identifies the exact source commit and compiler version.
- `SHA256SUMS.txt`: archive hashes. Each ZIP also contains a per-file
  `RELEASE-MANIFEST.json` with exact source revision and file hashes.

The source ZIP is intentionally a selected controller/badge package, not a full
repository export. CrowPanel firmware, native CircuitPython images, vendor
PDFs/installers/demo HEX packages, private profiles, credentials, caches, device
backups, and live captures are excluded. CrowPanel and native-runtime builds
remain separate artifacts with their own toolchains and validation.

The project's MIT license covers project-authored software; retained asset and
dependency notices continue to govern their respective material. The license
does not relicense unrelated vendor reference packages.

## Installation boundary

Preparation does not install anything. Before any later authorized controller
update, read `DEPLOYMENT.md`, preserve a verified complete backup and rollback,
and establish the exact runtime and supported route. Use source `.py` mode for
initial debugging and validation; switch to compiled libraries only after that
configuration is accepted. Keep `BUILD_INFO.txt`, release notes, manifests, and
the archive wrapper outside the device filesystem.

The evaluated installed `10.3.1-dirty` runtime has a separate Ctrl-C/VM teardown
fault. Its documented safe-mode/paused-runtime recovery safeguards take
precedence over general copy/soft-reload examples. This RC does not bundle a
replacement native runtime or authorize a reset or flash operation.

The optional badge client is installed separately on BADGER using its existing
launcher. Live BMW1 control needs compatible native hash cleanup support,
opt-in receiver configuration, and private enrollment on both ends. Never
reuse or distribute a real key, receiver profile, Wi-Fi configuration, or
saved device state in an archive.

## Validation and remaining limits

Local preparation checks and artifact provenance are recorded in
`docs/releases/RC-PREPARATION.md`. A completed host/build check proves its own
scope, not physical operation. The new portfolio 3D demonstration is also
separate browser evidence and is not part of this firmware package.

The existing `docs/bm83-startup-artwork-validation-2026-11-01.md` records
1,800.010162 uninterrupted monotonic seconds on a receiver-enabled Mac/helper
route, combined with owner observations of audible playback, all three screens,
advancing metadata/time/artwork, and badge pause/resume. It passes that scoped
delivery and physical acceptance gate. Its raw host result and separate owner
acceptance remain distinct evidence.

That result does not establish helper-free AVRCP delivery, Windows/Pi behavior,
all BLE handoff stacks, every cold-start order, power-interruption recovery, or
prolonged outages. Ctrl-C/VM teardown remains unresolved. Transient no-reply and
retry observations are retained; this is not a zero-loss network claim.

## Reproduction

Use the exact committed candidate revision in a clean checkout, the repository
compiler pin, and the instructions in `docs/releases/RC-PREPARATION.md`. Build
first, then package the exact commit. The packager refuses a dirty or mismatched
compiled provenance record and an unexpected compiled file set.

Local archives are review artifacts. Publishing, installing, or claiming a
stable all-platform release requires its own explicit decision.

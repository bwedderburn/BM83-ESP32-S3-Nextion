# BM83 Remote controller and badge source — v1.0.0-rc.1

Status: **[published GitHub prerelease](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/tag/v1.0.0-rc.1)**,
November 7, 2026. Annotated tag `v1.0.0-rc.1` points to
[`888b089c5a75865bb2bf8c76833f0eddc0fbd290`](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/commit/888b089c5a75865bb2bf8c76833f0eddc0fbd290);
Python package metadata uses `1.0.0rc1`. The published assets retain that exact
revision, independently of later documentation changes on `main`. Publication
performed no device operation. The earlier
[v0.1.0 source-preview prerelease](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/tag/v0.1.0)
remains available.

## Included behavior and scope

The ESP32-S3 CircuitPython controller coordinates BM83 UART control/metadata,
the Nextion touchscreen, relative BLE HID volume keys and remote state/control
paths. BM83 carries audio independently of the controller. The optional Universe
badge uses the implemented BMW1 authenticated UDP receiver. The full repository
also contains the separate CrowPanel firmware and native-runtime build recipe.

This prerelease includes the behavior already merged through `096706b`:

- Bond-preserving Disconnect, saved-host selection and bounded new-host pairing
  on CrowPanel and the badge, backed by the project native host-policy runtime.
- CrowPanel host labels and the revised Rename keyboard, badge battery status,
  and confirmed host-control results rather than radio-delivery inference.
- The Windows volume companion and authenticated launch receiver, with an
  **Open Windows app** action on CrowPanel and the badge.
- The existing playback, metadata, artwork and relative-volume paths, along with
  the startup and BLE enrollment/recovery changes recorded on `main`.

The release preparation itself changes packaging, metadata, documentation and
tests. It does not add a firmware change to that rebased controller/badge source.
Absolute-volume feedback and synchronized mute remain unavailable.

The native dependency recipe already includes PRs #196 (`idf-build-apps < 3.2`
on Python >=3.10), #197 (NVS generator 0.3.0), #199 (Click 8.5.0 with a local
compatibility override) and #200 (the optional linuxdoc 20260504 constraint).
The [November 3 dependency validation](tools/circuitpython-runtime/VALIDATION-DEPENDENCIES-2026-11-03.md)
records two matching native builds of the final combined dependency inputs.
Those builds are historical, uninstalled candidate evidence; this release
preparation does not rerun them or bundle a native image.

## Published assets

- [bm83-controller-badge-v1.0.0-rc.1-source.zip](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/download/v1.0.0-rc.1/bm83-controller-badge-v1.0.0-rc.1-source.zip): selected controller and badge
  source, public assets/notices, the Windows companion and launch receiver,
  license, release/deployment guidance, selected validation records and pinned
  application-build helpers.
- [bm83-controller-v1.0.0-rc.1-mpy.zip](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/download/v1.0.0-rc.1/bm83-controller-v1.0.0-rc.1-mpy.zip): controller `main.py` and
  `boot.py`, inactive example settings and project libraries compiled with the
  pinned CircuitPython **10.3.1** mpy-cross at **-O2**. Exact-revision build and
  compiler checks passed before publication.
- [MANIFEST.json](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/download/v1.0.0-rc.1/MANIFEST.json): per-file provenance for the source ZIP. Each ZIP also contains its own manifest; the compiled archive includes `BUILD_INFO.txt` identifying its source commit and compiler.
- [SHA256SUMS.txt](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/download/v1.0.0-rc.1/SHA256SUMS.txt): checksums for both ZIPs and the standalone manifest.

GitHub's asset digests and fresh downloads matched the verified local files
before and after publication. The [release page](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/tag/v1.0.0-rc.1)
also records all four asset hashes.

The selected source ZIP is an application package. CrowPanel source/binaries,
native CircuitPython images and build dependencies, vendor reference packages,
Adafruit libraries, private profiles, credentials, device backups and captures
are excluded. CrowPanel and native-runtime builds have separate toolchains and
acceptance gates. Retained asset/dependency notices govern their material; the
project MIT license does not relicense vendor references.

## Installation boundary

Before any later authorized update, read the
[deployment and rollback guide](docs/guides/deployment.md), preserve a verified
complete backup and establish the exact runtime and supported route. Use source
`.py` mode for initial debugging/validation. Keep archive wrappers, manifests and
`BUILD_INFO.txt` outside the device filesystem.

The documented installed `10.3.1-dirty` runtime has a separate Ctrl-C/VM teardown
fault. Its safe-mode/paused-runtime recovery safeguards take precedence over
general copy/soft-reload examples. Host selection requires the matching project
native host-policy runtime and application components; an older eight-bond
runtime alone cannot provide it. This RC does not authorize reset or flashing.

The badge app is installed separately using its existing launcher. Live BMW1
control needs compatible native hash cleanup, opt-in receiver configuration and
private enrollment. Windows launch uses separate private receiver configuration
and authentication material. Preserve existing keys, profiles, Wi-Fi settings,
bonds and saved state; none belong in a release archive.

## Validation and remaining limits

[RC preparation](docs/releases/RC-PREPARATION.md) records the reproducible host
and packaging gates. The tagged commit passed the
[Python 3.11/3.12/3.13 workflow](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42416862677),
[host security and reliability workflow](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42416862651)
and [Codacy analysis/SARIF upload](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42416862684).
Host tests, compiler checks and browser simulations each establish only their measured scope.

The [dated release handoff](docs/reliability/release-handoff-2026-11-07.md)
records the verbatim local gates, CI run IDs, all four asset hashes, compiler
digest, separate-session reproduction result and actual rc.1 gate order. It also
records repository cleanup and the packaging backlog's implementation on later `main`. Future candidates
are independently reviewed before tagging.

The [November 4 B-Intel Phase 1 record](docs/reliability/phase1-bintel-2026-11-04.md)
accepts its Windows Apple Music/BLE HID measured workload, owner screens/controls,
exact original restoration and automatic CrowPanel recovery. The
[November 5–6 Phase 2 record](docs/reliability/phase2-host-selection.md) separately
records exercised Windows enrollment/persisted pause, a saved Pi handoff,
CrowPanel/badge controls, Rename and Windows launch. A new qualified Phase 2
timing window and the broader enrollment, competing-host and power-order matrix
remain open.

The [reliability matrix](docs/reliability/README.md) continues to classify both
macOS/Apple Music helper-off and helper-on routes as **Not accepted**. The
[November 1 startup/artwork record](docs/validation/bm83-startup-artwork-validation-2026-11-01.md)
retains its historical observations and owner reports; they do not supersede
that current matrix. The Windows BM83 audio power-cycle wedge and native-runtime
teardown fault remain separate unresolved limits. No result here qualifies all
hosts or unattended deployment.

## Reproduction

Use the exact tagged commit `888b089c5a75865bb2bf8c76833f0eddc0fbd290` in a clean checkout and the canonical
`scripts/package_source_release.py` with `--scope controller-badge-source`.
[RC preparation](docs/releases/RC-PREPARATION.md) gives the commands and optional
compiled-artifact requirements. Later `main` documentation changes are outside
the tagged snapshot; use the release revision to reproduce its published assets.

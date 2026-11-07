# Releases

**[v1.0.0-rc.1](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/tag/v1.0.0-rc.1)**
was published as a GitHub prerelease on November 7, 2026, with Python package
metadata `1.0.0rc1`. Its annotated tag identifies exact source commit
[`888b089c5a75865bb2bf8c76833f0eddc0fbd290`](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/commit/888b089c5a75865bb2bf8c76833f0eddc0fbd290).
The [release notes](../../RELEASE_NOTES-v1.0.0-rc.1.md) and
[historical preparation record](RC-PREPARATION.md) describe the selected assets,
reproduction and remaining acceptance limits. This publication performed no
hardware run or installation; BM83 and CrowPanel stayed offline.

The published [v0.1.0 source-preview prerelease](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/tag/v0.1.0)
identifies the earlier revision `0f7dd18167c8634e26bcf7a7a0a7c946fbb6a49a`.
Its [original draft notes](v0.1.0.md) remain a historical record rather than the
active version plan. That prerelease does not establish physical acceptance of
this later controller/badge integration.

## Published assets

| Download | Purpose | Boundary |
| --- | --- | --- |
| [bm83-controller-badge-v1.0.0-rc.1-source.zip](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/download/v1.0.0-rc.1/bm83-controller-badge-v1.0.0-rc.1-source.zip) | Explicit controller/badge source, public assets/notices, Windows companion/launch receiver, license and selected release/deployment/validation files | Application source; native runtime, CrowPanel and Adafruit libraries are separate |
| [bm83-controller-v1.0.0-rc.1-mpy.zip](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/download/v1.0.0-rc.1/bm83-controller-v1.0.0-rc.1-mpy.zip) | Exact-revision controller entrypoints and project libraries built with pinned Linux amd64 CircuitPython 10.3.1 mpy-cross at `-O2` | Application artifacts; not a native flash image or installer |
| [MANIFEST.json](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/download/v1.0.0-rc.1/MANIFEST.json) | Per-file provenance for the source ZIP; the compiled ZIP contains its own manifest | Integrity/provenance; no signature or hardware qualification |
| [SHA256SUMS.txt](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/download/v1.0.0-rc.1/SHA256SUMS.txt) | Source/compiled ZIP and manifest digests | Compare downloaded bytes before use |

All four published downloads were compared with the inspected release assets
after publication and matched their SHA-256 digests. The exact asset hashes are
retained in the [preparation record](RC-PREPARATION.md#published-artifacts).
The canonical packager also retains an `application-source` profile for the
earlier controller-only preview; it is separate from this published RC profile.

Project-authored code uses the [MIT license](../../LICENSE). Public assets retain
their notices. Full repository archives also retain vendor reference material
under upstream terms; the project license does not relicense those files. The
selected application packages exclude vendor references and third-party libraries.

Source ZIPs read the exact reviewed Git commit using explicit allowlists. They
exclude local settings, enrollment profiles, Wi-Fi credentials, pairing data,
captures, backups, private keys and native flash images. Keep the settings example
inactive and preserve each installation's private configuration. A named archive
directory prevents opening a ZIP from writing directly over device files; the
archives must not be copied wholesale to a device.

## Reproduce the published RC assets

Use `scripts/package_source_release.py`, the canonical implementation for both
profiles. `scripts/prepare_release.py` is a compatibility entrypoint to the same
code; `--ref` is an alias for `--revision`. Start with a clean checkout of
`v1.0.0-rc.1` at exact commit `888b089c5a75865bb2bf8c76833f0eddc0fbd290`,
including its packager. Later `main` documentation commits are outside the
published inputs; packaging the current `HEAD` would describe a different source
revision. Choose a new host output directory; existing paths and symlinks are refused.

```powershell
python scripts/package_source_release.py --revision 888b089c5a75865bb2bf8c76833f0eddc0fbd290 --version v1.0.0-rc.1 --scope controller-badge-source --output C:\Users\brian\Downloads\BM83-v1.0.0-rc.1-source-assets
```

```sh
python3 scripts/package_source_release.py --revision 888b089c5a75865bb2bf8c76833f0eddc0fbd290 --version v1.0.0-rc.1 --scope controller-badge-source --output /absolute/new/BM83-v1.0.0-rc.1-source-assets
```

The command reads committed Git objects with replacement objects disabled and
rejects selected symlinks/submodules or missing inputs. It produces
`bm83-controller-badge-v1.0.0-rc.1-source.zip`, `MANIFEST.json` and `SHA256SUMS.txt`.
Sorted stored ZIP members, fixed timestamps/modes and canonical committed bytes
make repeat packaging independent of checkout line endings and compression-library
versions. Compare reproduced bytes with the published checksums; no rebuild or
replacement upload is needed to use the existing published assets.

Source-only packaging writes checksums for its ZIP and manifest. The published
checksum file also lists the compiled ZIP; reproducing that complete file
requires the combined source/compiled command in the preparation record.

For the optional compiled controller ZIP, follow
[RC preparation](RC-PREPARATION.md#optional-compiled-controller-assets). It requires
a build at the exact reviewed revision and an explicitly verified pinned compiler;
source-only review does not need a compiler. These commands perform no upload,
tag creation, device discovery, deployment or native flash operation.

## Validation and acceptance limits

The released commit passed the main-branch
[Python package](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42416862677),
[Host security and reliability policy](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42416862651)
and [Codacy Security Scan](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42416862684)
workflows. Host checks and publication retain separate physical boundaries.
The [reliability matrix](../reliability/README.md),
[B-Intel Phase 1 acceptance](../reliability/phase1-bintel-2026-11-04.md) and
[Phase 2 host-selection record](../reliability/phase2-host-selection.md) retain
their distinct scopes. The Windows Phase 1 result and exercised Phase 2 controls
do not accept all platforms, enrollment/power-order cases or a new Phase 2 timing
window. Both macOS helper paths remain **Not accepted** in the current matrix.

Native CircuitPython and CrowPanel images require their own exact source,
toolchain, layout, installed-configuration and hardware verdicts. The recorded
two native dependency builds establish historical build equality, separate from
current physical acceptance. Private device data and frozen manifests stay
outside public assets.

The reviewed source was integrated into `main` before publication, and the
candidate branch was retired. The tag and four published assets stay fixed at
`888b089`; later documentation updates do not change those bytes. Hardware
installation remains a separate decision governed by the deployment and
recovery instructions.

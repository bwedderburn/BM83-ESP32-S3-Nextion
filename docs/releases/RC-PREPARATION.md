# v1.0.0-rc.1 preparation and reproduction record

Python package version: `1.0.0rc1`. Published Git tag: `v1.0.0-rc.1`.
The [GitHub prerelease](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/tag/v1.0.0-rc.1)
was published on November 7, 2026, from exact commit
`888b089c5a75865bb2bf8c76833f0eddc0fbd290`. The candidate was rebased on
`main` at `096706b`, then reviewed, integrated into `main` and published. Its
`codex/bm83-release-candidate-20261107` branch has been retired. The earlier
[v0.1.0 source-preview prerelease](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/tag/v0.1.0)
and its [original draft notes](v0.1.0.md) remain historical. This record describes
the completed preparation and exact-version reproduction. Its commands generate
local artifacts without creating tags/releases, uploading or operating devices.

## Published artifacts

- [bm83-controller-badge-v1.0.0-rc.1-source.zip](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/download/v1.0.0-rc.1/bm83-controller-badge-v1.0.0-rc.1-source.zip)
- [bm83-controller-v1.0.0-rc.1-mpy.zip](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/download/v1.0.0-rc.1/bm83-controller-v1.0.0-rc.1-mpy.zip)
- [MANIFEST.json](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/download/v1.0.0-rc.1/MANIFEST.json)
- [SHA256SUMS.txt](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/download/v1.0.0-rc.1/SHA256SUMS.txt)

All four downloads were verified after publication against the inspected local
release assets, with matching bytes and SHA-256 digests:

```text
fdebb8918805f4746bbea98c294e1d7df45a075776061650cae90ce5cc8e94d7  bm83-controller-badge-v1.0.0-rc.1-source.zip
b5610d3c0a4e46146e11fd8a648efc89e97fa9452464139ae9fb794a7917afde  bm83-controller-v1.0.0-rc.1-mpy.zip
beb8018100eba91919745990a860a55105a5ae6b9e89bcb74059822aa072bbfb  MANIFEST.json
033010c2b1e20ca31df3d680123d2904ab9d78e228632c8666878d401a2431ac  SHA256SUMS.txt
```

## One canonical packager

At the released rc.1 tag, `scripts/package_source_release.py` owns both supported
source profiles:

- `--scope application-source` preserves the earlier controller-only preview.
- `--scope controller-badge-source` selects the expanded RC package, including
  controller/badge source, public assets/notices, the Windows companion and
  launch receiver, and the explicit release/deployment/validation files.

At that tag, `scripts/prepare_release.py` is a compatibility entrypoint to the
same implementation. Later `main` retired the shim and made `--scope` and
`--version` required; compiler arguments also require `--include-mpy`, and compiled
packaging requires both arguments before source reads. Current `main` also
refuses a requested revision whose committed packager differs from the executing
script, allowing CRLF/LF checkout conversion. Reproduce
the published files using their own tagged packager, preserving its original
allowlist and behavior. `--ref` aliases `--revision` in the canonical CLI.
The commands below specify the scope and version explicitly on both versions.

The packager reads committed Git objects with replacement objects disabled. It
selects explicit reviewed paths, requires the profile's expected inputs and
rejects symlinks, submodules, escaped paths and private material. Working-tree
edits, untracked files and generated source cannot enter the source ZIP.
The native build recipe/dependencies, CrowPanel firmware and vendor packages
remain outside this selected package. No device drive or serial port is used.

ZIP member order, stored entries, timestamps, modes, JSON and path separators
are fixed. Identical committed inputs and compiled bytes produce identical
archive hashes. The output directory must be new; existing files/directories and
output symlinks are refused. Choose a host path for review artifacts, never a
device filesystem.

## Reproduce source assets

Start from a clean checkout of the published tag, including its exact packager:

```sh
git clone --branch v1.0.0-rc.1 --single-branch https://github.com/bwedderburn/BM83-ESP32-S3-Nextion.git BM83-v1.0.0-rc.1-reproduction
cd BM83-v1.0.0-rc.1-reproduction
git rev-parse HEAD
```

The reported commit must be `888b089c5a75865bb2bf8c76833f0eddc0fbd290`.
Later documentation commits on `main` are outside the published inputs.
Packaging a later `HEAD` would record a different revision and produce different
source bytes. Choose a new host output directory below; neither command builds
or installs firmware.

```powershell
python scripts/package_source_release.py --revision 888b089c5a75865bb2bf8c76833f0eddc0fbd290 --version v1.0.0-rc.1 --scope controller-badge-source --output C:\Users\brian\Downloads\BM83-v1.0.0-rc.1-source-assets
```

```sh
python3 scripts/package_source_release.py --revision 888b089c5a75865bb2bf8c76833f0eddc0fbd290 --version v1.0.0-rc.1 --scope controller-badge-source --output /absolute/new/BM83-v1.0.0-rc.1-source-assets
```

Outputs are `bm83-controller-badge-v1.0.0-rc.1-source.zip`, `MANIFEST.json` and
`SHA256SUMS.txt`. ZIPs unpack beneath a named `BM83-Remote-v1.0.0-rc.1/` directory.
Inspect every member, license/notice, per-file hash and source revision. Compare
the source ZIP and manifest with the published checksums. Reproduction generates
local comparison artifacts; the existing release needs no rebuild or replacement
upload.

The source-only command writes two checksum entries, for the source ZIP and
manifest. The published `SHA256SUMS.txt` has a third entry for the compiled ZIP;
use the combined source/compiled command below to reproduce that complete file.

## Optional compiled controller assets

Source-only review needs no compiler. To add a compiled controller ZIP, use a
clean checkout of exact release commit `888b089` and follow the
[application build guide](../guides/building.md). First verify that the resolved
generated `dist/circuitpython` directory remains inside the intended checkout;
`build_mpy.sh` removes/recreates that generated directory. Keep the pinned
compiler outside release assets.

The optional compiled package requires the repository-pinned Linux amd64
CircuitPython 10.3.1 mpy-cross, used at `-O2`. Run this lane under Linux/WSL.
The committed compiler digest is
`aa74dcb51e51c1a70fd268dad9e05b40f72c29df3082f86c3a20665360e4acda`.
The supplied digest must match both `tools/mpy_cross_pin.env` and the actual
executable. Historical Windows compiler observations do not satisfy that pin.

After building, add the compiler path and its verified digest to the same
canonical command, with a new output directory:

```sh
python3 scripts/package_source_release.py --revision 888b089c5a75865bb2bf8c76833f0eddc0fbd290 --version v1.0.0-rc.1 --scope controller-badge-source --include-mpy --compiler /absolute/path/to/mpy-cross --compiler-sha256 <verified-compiler-sha256> --output /absolute/new/BM83-v1.0.0-rc.1-with-mpy
```

The packager requires matching `dist/BUILD_INFO.txt` source/compiler provenance,
the complete expected file set and verbatim source entrypoints/public assets.
It verifies the supplied compiler's bytes/version and recompiles committed
library sources at `-O2` to compare with `dist/`. A stale build is refused even
when application source has not changed since its recorded commit. The optional
output is `bm83-controller-v1.0.0-rc.1-mpy.zip` with its manifest/build record.
These checks validate application artifacts; they do not build or qualify the
native runtime, CrowPanel or physical audio/radio/screens.

## Provenance and historical evidence

The rebased tree retains the dependency updates merged as #196 (IDF-build-apps),
#197 (NVS generator 0.3.0), #199 (Click 8.5.0) and #200 (optional linuxdoc
20260504 constraint). Its active `security_build` inputs are:

| Input | SHA-256 |
| --- | --- |
| `requirements-build.txt` | `e0c1f8197c9a62b3a7ff875574036be301eee1a62008db4c58a947f9573a2f2b` |
| `espidf.constraints.v6.0.txt` | `0728b440d5b5f6fb517d954b74889bc9e8e4b1e079b1a92237f7e43036d4edc5` |

The [November 3 native dependency record](../../tools/circuitpython-runtime/VALIDATION-DEPENDENCIES-2026-11-03.md)
documents offline preflight and two matching native builds of these combined
inputs. The Click override is local compatibility evidence for the recorded
Linux/Python 3.11.18 builder. Historical `reference_tools` hashes, source/patch
pins, compiler manifests and frozen native artifacts retain their own scope;
they are not relabeled by this RC preparation.

The [B-Intel Phase 1 record](../reliability/phase1-bintel-2026-11-04.md) accepts
its November 4 measured and physical workload. The
[Phase 2 record](../reliability/phase2-host-selection.md) documents the exercised
November 5–6 controls and host handoffs, with further matrix/timing gates open.
The current [reliability matrix](../reliability/README.md) still marks both macOS
helper routes **Not accepted**. Earlier November 1–2 records remain historical
evidence; their test counts and artifacts do not describe this rebased revision.

## Completed validation and publication

The release commit passed the supported Linux Python 3.11/3.12/3.13 host suite,
fatal lint, production/packager Bandit checks, reliability policy and pinned
dependency audits. Packager checks exercised allowlists, refusal cases,
exact-revision provenance and repeatability. Source and compiled archive bytes
were reproduced through both entrypoints; Windows source packaging matched.

After integration, the exact commit passed the main-branch
[Python package](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42416862677),
[Host security and reliability policy](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42416862651)
and [Codacy Security Scan](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42416862684)
workflows. Codacy completed analysis and SARIF upload. The reviewed tag and four
verified assets were then published as a prerelease. No new native build or
hardware run was performed for publication; BM83 and CrowPanel remained offline.
Native/application installation and physical acceptance retain their separate
gates. Later documentation updates leave the released tag and asset bytes fixed.

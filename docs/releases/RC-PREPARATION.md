# v1.0.0-rc.1 preparation

Python package version: `1.0.0rc1`. Proposed Git tag: `v1.0.0-rc.1`.
The active candidate continues from `main` at `096706b` on
`codex/bm83-release-candidate-20261107`. The published
[v0.1.0 source-preview prerelease](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/tag/v0.1.0)
and its [original draft notes](v0.1.0.md) remain historical. These commands prepare
review assets; they do not create tags/releases, upload files or operate devices.

## One canonical packager

`scripts/package_source_release.py` owns both supported source profiles:

- `--scope application-source` preserves the earlier controller-only preview.
- `--scope controller-badge-source` selects the expanded RC package, including
  controller/badge source, public assets/notices, the Windows companion and
  launch receiver, and the explicit release/deployment/validation files.

`scripts/prepare_release.py` is a compatibility entrypoint to the same
implementation. `--ref` aliases `--revision`; it does not select a different
allowlist or output policy. Always specify the scope and version when preparing
release assets.

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

## Prepare source assets

Commit reviewed changes first. Substitute the full reviewed commit SHA and a
new host directory below; neither command builds or installs firmware.

```powershell
python scripts/package_source_release.py --revision <reviewed-commit-sha> --version v1.0.0-rc.1 --scope controller-badge-source --output C:\Users\brian\Downloads\BM83-v1.0.0-rc.1-source-assets
```

```sh
python3 scripts/package_source_release.py --revision <reviewed-commit-sha> --version v1.0.0-rc.1 --scope controller-badge-source --output /absolute/new/BM83-v1.0.0-rc.1-source-assets
```

Outputs are `bm83-controller-badge-v1.0.0-rc.1-source.zip`, `MANIFEST.json` and
`SHA256SUMS.txt`. ZIPs unpack beneath a named `BM83-Remote-v1.0.0-rc.1/` directory.
Inspect every member, license/notice, per-file hash and source revision before
publication. Reproduce into a second new directory to compare archive bytes.

## Optional compiled controller assets

Source-only review needs no compiler. To add a compiled controller ZIP, use a
clean checkout of that exact reviewed revision and follow the
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
python3 scripts/package_source_release.py --revision <reviewed-commit-sha> --version v1.0.0-rc.1 --scope controller-badge-source --include-mpy --compiler /absolute/path/to/mpy-cross --compiler-sha256 <verified-compiler-sha256> --output /absolute/new/BM83-v1.0.0-rc.1-with-mpy
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

## Current candidate gates

Run the relevant host checks against the finished candidate: the full supported
host suite, fatal lint, production/packager Bandit checks, reliability policy,
and the pinned dependency audits. Exercise packager allowlists, refusal cases,
exact-revision provenance and repeatability. Record the final commit, actual
platform/interpreter, pass/skip counts and archive digests in the maintenance
handoff; do not carry forward older counts as current results.

The GitHub push workflows target `main`, so a candidate-branch push alone does
not establish current CI results. Keep publication, native/app installation and
physical acceptance separate. The finished candidate requires owner review
before fast-forwarding `main`; this preparation does not authorize device access.

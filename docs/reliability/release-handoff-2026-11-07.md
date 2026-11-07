# Release handoff — 2026-11-07

The published [v1.0.0-rc.1 prerelease](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/tag/v1.0.0-rc.1)
uses exact source commit
[`888b089c5a75865bb2bf8c76833f0eddc0fbd290`](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/commit/888b089c5a75865bb2bf8c76833f0eddc0fbd290)
and Python package version `1.0.0rc1`. This dated record supplements
[DIRECT-MAINTENANCE.md](DIRECT-MAINTENANCE.md). Later documentation on `main`
does not change the released tag, source snapshot or asset bytes.

This is a repository and release handoff. BM83 and CrowPanel stayed offline
during this maintenance. Private profiles, credentials, backups and raw captures
remain outside Git. Native CircuitPython/CrowPanel builds and device operations
are outside this documentation change.

## Gates recorded for 888b089

The local gate results and CI run IDs are retained verbatim:

```text
Linux, Python 3.13: pytest 1705 passed, 4 skipped, 162 subtests; flake8 E9/F63/F7/F82 0; bandit clean; check_reliability_setup PASS; pip-audit clean
CI run IDs: 42416862677, 42416862651, 42416862684
```

These are the historical results for `888b089`, including its real pinned
application `.mpy` compiler lane. The Bandit gate used the configured production
and packager targets at medium/high severity (`-ll`). The clean dependency
audits covered the development, repo-health MCP and native-build requirement
manifests. They are separate from a native-runtime build or physical acceptance.

| Workflow at 888b089 | Run ID | Result |
| --- | --- | --- |
| [Python package](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42416862677) | `42416862677` | Passed: Python 3.11, 3.12 and 3.13 |
| [Host security and reliability policy](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42416862651) | `42416862651` | Passed |
| [Codacy Security Scan](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42416862684) | `42416862684` | Analysis and SARIF upload passed; this verdict does not assert zero findings |

The gates run for this documentation change are recorded separately in its
commit message. The historical counts above are not relabeled as a new run.

## Published assets and compiler

The four asset SHA-256s are:

```text
fdebb8918805f4746bbea98c294e1d7df45a075776061650cae90ce5cc8e94d7  bm83-controller-badge-v1.0.0-rc.1-source.zip
b5610d3c0a4e46146e11fd8a648efc89e97fa9452464139ae9fb794a7917afde  bm83-controller-v1.0.0-rc.1-mpy.zip
beb8018100eba91919745990a860a55105a5ae6b9e89bcb74059822aa072bbfb  MANIFEST.json
033010c2b1e20ca31df3d680123d2904ab9d78e228632c8666878d401a2431ac  SHA256SUMS.txt
```

The pinned Linux amd64 CircuitPython **10.3.1 mpy-cross**, used at **-O2**, has
SHA-256:

```text
aa74dcb51e51c1a70fd268dad9e05b40f72c29df3082f86c3a20665360e4acda
```

The [release guide](../releases/README.md#published-assets) links the four
downloads. The standalone manifest describes the selected controller/badge
source ZIP; each ZIP also contains its own manifest, and the compiled controller
ZIP includes its exact-revision `BUILD_INFO.txt`. Native runtime images,
CrowPanel images, vendor packages, Adafruit libraries and private files are
outside these selected application packages. The three-entry published
`SHA256SUMS.txt` covers both ZIPs and the standalone manifest; its own digest is
recorded above.

## Independent reproduction

The independent result supplied by the owner for this handoff is recorded
verbatim:

> a separate Linux session rebuilt all four assets from 888b089 with the pinned compiler and matched the published bytes exactly.

This records the separate session's result. The current documentation update
does not repeat that build. Application compilation and packaging reproduction
remain separate from native CircuitPython/CrowPanel compilation and live
radio/audio/display acceptance.

Published assets are reproduced with the packager at their own tag. For rc.1,
use a clean checkout of `v1.0.0-rc.1` / `888b089`, including its packager and
compiler pin. Later `main` documentation is outside that snapshot. Follow the
[exact-version reproduction record](../releases/RC-PREPARATION.md); use the
combined source/compiled invocation to reproduce all four published files.

## Gate order actually used for rc.1

1. The local gates above passed, and the owner approved fast-forwarding `main`
   from `096706b` to `888b089`. The normal push then started main-branch CI.
2. All three recorded main workflows completed successfully. The owner then
   explicitly authorized the tag and prerelease for that exact commit.
3. The annotated `v1.0.0-rc.1` tag and prerelease were created using the local
   gates, green main CI and owner decision. All four uploads were checked
   against their digests and downloaded bytes before and after publication.
4. A subsequent independent release review found no defect. That release
   review was retrospective; it followed the tag and prerelease.

**Future candidates must receive independent review before tagging.** Review
the exact candidate commit, selected profile, compiler/build provenance,
manifests, release notes and supported reliability claims; resolve findings and
record the outcome. Complete the applicable local gates and green main CI,
then record the owner's release decision before creating the tag and publishing.
The [versioning and final-release criteria](../releases/README.md#version-line-and-final-v100-gates)
tie final `v1.0.0` to the platform rows and remaining acceptance gates.

## Repository cleanup recorded on 2026-11-07

- **92 pre-existing branches were deleted** during the repository cleanup.
  PR-backed history and the owner's retained patches/bundle preserve the
  recorded recovery routes; branch deletion was not a claim that every tip
  had been merged into `main`.
- The owner narrowed ruleset **11607796**, “Copilot review for default branch,”
  to the **default branch** by removing its all-branches target. Feature-branch
  updates and deletions no longer inherit that all-branches restriction. This
  maintenance did not change protection, credentials or approval settings.
- `recovered_src/` was removed from `main` in
  [`096706b`](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/commit/096706b77d4a49b6046fe2027cb9c6fe65374dc2),
  with its live layout/scanner references. Deliberate historical mentions remain.
- The original `codex/bm83-release-candidate` branch and the rebased
  `codex/bm83-release-candidate-20261107` branch were retired. The original
  candidate was preserved outside the repository; the rebased candidate was
  contained in `main` before its remote/local branch and worktree were removed.
- **`main` is the only branch locally and on origin.** The retired worktree's
  ignored/untracked content was archived and verified before removal. Private
  files, frozen evidence and the main checkout's `.claude/` and `tmp/` remain
  preserved outside tracked release assets.

## Tracked backlog — deferred

These are future packaging and host-policy tasks. This handoff records them
without implementing them or changing the published tag, packager or assets.

- [ ] Make `--scope` and `--version` required in
  `scripts/package_source_release.py` so a release invocation selects both
  explicitly.
- [ ] Reject `--compiler` / `--compiler-sha256` when `--include-mpy` is absent.
- [ ] Harden or remove the `scripts/prepare_release.py` compatibility shim,
  with an explicit supported invocation/import contract.
- [ ] Add automated RC-profile plus `--include-mpy` end-to-end coverage of
  combined source/compiled packaging and its manifests/checksums. Preserve the
  existing manual reproduction evidence and focused compiler-verification tests.
- [ ] Add a `main()` smoke test covering the canonical CLI entry point.
- [ ] Add a cross-script `BUILD_INFO.txt` contract test from build output
  through compiled packaging. Extend the existing field/refusal and build-script
  metadata tests with the exact four-field, source/compiler/optimization contract.
- [ ] Add `scripts/` to the Bandit targets in `.github/workflows/host-security.yml`.
- [ ] Fix the moved-path comment in `tools/mpy_cross_pin.env` from
  `docs/hardware-test-limitations.md` to `docs/validation/hardware-test-limitations.md`,
  preserving the compiler version and digest.
- [ ] Keep published-asset reproduction on the packager at each asset's own
  tag. The rc.1 guide already pins `888b089`; preserve and verify this invariant
  for future releases.

The shim and automated-test items are follow-up hardening/coverage work. They
do not invalidate the recorded published-byte reproduction or authorize device
operations. The [reliability matrix](README.md) and
[Phase 2 record](phase2-host-selection.md) continue to own physical acceptance.

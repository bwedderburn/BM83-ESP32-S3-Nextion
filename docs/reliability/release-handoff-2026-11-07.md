# Release handoff — 2026-11-07

The published [v1.0.0-rc.1 prerelease](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/tag/v1.0.0-rc.1)
uses exact source commit
[`888b089c5a75865bb2bf8c76833f0eddc0fbd290`](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/commit/888b089c5a75865bb2bf8c76833f0eddc0fbd290)
and Python package version `1.0.0rc1`. This dated record supplements
[DIRECT-MAINTENANCE.md](DIRECT-MAINTENANCE.md). Later documentation on `main`
does not change the released tag, source snapshot or asset bytes.

This record covers the release handoff and later host-only tooling follow-ups.
BM83 and CrowPanel stayed offline during this maintenance. Private profiles,
credentials, backups and raw captures remain outside Git. Native
CircuitPython/CrowPanel builds and device operations are outside this maintenance.

## Gates recorded for 888b089

The local gate results and CI run IDs are retained verbatim:

```text
Linux, Python 3.13: pytest 1705 passed, 4 skipped, 162 subtests; flake8 E9/F63/F7/F82 0; bandit clean; check_reliability_setup PASS; pip-audit clean
CI run IDs: 42416862677, 42416862651, 42416862684
```

These are the historical results for `888b089`, including its real pinned
application `.mpy` compiler lane. The **local** Bandit gate covered the production
trees and packagers at medium/high severity (`-ll`). The `888b089` host-security
workflow scanned only `firmware/circuitpython` and
`addons/universe-badge/apps/bm83_remote`; it did not scan `scripts/` in CI.
That CI target was added later in `f6243be`. The clean dependency audits covered
the development, repo-health MCP and native-build requirement manifests. They
are separate from a native-runtime build or physical acceptance.

| Workflow at 888b089 | Run ID | Result |
| --- | --- | --- |
| [Python package](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42416862677) | `42416862677` | Passed: Python 3.11, 3.12 and 3.13 |
| [Host security and reliability policy](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42416862651) | `42416862651` | Passed |
| [Codacy Security Scan](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42416862684) | `42416862684` | Analysis and SARIF upload passed; this verdict does not assert zero findings |

Gates for later commits are recorded separately in their commit messages and
workflow runs. The historical counts above are not relabeled as a new run.

## Later-main scope and CI record

The initial owner request was list-only: commit
[`fc498b8`](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/commit/fc498b852334fa43709d418f2f4684cba8a1d5a4)
recorded the handoff and deferred backlog without implementing it. The owner
subsequently requested: **“Implement the deferred backlog in the release handoff with host-only tests.”**
That later instruction authorized the host-only scope
expansion. Codex chose the tooling, test and workflow edits in
[`f6243be`](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/commit/f6243be4a150552ad288951453f3bfa836ea259b)
under that request.

The following commits completed their automatic post-landing main workflows successfully:

| Commit | Python package | Host security and reliability policy | Codacy Security Scan |
| --- | --- | --- | --- |
| `fc498b8` — documentation/list-only handoff | [42421242030](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42421242030) | [42421242140](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42421242140) | [42421242058](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42421242058) |
| `f6243be` — host-only backlog implementation | [42426961009](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42426961009) | [42426961007](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42426961007) | [42426961054](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42426961054) |
| `e6d8901` — release-review follow-ups | [42435140948](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42435140948) | [42435140949](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42435140949) | [42435140954](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42435140954) |
| `4f8a6f1` — owner-required check documentation | [42436344333](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42436344333) | [42436344315](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42436344315) | [42436344346](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42436344346) |

The `f6243be` [pinned application `.mpy` build](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/actions/runs/42426961027)
also passed. These runs record actual execution for their respective commits;
the host-security runs executed their configured policy, Bandit and dependency
audit steps. Codacy success records completed analysis/upload. None of these
results establishes physical acceptance or a new native-runtime build.

Standing CI-record rule: commits touching `.github/workflows/` or
`scripts/check_reliability_setup.py` must record their post-landing workflow run
IDs in this handoff, verified read-only against the exact commit.
Documentation-only commits need not record their own post-landing run IDs here.

The current review follow-up's reliability checker is a host-only structural
guard. It requires the workflow directory and `python-package.yml`,
`host-security.yml` and `codacy.yml` files, then checks known YAML fields and the literal Bandit command/target
layout, including declared job/step conditions and `continue-on-error` fields.
Its editor-task check likewise checks the configured literal arguments. It does
not execute GitHub's workflow engine or evaluate arbitrary shell behavior.
The linked workflow results provide separate execution evidence; neither the
checker nor a green run establishes protected-branch required-check settings.

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

### Standing reproduction rule

Use each published asset's own tagged packager, source revision and compiler
pin for every reproduction. This is an ongoing release rule, outside the finite
implementation checklist below. The `f6243be` summary counted it as a ninth
completed item; this handoff now separates the rule from the eight finite tasks.

The later-main review follow-up adds a packager source-identity guard: the
executing packager source must match its ordinary committed blob at the requested
revision, allowing only CRLF/LF normalization, before artifact-input selection or
output creation. This enforces that invariant for the updated tool. It does not
change the older `888b089` packager, which must still be run from its own tag.
The source comparison covers the packager; build-script identity is outside that
comparison. Existing compiler, exact-ref build and compiled-byte checks continue
separately. No published asset or manifest format is changed by this guard.

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

## Tracked backlog — implemented on later main

These eight finite tasks were deferred in the initial list-only handoff, then
implemented under the subsequent explicit host-only request in `f6243be`.
Its local gates are recorded in that commit message and its post-landing CI is
linked above. The published rc.1 tag, tagged packager and four assets remain
unchanged.

- [x] Make `--scope` and `--version` required in
  `scripts/package_source_release.py` so a release invocation selects both
  explicitly.
- [x] Reject `--compiler` / `--compiler-sha256` when `--include-mpy` is absent.
- [x] Remove the `scripts/prepare_release.py` compatibility shim and its current
  RC allowlist entry; the canonical script is the supported release entrypoint.
- [x] Add automated RC-profile plus `--include-mpy` end-to-end coverage of
  combined source/compiled packaging and its manifests/checksums. Preserve the
  existing manual reproduction evidence and focused compiler-verification tests.
- [x] Add a `main()` smoke test covering the canonical CLI entry point.
- [x] Add a cross-script `BUILD_INFO.txt` contract test from actual build output
  through compiled packaging in the new
  `tests/test_source_release_end_to_end.py` module. The existing field/refusal and
  build-script metadata tests remained in place.
- [x] Add `scripts/` to the Bandit targets in `.github/workflows/host-security.yml`,
  and extend the existing `tests/test_reliability_setup.py` policy tests for the
  required production/script target set and declared bypass fields.
- [x] Fix the moved-path comment in `tools/mpy_cross_pin.env` from
  `docs/hardware-test-limitations.md` to `docs/validation/hardware-test-limitations.md`,
  preserving the compiler version and digest.

Host-only tests cover the current CLI, combined RC source/compiled output and
the build-script/packager metadata contract. These follow-ups do not invalidate
the recorded published-byte reproduction or authorize device operations.
The [reliability matrix](README.md) and
[Phase 2 record](phase2-host-selection.md) continue to own physical acceptance.

## Remaining gates and role owners

Brian / `@bwedderburn` owns release scope, approvals and physical acceptance
decisions. Codex is the host-only maintainer for source review, test coverage,
tooling and sanitized evidence preparation. Hardware/native investigation may
need a specialist assigned by the owner; this handoff assigns no new person or
GitHub issue ownership.

| Remaining gate | Evidence or decision still needed | Role owner |
| --- | --- | --- |
| Windows BM83 audio power-cycle wedge | Establish source-side recovery behavior and any claimed automatic recovery for the exact supported configuration; BLE volume fixes do not close this audio-path fault | Brian decides the physical protocol/acceptance; an owner-assigned specialist investigates; Codex prepares host-only checks |
| Ctrl-C / native VM teardown fault | Identify the exact runtime/backend and failure, with a bounded safe-mode/rollback route and separately authorized physical validation | Brian authorizes any device work; an owner-assigned native specialist investigates; Codex maintains host-only guards/evidence |
| Phase 2 host selection | Complete the new qualified timing window and full declared host, enrollment, competing-host and power-order matrix, including the open Selected AUTO, Enrollment and Live regression gates | Brian owns the physical run and verdict; Codex prepares regression/instrumentation; a specialist is assigned by the owner if needed |
| macOS / Apple Music / helper off and helper on | Both reliability-matrix rows remain **Not accepted**; obtain their own exact-build acceptance if included in the support declaration | Brian declares support and accepts results; Codex prepares host-only diagnostics |
| Linux / claimed audio + BLE HID stack | The matrix row remains **Not tested**; the saved-Pi bench trial does not establish this entire row | Brian declares support and the exact stack; an owner-assigned specialist performs any authorized physical work |
| Final-release acceptance scope | Explicitly declare supported rows and require acceptance of the exact final source/native/application build and installed configuration for each; explicitly mark excluded rows unsupported | Brian owns the scope and release decision; Codex assembles source, test and review evidence |
| Private evidence and reproducible rollback | Retain exact versions, source/compiler/artifact manifests, private captures and verified backups outside Git; publish only sanitized evidence with its actual scope | Brian is evidence custodian and approves any installation; Codex preserves public/private boundaries |

The [reliability matrix](README.md), [Phase 2 gates](phase2-host-selection.md#required-gates)
and [final-release criteria](../releases/README.md#version-line-and-final-v100-gates)
remain authoritative for those decisions. Historical Windows acceptance cannot
substitute for a new final build or unaccepted platform row. These open gates do
not authorize device access during host-only maintenance.

On 2026-11-07, Brian, the repository owner, added `host-security` as a required
status check for `main` via the GitHub REST API (`gh api`), after the UI edit did
not save. Subsequent read-only API verification
found exactly these required contexts: `build (3.11)`, `build (3.12)`,
`build (3.13)` and `host-security`. The strict/up-to-date flag remains `true`,
and `enforce_admins.enabled` remains `false` ("Do not allow bypassing the above
settings" is off). The pull-request review requirement is unchanged, Codacy
remains non-required, and ruleset `11607796` is unchanged.

These required checks gate pull requests such as Dependabot's updates. Direct
pushes to `main` remain the maintenance workflow under `CLAUDE.md`, using the
owner's existing permissions. Codex verified the decision read-only and changed
no protection, ruleset, credential or approval setting; the restriction on
changing those settings remains in force. Successful host-security execution
and structural checker coverage are recorded separately from this settings
verification.

## Review disposition

The owner reported zero blockers across all three review lenses, with no rollback
requested. The follow-ups addressed here correct evidence wording and task
history, name the remaining gates/owners, link post-landing CI, align local scan
commands, and add missing presence, argument and packager-identity checks.

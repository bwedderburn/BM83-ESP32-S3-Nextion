# Native dependency proposal review — 2026-11-03

Scope: host-only review of Dependabot proposals #199 (Click) and #200
(linuxdoc). No device discovery, hardware I/O, runtime deployment or physical
acceptance is part of this work. Historical validation records, source/compiler
pins and runtime patch provenance remain unchanged.

## Restore active recipe coherence

The active dependency hashes in `source-pins.json` had not followed the earlier
IDF-build-apps/NVS-generator updates merged as #196 and #197. Both new proposals
also changed hashed inputs without refreshing the active declarations. The
native recorder would reject those inputs before compilation, although the
ordinary host tests passed because recorder tests used synthetic fixtures.

The new actual-repository regression test checks both dependency files against
their `security_build` SHA256 declarations. It failed for both files before this
repair. Exact LF bytes are required by Git attributes, matching the recorder's
raw-byte hashes on Linux and preventing Windows checkout conversion from
changing Docker inputs. `reference_tools` retains its historical digests.

## linuxdoc proposal #200

The change is confined to the optional DOCS constraint:
`linuxdoc==20210324` becomes `linuxdoc==20260504`. The installed native-build
requirements contain no linuxdoc package and the recipe does not invoke its
renamed CLI commands. The release requires Python >=3.10, compatible with the
pinned Linux/Python 3.11.18 builder. Its intervening license change to
AGPL-3.0-or-later is upstream metadata; this constraint update does not itself
install or redistribute linuxdoc.

The repaired checkout passes the complete Linux host suite: 1,501 tests and
157 subtests, with five optional tests skipped. Strict lint, reliability policy,
production Bandit analysis and whitespace checks pass. Pinned pip-audit reports
no known vulnerabilities for the native requirements or linuxdoc 20260504.
The two input-coherence tests also pass on Windows, including a real checkout
with `core.autocrlf=true`. This does not claim that the full Linux-oriented
test suite is supported unchanged on Windows.

The active requirements digest reflects the already-merged native dependency
set; the active constraints digest includes #200. Updating these declarations
establishes input consistency, not successful native compilation or renewed
hardware acceptance. Frozen native artifacts are not relabeled as builds of
these changed inputs.

## Click proposal #199

Click 8.5.0 is beyond the pinned ESP-IDF's upstream `click<8.2` constraint.
The proposal therefore needs an explicit compatible override, refreshed active
input hashes and real Linux tool/build evidence before merging. Green host CI
alone does not establish this compatibility.

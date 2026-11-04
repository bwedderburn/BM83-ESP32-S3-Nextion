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

At the #200 merge, the active requirements digest reflects the already-merged
native dependency set and the active constraints digest includes #200. Those
declarations establish input consistency. Native compilation of the final
combined inputs is evidenced below; hardware acceptance remains separate.
Frozen native artifacts are not relabeled as builds of changed inputs.

## Click proposal #199

Click 8.5.0 is beyond the pinned ESP-IDF's upstream `click<8.2` constraint.
This is an explicit local compatibility override, `click>=8.5.0,<8.6`, with the
installed version pinned exactly to 8.5.0. The evidence covers the recorded
Linux/Python 3.11.18 toolchain; it does not claim upstream support for Click 8.5
or validation of future versions. See the [upstream IDF constraints](https://dl.espressif.com/dl/esp-idf/espidf.constraints.v6.0.txt)
and [Click changelog](https://click.palletsprojects.com/en/stable/changes/).

Both active digests were refreshed for these final combined inputs:

| Input | SHA256 |
| --- | --- |
| requirements-build.txt | `e0c1f8197c9a62b3a7ff875574036be301eee1a62008db4c58a947f9573a2f2b` |
| espidf.constraints.v6.0.txt | `0728b440d5b5f6fb517d954b74889bc9e8e4b1e079b1a92237f7e43036d4edc5` |

The private candidate builder is
`sha256:4765f63b4302bb7c7b47d9836f98776ea489a1a5ee0f36ab19e0942277946563`,
derived from the unchanged cached hash-close builder
`sha256:7adf55fa8693c225abe0467f02ffcbda84bd086df2e2e3957c7fae9499d83816`.
Only the reviewed recipe files and installed Click/NVS-generator versions
changed in the derived environment. The exact source commits, compiler, board
configuration and runtime patches remain independently checked.

Real offline preflight passed: `pip check`, IDF's dependency checker, `idf.py`
top-level/build/menuconfig help, Bash completion and completion-script generation,
NVS generation/encryption/decryption, AES-XTS/AES-ECB round trips, and ECDSA/RSA
signing/verification with tamper rejection. Actual versions include Click 8.5.0,
NVS generator 0.3.0, cryptography 50.0.0, esptool 5.6.0 and rich-click 1.9.9.

Two fresh, sequential native builds used the same immutable candidate image,
independent empty output directories, network disabled, four CPUs and a 4 GiB
memory limit. No device, privileged access or Docker socket was exposed. Run A
completed in 251.41 seconds and run B in 229.21 seconds. Both passed the source,
tool, provenance and default offline image validators (`write_performed=false`).

Raw comparison passed for all ten recorded artifacts, without normalizing or
rewriting completed output. Both applications are 1,947,056 bytes with SHA256
`a081b8b2bbd5d90c4dbb5007e48edad5aa632a37ecfe5b27baaa61646edff1f4`.
Both application ELFs have SHA256
`e42c6da41a294130fe2a20472321e852276ecc2c1bbfd5a51c6debe65a40f491`.
The comparator establishes equality and declared-hash validity; separate source
guards establish the approved pinned sources before and after each build.

The final recipe also passes 1,501 Linux host tests and 157 subtests, with five
optional tests skipped, strict lint and the pinned full-manifest advisory audit.
These are uninstalled native candidates and host checks, not radio/audio,
screen/button or reconnect acceptance. Raw logs and original outputs remain in
the new private validation directory; older frozen evidence is unchanged.

# Local release candidate preparation

Candidate: Python version `1.0.0rc1`, proposed Git tag `v1.0.0-rc.1`.
This document describes local preparation only; no tag or public release exists
as a consequence of these commands.

## Scope and source selection

The release helper reads committed Git blobs from the requested revision. Its
allowlist contains `firmware/circuitpython/`, `addons/universe-badge/`, and a
small explicit set of release/installation/validation files. It never walks
the entire working tree to create a source archive. Generated or untracked
files cannot silently enter the source package.

Compiled output must match the exact committed revision in `dist/BUILD_INFO.txt`
and the pinned CircuitPython 10.3.1 compiler at -O2. Expected output names are
derived from committed source: source entrypoints remain verbatim `.py`, library
modules become `.mpy`, and tracked public assets retain their exact bytes.
Unexpected files, private profiles, private key blocks, and escaped paths are
refused. The native runtime, CrowPanel build, and vendor reference/demo packages
are excluded. No device drive or serial port is used.

ZIP entry order, timestamps, file modes, JSON formatting, and separators are
fixed. Stored ZIP entries avoid compression-library differences. Repeating the
packaging command for identical committed source and compiled bytes produces
identical archive SHA-256 values. Reproducing native compiler output itself
still requires the documented compiler/runtime compatibility.

## Local build and package

1. Commit the reviewed release files and note the exact commit.
2. Select the repository-pinned CircuitPython 10.3.1 mpy-cross for the host.
3. Confirm the resolved `dist/circuitpython` output is inside this isolated
   checkout, then run the existing build script. Its cleanup removes only that
   generated controller directory; never point it at a device filesystem.
4. Run the packager from the repository root:

   ```sh
   python scripts/prepare_release.py --include-mpy --compiler-sha256 <observed-compiler-sha256>
   ```

   Source-only preparation omits `--include-mpy` and the compiler hash. Output
   defaults to ignored `dist/releases/v1.0.0-rc.1/`. Existing differing archives
   are refused; choose another output folder inside `dist/` for another build.

5. Verify `SHA256SUMS.txt`, internal manifests, file names, and notices. Repeat
   the packaging command to check deterministic archive bytes.

The command writes only archives/checksums under the checkout's ignored `dist/`.
It does not build or flash firmware, install dependencies, contact a device,
create a tag or release, push a branch, or upload artifacts.

## Recorded preparation checks

Final revision, check results, and generated archive hashes are reported by the
local preparation handoff. Detailed machine logs remain ignored build outputs.
Record hardware acceptance only from its named historical evidence; no device
validation is rerun by release preparation.

Preparation on November 2, 2026 completed:

- Full host regression on Ubuntu 24.04 / Python 3.12.3: **1,500 passed,
  4 skipped, 157 subtests passed**, with the real pinned Linux 10.3.1 compiler
  build lane enabled. The host native-hash ownership harness also passed.
- Reliability policy and fatal lint checks passed. Production Bandit analysis
  found no medium/high-severity issues. Audits of the development, repo-health
  MCP, and native-runtime build requirement manifests reported no known
  vulnerabilities at preparation time.
- The actual `build_mpy.sh` completed using native Windows mpy-cross 10.3.1
  after verifying that its output remains inside the isolated release checkout.
- Packaging refusal checks covered private paths, traversal, and private-key
  headers. Archive bytes were repeatable; executable source modes are preserved
  from the committed Git tree.

The Windows Python 3.14 diagnostic full-suite run was not accepted: 1,315 passed,
90 failed, 99 skipped, and 2 errored. It exposes POSIX-private-permission,
default-encoding, path, and checkout-line-ending assumptions in host tools and
fixtures. No production safety guards were weakened to turn that run green.
The intended Linux/CI-style suite above passed from a fresh LF checkout with
proper POSIX fixture permissions. This record does not claim Windows host-tool
or physical Windows audio/BLE compatibility.

The Linux native-hash harness used locally extracted OpenSSL development
headers, version 3.0.13-0ubuntu3.16, with the host crypto library. This was a
local build dependency, not a system package installation or a bundled runtime.

The native Windows compiler available for this preparation reports
`CircuitPython 10.3.1 on 2026-09-14; mpy-cross emitting mpy v6.3` and SHA-256
`0f57daeaeda62d9f4b36c110ea0dc6e80f60ef8eb8adb77d576741167e1a47a9`.
This is an observed host compiler, distinct from the separately pinned Linux
download digest. Neither compiler binary is bundled in the RC archives.

## Local dependency refresh on November 2, 2026

The candidate incorporates the two squash-merged dependency updates while
retaining the original release preparation commit:

- PR #196: `afc0c3b9632e20d4c2fd2871e18b0ce29a4285da`, allowing
  `idf-build-apps < 3.2` on Python >=3.10. That package is not installed by the
  frozen native build requirements.
- PR #197: `f7cffd27c23855c82a20305276eb14fbeca41015`, updating the NVS
  partition generator to `0.3.0` in both requirements and constraints.

At the final merged revision, GitHub's Python 3.11/3.12/3.13 tests, host-security
policy/dependency audits, Codacy scan, CodeQL language scans and dependency graph
update passed. These are host checks, not a native-runtime compilation or
hardware acceptance record.

The merged dependency files changed without corresponding active provenance
hash updates. The local refresh repairs only `security_build` in
`tools/circuitpython-runtime/source-pins.json`: constraints SHA-256
`54ee078efacb8de913ba75d0132b783a192e5f887ddda539d13a2937f71dd3b5`
and requirements SHA-256
`47e0b8723a7e1439e1bbc1ac0e961f1c91160539ea0331efbbf619d8984de6b0`.
The new two-case repository consistency test failed against the merged files
before this repair and passed afterward. Historical `reference_tools` hashes,
native source/patch pins and dated native-build reports retain their original
bytes and scope.

Refresh validation on Ubuntu 24.04 / Python 3.12.3:

- **128 passed** across native provenance, host-tool safety and reproducibility
  tests, including the new repository consistency cases. Fatal lint passed.
- A fresh isolated environment installed the complete frozen native build
  requirements with the refreshed constraints; `pip check` passed.
- The actual host-tool verifier passed all five synthetic check groups: NVS
  generate/repeat/encrypt/decrypt, AES-XTS, legacy ESP32 AES-ECB, ECDSA P-256 and
  RSA-3072 signing/verification with tamper rejection. It reported
  `hardware_access: false`, NVS `0.3.0`, cryptography `50.0.0`, esptool `5.6.0`,
  cffi `2.1.1` and OpenSSL `4.0.1`.

These new checks do not rerun or replace the earlier full regression record.
The native builder's Python 3.11.18 environment and a new native CircuitPython
image have not been built or validated for this dependency refresh.

Refreshed controller archives use the pinned Linux mpy-cross 10.3.1 at -O2,
SHA-256 `aa74dcb51e51c1a70fd268dad9e05b40f72c29df3082f86c3a20665360e4acda`.
Their output folder is `dist/releases/v1.0.0-rc.1-dependency-refresh/`; the
original `dist/releases/v1.0.0-rc.1/` archives are preserved. Each refreshed
archive's manifest records the exact final local candidate revision, and the
compiled archive includes matching `BUILD_INFO.txt`. The selected source and
compiled archives exclude the native build recipe and its dependencies.

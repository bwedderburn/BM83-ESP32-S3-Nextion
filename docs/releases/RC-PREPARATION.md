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

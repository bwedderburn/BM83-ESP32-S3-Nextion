# Isolated native-build security validation — 2026-11-01

Scope: remediate the four host-tool dependency advisories, verify compatibility
and reproduce the native artifacts locally. BM83 and CrowPanel remain offline.
No serial/device discovery, radio probe, playback, reset, deployment, flashing,
credential change, Copilot request or branch-policy change is part of this work.
Raw logs, generated firmware and original failed comparisons stay outside Git.

## Dependency change

Only the effective cryptography requirement/constraint changes:

- `cryptography==46.0.7` becomes `cryptography==50.0.0`.
- The reviewed IDF constraint override is `>=50.0.0,<50.1`.
- NVS generator 0.1.9, esptool 5.6.0, cffi 2.1.1 and the existing IDF-build-apps
  bounds remain unchanged.
- CI now audits the entire pinned native manifest alongside development/MCP
  requirements; no advisory is ignored or manually dismissed.

| Advisory | Severity | First fixed version |
| --- | --- | --- |
| GHSA-537c-gmf6-5ccf | High | 48.0.1 |
| GHSA-g6cj-pr64-35w5 | High | 50.0.0 |
| GHSA-jwv3-5hgf-82ww | High | 49.0.0 |
| GHSA-m2h6-j472-rp4c | Medium | 49.0.0 |

The supported host is Linux amd64, Python 3.11.18. The official
[cryptography changelog](https://cryptography.io/en/50.0.0/changelog/) documents
the removal of Intel macOS support/wheels in 49. The Linux route avoids an
unsupported source build on this Intel Mac. The active requirements and
constraints hashes are separate from the preserved historical reference hash.

## Real compatibility checks

The actual installed tools passed, using disposable synthetic files and keys:

- NVS generation twice with matching hashes, encryption and exact plaintext
  decryption round trip.
- ESP32-S3 AES-XTS and legacy ESP32 AES-ECB encryption repeat/round-trip checks.
- ECDSA P-256 and RSA-3072 Secure Boot V2 signing and verification, with rejection
  of modified signed data.
- Offline ESP32-S3 inspection of the generated application with esptool.
- `pip check` and IDF's own dependency checker, with the reviewed constraints.

The actual crypto backend reports OpenSSL 4.0.1. No key bytes or raw subprocess
output are included in the reports. The full flat-manifest audit reports no
known vulnerabilities.

## Reproducibility defect found and corrected

The first two clean builds compiled and passed offline image validation, but
strict raw comparison correctly failed. Their app images differed in 87 bytes:
22 gzip timestamp bytes, 32 propagated ELF-digest bytes and 33 checksum/digest
bytes. The application ELFs differed in those 22 gzip timestamp bytes; the
remaining eight recorded artifacts matched.

Inspection of all 11 embedded gzip members found identical deflate streams,
CRC/ISIZE trailers and decoded assets, but timestamps 604 seconds apart. The
pinned upstream [web-asset generator](https://github.com/adafruit/circuitpython/blob/c9dee12beed76e4ffa11d2d6d99ff104fc976c3a/tools/gen_web_workflow_static.py#L35)
calls `gzip.compress(uncompressed)`, whose Python 3.11 default embeds wall-clock
time despite `SOURCE_DATE_EPOCH` being set.

The explicit one-line `reproducible-web-assets.patch` sets `mtime=0` during
generation. The complete generator is checked against the exact pinned source
plus that one change, and the patch digest is recorded and compared. This is a
build-tool change; source commits, target compiler and the eight-bond/24-CCCD
board configuration are preserved. Python 3.11's zero-time fast path can also
change the gzip OS byte from 255 to 3. Asset-content checks compare decoded data,
deflate bytes and CRC/ISIZE, rather than mistaking that header for content.

The failed outputs remain intact. Completed artifacts are never rewritten or
normalized to make comparison pass. Replacement verification uses two further
fresh containers and their original output bytes.

## Final clean-build result

**Passed:** two further independent clean builds from the same immutable Linux
builder produced identical original bytes for all ten recorded artifacts. Each
container had networking disabled, no privileged/device access, a separate empty
output mount and fresh board/mpy-cross object directories. Both finished with
successful pinned-source/tool checks, crypto/image-tool checks and offline image
validation. No generated output was normalized or rewritten.

Builder ID: `sha256:da748fb217b4f24b8469e63c86c77bd054d6e1e61a3e3eaf4d1fd0346a2445e8`.

Both applications are **1,946,640 bytes**, leaving **150,512 bytes** in the stock
2 MiB application partition. The image checksum/appended SHA, segment bounds,
partition table/MD5 and eight-bond/24-CCCD/NVS-persistence configuration passed.
No extra board reproducibility option was introduced.

All eleven fixed gzip members have zero timestamps and identical decoded data,
deflate bytes and CRC/ISIZE to the original build. The final pair's gzip content
checks also pass. The actual crypto-tool reports match across the final pair.

| Artifact | Bytes | Matching SHA256 in both builds |
| --- | ---: | --- |
| app | 1,946,640 | `a38ddf41061d259973eaf757cc138b7a312f3e00aae9198335f7bfcb28623099` |
| bootloader | 13,808 | `bfc1a9253d8a4ec1771e5effdea9d2ce98149df58d190b98356b4e7e2687df13` |
| distro_manifest | 11,204 | `25cd4e369dcd7ed351f0c8d3850fd17e375d55a69ac07ae847850297c76822c3` |
| elf | 15,344,048 | `2d13636560195a3aad024b4397d905b2e461474067a46667b4f422e6f2f051d2` |
| mpy_cross | 420,280 | `74a98459206ee85c32dc88927cbc1328a56c7fb5475823a26319b264e6c37464` |
| partition_table | 3,072 | `5f34538abf96c176b63896558ec5d32096be6cef6f09ddbe644dd2a6eeb5d8a8` |
| python_packages | 1,583 | `a25aa69df1e2af04502f1029136993bd2ffb0d4b188d825b5af1b5be69e8f6c8` |
| recursive_submodules | 13,557 | `0eb24da80937af7aa96c47c417d054310e0295eb21a40baa87c294df0b831e34` |
| sdkconfig | 95,557 | `71fa871fce83ac4c37dbb12a1c5ff1d7cddfb10224b59312649d3161ad5429e5` |
| sdkconfig_h | 54,612 | `5094a0ff44349f051fab6cb928870d394bcd7686714ec28394074ae5d23b7bad` |

The comparison separately verifies every declared hash, equal recorded inputs
and raw bytes. It deliberately does not claim that matching metadata alone
proves approved inputs (`approved_source_pins_verified: false`). The recorder's
independent before/after checks established the actual pinned commits, complete
allowlisted board/generator patches, host/compiler versions and dependency/tool
manifest hashes. The web patch input digest is
`874027789d6166cb141c5d30a33356de1e1e69171f3a0ac592bf85a86468c0ae`.

## Scope of the evidence

Repeating builds from an immutable prepared builder is distinct from recreating
that builder later against changing Debian/PyPI metadata. The exact builder ID,
package/source manifests and raw logs are retained with the private artifacts.

The recorder/repeat guards pass 101 tests (37 recorder, 64 comparison). The
host-tool verifier's 10 safety/error fixtures pass. The earlier complete host
suite passed 1,371 tests and 116 subtests, including its real pinned compiler
gate; the updated guards were then exercised separately. Lint, shell syntax,
policy and whitespace checks pass; Bandit reports no medium/high findings in
the new tools. All 39 original frozen investigation files remain hash-identical.

No generated image is installed or physically accepted. Issue #193's separate
native-radio/resource causality investigation, the controlled physical soak and
screen/button/reconnect gates remain open. This dependency repair does not close
Phase 1 acceptance or authorize Phase 2 BLE HID Disconnect.

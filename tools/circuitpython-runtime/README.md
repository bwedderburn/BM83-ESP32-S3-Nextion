# Secure isolated CircuitPython runtime build

The active recipe uses **cryptography 50.0.0** on **Linux amd64**, with Python
3.11.18, pinned CMake 3.30.9, Ninja package 1.13.2 and the official
`esp-15.2.0_20251204` target toolchain. cryptography 49 removed Intel macOS
support/wheels, so this recipe runs in a local Linux container on the Intel Mac.
It does not source-build an unsupported cryptography wheel or relax TLS checks.

The CircuitPython 10.3.1, ESP-IDF and NimBLE commits remain pinned in
[source-pins.json](source-pins.json). The board capacity patch retains eight stored
bonds and 24 CCCD records. Stock partition layout, GATT service definitions, 8 MiB
flash and 8 MiB octal PSRAM remain in the pinned source configuration. No device
access, deployment, pairing, playback or live NVS data is part of this recipe.

`reference_tools` retains the original Intel macOS environment's provenance,
including its old constraints digest. `security_build` identifies the new active
Linux snapshot and its current requirements/constraints hashes. Do not relabel
an original artifact with new digests or replace frozen candidates silently.
The active recipe incorporates dependency updates from PRs #196 and #197
(`idf-build-apps < 3.2` for Python >=3.10 and NVS partition generator `0.3.0`),
#199 (Click `8.5.0`) and #200 (the optional linuxdoc constraint `20260504`).
The frozen build requirements install neither `idf-build-apps` nor linuxdoc;
their constraints do not add those tools to this recipe. Click `8.5.0` is an
explicit local override of the pinned ESP-IDF's upstream `click<8.2` bound,
validated for the recorded Linux/Python 3.11.18 environment.

The optional ESP-IDF MQTT tests use Paho's legacy callback API. The constraint
excludes 2.0.0 because it requires a callback API argument to Client(). Offline
checks of the pinned IDF MQTT example covered client setup and callback delivery
with Paho 1.6.1, 2.1.0 and 2.2.0. The native build requirements list the packages
installed by the builder.

The active raw-byte dependency hashes in `source-pins.json` are:

| Input | SHA256 |
| --- | --- |
| `requirements-build.txt` | `e0c1f8197c9a62b3a7ff875574036be301eee1a62008db4c58a947f9573a2f2b` |
| `espidf.constraints.v6.0.txt` | `abd640a6a24a5ca8e1fe6c7181279bdc863401631472aa1829e29b513cd32230` |

The [3 November dependency validation](VALIDATION-DEPENDENCIES-2026-11-03.md)
records real offline host-tool preflight and two clean native builds of these
dependency inputs recorded there. Raw comparison passed for all ten recorded artifacts, and
both builds passed the default offline image validator with no writes. This
dated evidence does not qualify later source or patch changes, or establish
hardware acceptance. The November 1 reports retain their original inputs and
frozen artifacts; they are not relabeled as builds of the refreshed recipe.

The additional [one-line web-asset build-tool patch](reproducible-web-assets.patch)
sets gzip's timestamp to zero before compression. The pinned upstream generator
otherwise embeds the current time under Python 3.11, even with
`SOURCE_DATE_EPOCH` set. Both the complete generator contents and patch hash are
checked/recorded. Decoded web assets were checked against the original build
during [validation](VALIDATION-2026-11-01.md); that additional comparison is not
an automatic build-script step. Completed images are never normalized to hide
differences. The original board capacity patch and all native source commit pins
remain unchanged. Additional runtime behavior is provided by the separately
pinned patches below.

## Native hash-operation ownership

The additional [native hash cleanup patch](hashlib-close.patch) fixes ownership
of PSA operations in the shared Mbed TLS `hashlib` implementation. It adds an
idempotent `Hash.deinit()`, a GC finalizer, guards update/digest after close and
checks native initialization/update/clone/finish failures. Digest still finishes
only a clone, so repeated digest calls and subsequent updates retain their normal
meaning. Unsupported algorithms and partial initialization remain safe to finalize.
Other hashlib backends retain their existing bindings.

The controller's HMAC helper explicitly closes each operation in `finally`.
The private `_deinit_supported` module flag lets it refuse an older embedded
runtime before opening the receiver or allocating a test context. It does not
substitute a pure-Python hash or change authentication, keys or wire encoding.

`runtime_patches.hashlib_close` in `source-pins.json` pins the reviewed patch and
all six complete patched files. The source checker rejects any additional edits,
including staged changes, and `hashlib_close_patch_sha256` is a required input
in the repeat-build manifest. The existing board/gzip patches, source commits,
NVS layout and bond capacities remain unchanged. The dependency refresh above
is separate from these native source patches.

The host C ownership harness applies the real patch to pinned source fixtures,
uses a bounded PSA allocation/error model and host SHA known answers, and checks
repeated digest/update, explicit close, failed operations and 1,000 cycles. It
does not emulate ESP32 DMA or real GC scheduling. Physical allocation recovery,
finalizer fallback, authentication latency and the normal >=30-minute run card
must still pass before hardware acceptance. A compiled image is not acceptance.

## Native BLE host policy candidate

The additional [host policy patch](host-policy.patch) adds the project-specific
ESP32 `_bleio` API consumed by Disconnect + Select host. The ordinary eight-bond
runtime does not supply this capability. This is a development candidate with
separate [build and physical acceptance gates](../../docs/reliability/phase2-host-selection.md).
No connected-device acceptance follows from a successful build.

The native policy owns persistent PAUSED/AUTO selection, a bounded ENROLL window,
saved-identity inventory and owner aliases. It does not expose bonding keys to
Python, rotate the local identity, replace the HID report map, erase old bonds or
evict records on capacity failure. The default for missing/corrupt policy or a
native failure is closed admission. Explicit Disconnect remains paused across
boot; AUTO admits only the selected saved identity.

The patch checks persistent NimBLE records and keeps OUR_SEC, PEER_SEC and CCCD
facts separate. Controller privacy and accept-list configuration are verified;
repeat-pair deletion is disabled. Security/HID readiness, full-width disconnect
reasons and operation/policy/connection generations are observations, not inferred
from a command ACK. Advertising and HID input submission must be serialized with
native policy transitions, using copied bounded records and generation checks.

The board disables NimBLE's automatic connection reattempt so a failed link
cannot restart advertising outside the saved host policy.

`runtime_patches.host_policy` pins the patch plus all twelve complete patched
source files. `record-build.py` rejects missing, extra, staged or untracked source
changes and requires the patch digest in both clean-build manifests. The four new
native source files are explicitly marked intent-to-add after patch application;
the original Git index must remain intact. The host harness compiles production
policy code; it is not NimBLE radio, actual NVS or RPA-rotation acceptance.

## Prepare the immutable builder

Docker Desktop must be running. Choose a new private output directory outside
Git; the source/SDK/toolchain cache stays in Docker. Keep adequate disk headroom
and do not prune unrelated images, volumes or containers to make room.

```sh
recipe_dir=/absolute/repository/tools/circuitpython-runtime
runtime_root=/absolute/new/private/bm83-secure-runtime
umask 077
mkdir -p "$runtime_root/run-a" "$runtime_root/run-b"
chmod 700 "$runtime_root" "$runtime_root/run-a" "$runtime_root/run-b"

docker build --platform linux/amd64 --progress=plain \
  --tag bm83-circuitpython-secure "$recipe_dir" \
  > "$runtime_root/prepare.log" 2>&1
builder_id="$(docker image inspect --format '{{.Id}}' bm83-circuitpython-secure)"
```

The Dockerfile pins the official Python base by immutable digest, fetches the
exact source gitlinks and checks the IDF tool manifest. IDF verifies official
compiler-download hashes. All Python build dependencies are explicitly pinned;
installation is checked against the reviewed local constraints. The tool-download
cache is task-specific. OpenOCD's installer version check requires `libusb-1.0-0`
in the container, but no USB device is exposed or used.

Preparation downloads official/public build inputs. The two actual builds below
use the same immutable image ID with network disabled and independent writable
container filesystems. No host source checkout, Docker socket, device, account
or credential directory is mounted into either build.

## Run two genuinely clean builds

Run these sequentially to bound RAM and disk use. Each output directory must be
empty. The entrypoint refuses existing board/mpy-cross object directories, and
neither command includes a flash target.

```sh
for run in run-a run-b; do
  docker run --rm --network none --cpus 4 --memory 4g --memory-swap 4g \
    --pids-limit 4096 \
    --env "BM83_BUILDER_IMAGE=$builder_id" \
    --volume "$runtime_root/$run:/output" \
    "$builder_id" > "$runtime_root/$run.log" 2>&1
done

python3 "$recipe_dir/verify_reproducibility.py" \
  "$runtime_root/run-a" "$runtime_root/run-b"
```

The build checks exact source commits, the whole reviewed board/tool patches, dirty
source paths, host/compiler versions and active dependency hashes. It uses the
pinned CircuitPython commit's `SOURCE_DATE_EPOCH`, UTC, a fixed Python hash seed
and identical internal paths, plus deterministic gzip generation. No extra board
reproducibility flag is silently added. These controls address build date/path
metadata while preserving the reviewed firmware configuration.

The repeat verifier requires matching provenance, independently verifies every
declared artifact digest, then compares **raw bytes**. It checks the application
image, actual application ELF, sdkconfig, sdkconfig header, partition table,
distro package manifest and Python package manifest, plus recorded bootloader,
mpy-cross and recursive-submodule provenance. Missing artifacts, modified input
metadata, symlinks, reused build directories and mismatches fail verification.
It does not normalize differences away or infer source approval from equality;
the separate pinned-source checks and preparation logs establish that evidence.

A cached immutable builder and repeatable firmware output do not promise that
recreating the builder later with changing Debian/PyPI metadata yields the same
image ID. Keep the actual builder ID, package manifests and logs with the outputs.

## Verify real host-tool compatibility

Before compilation, [verify_host_tools.py](verify_host_tools.py) exercises the
installed tools using disposable synthetic files and test keys:

- NVS generation twice, encryption and exact plaintext decryption round trip.
- ESP32-S3 AES-XTS and legacy ESP32 AES-ECB repeat/round-trip checks.
- ECDSA P-256 and RSA-3072 Secure Boot V2 signing/verification, with rejection of
  modified signed data.

After compilation it also runs fixed offline ESP32-S3 `image-info`. Reports
record the cryptography/OpenSSL versions and results without key bytes or raw
subprocess output. They execute no port discovery, device command or network I/O.
The build also runs IDF's own Python-dependency checker and `pip check`.

CI audits every package in the pinned native-build snapshot in addition to the
existing development/MCP dependency audits. It does not dismiss advisories.

## Artifacts remain uninstalled candidates

Each output contains `build-manifest.json` for repeat verification and a separate
`artifact-manifest.json` for the existing **default offline** image validator:

```sh
python3 /absolute/repository/tools/update_circuitpython_runtime.py \
  "$runtime_root/run-a/artifact-manifest.json"
```

Without `--write`, that validator checks the image header, appended digest,
checksum, segment bounds, exact stock partition layout and partition MD5 without
launching a subprocess or accessing hardware. The application is restricted to
the stock 2 MiB `ota_0` partition at `0x10000`. Bootloader and partition files are
reference artifacts, not write targets. Do not flash a combined `firmware.bin`.

Keep the old images, source/compiler manifests, private backups and saved state
intact. A reproducible build and offline validation do not establish radio/audio
stability, physical screens/buttons or deployment approval. Follow the separately
authorized [guarded update guide](../../docs/guides/ble-runtime-update.md) only when
hardware work is explicitly resumed.

# Secure isolated CircuitPython runtime build

The active recipe uses **cryptography 50.0.0** on **Linux amd64**, with Python
3.11.18, pinned CMake 3.30.9, Ninja package 1.13.2 and the official
`esp-15.2.0_20251204` target toolchain. cryptography 49 removed Intel macOS
support/wheels, so this recipe runs in a local Linux container on the Intel Mac.
It does not source-build an unsupported cryptography wheel or relax TLS checks.

The CircuitPython 10.3.1, ESP-IDF and NimBLE commits remain pinned in
[source-pins.json](source-pins.json). The only board patch is still eight stored
bonds and 24 CCCD records. Stock partition layout, BLE workflow services, 8 MiB
flash and 8 MiB octal PSRAM remain in the pinned source configuration. No device
access, deployment, pairing, playback or live NVS data is part of this recipe.

`reference_tools` retains the original Intel macOS environment's provenance,
including its old constraints digest. `security_build` identifies the new active
Linux snapshot and its current requirements/constraints hashes. Do not relabel
an original artifact with new digests or replace frozen candidates silently.
The unrelated NVS-generator and IDF-build-apps version bounds are preserved.

The additional [one-line web-asset build-tool patch](reproducible-web-assets.patch)
sets gzip's timestamp to zero before compression. The pinned upstream generator
otherwise embeds the current time under Python 3.11, even with
`SOURCE_DATE_EPOCH` set. Both the complete generator contents and patch hash are
checked/recorded. Decoded web assets were checked against the original build
during [validation](VALIDATION-2026-11-01.md); that additional comparison is not
an automatic build-script step. Completed images are never normalized to hide
differences. The original board
patch and all native source commit pins remain unchanged.

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
authorized [guarded update guide](../../docs/ble-runtime-update.md) only when
hardware work is explicitly resumed.

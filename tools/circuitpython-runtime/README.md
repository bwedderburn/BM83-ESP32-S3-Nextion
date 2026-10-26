# Build the reviewed CircuitPython BLE capacity configuration

This recipe reproduces the pinned source and configuration of the reviewed
ESP32-S3 N8R8 runtime. It changes two settings: eight stored bonds and 24 CCCD
records. It preserves the stock partition layout, native BLE workflow services,
8 MiB flash and 8 MiB octal PSRAM.

This is a reproducible build recipe, not a claim of byte-for-byte deterministic
output. Build timestamps, absolute paths, host tools and generated metadata can
change ELF/image hashes. Review a newly built image and its manifest before use;
do not substitute a new digest into an already approved artifact silently.

The reference build used Intel macOS, Apple Clang 21, Python 3.11.13, CMake
3.30.9, the Ninja 1.13.2 Python package, and the official
`esp-15.2.0_20251204` toolchain. The exact source commits are in
[source-pins.json](source-pins.json). Although CircuitPython's submodule branch
label says `circuitpython-v5.5.1`, its pinned IDF commit reports
`v6.0.1-7-g2b900d1222`. Always follow the gitlink, never a current branch tip.

## Fetch and verify sources

Use a new external build directory and a Python 3.11 installation. Set the two
absolute paths below for the checkout containing this recipe and the new build.
These commands prepare/build files only; they do not access a device.

```sh
recipe_dir=/absolute/repository/tools/circuitpython-runtime
runtime_root=/absolute/new/private/cp1031-build
mkdir -p "$runtime_root"
chmod 700 "$runtime_root"
python3.11 -m venv "$runtime_root/host-venv"
"$runtime_root/host-venv/bin/python" -m pip install cmake==3.30.9 ninja==1.13.2

git clone --filter=blob:none --no-checkout https://github.com/adafruit/circuitpython.git "$runtime_root/circuitpython"
git -C "$runtime_root/circuitpython" checkout --detach c9dee12beed76e4ffa11d2d6d99ff104fc976c3a
cd "$runtime_root/circuitpython"
"$runtime_root/host-venv/bin/python" tools/ci_fetch_deps.py espressif_esp32s3_devkitc_1_n8r8
git -C ports/espressif/esp-idf submodule update --init --recursive --depth 1

test "$(git rev-parse HEAD)" = c9dee12beed76e4ffa11d2d6d99ff104fc976c3a
test "$(git -C ports/espressif/esp-idf rev-parse HEAD)" = 2b900d1222cfce5dfa340ed99375af69ec1ee192
test "$(git -C ports/espressif/esp-idf/components/bt/host/nimble/nimble rev-parse HEAD)" = 7075927f97c648af650a288e94a8c80dd7f00c27
git apply --check "$recipe_dir/bonds8-cccd24.patch"
git apply "$recipe_dir/bonds8-cccd24.patch"
```

The board dependency script and recursive submodule update check out the commits
recorded by the pinned repositories. Do not run `git submodule update --remote`.

## Install isolated build tools

IDF's pinned `tools/tools.json` selects the official target toolchains and checks
download digests. Keep them and Python environments inside the external build.
The included constraints snapshot and complete Python package versions preserve
the reference environment instead of fetching a changing constraints URL.

```sh
export IDF_TOOLS_PATH="$runtime_root/idf-tools"
export PIP_CACHE_DIR="$runtime_root/pip-cache"
idf_source="$runtime_root/circuitpython/ports/espressif/esp-idf"
"$runtime_root/host-venv/bin/python" "$idf_source/tools/idf_tools.py" install --targets esp32s3

export IDF_PYTHON_ENV_PATH="$IDF_TOOLS_PATH/python_env/idf6.0_py3.11_env"
python3.11 -m venv "$IDF_PYTHON_ENV_PATH"
cp "$recipe_dir/espidf.constraints.v6.0.txt" "$IDF_TOOLS_PATH/espidf.constraints.v6.0.txt"
"$IDF_PYTHON_ENV_PATH/bin/python" -m pip install \
  --constraint "$recipe_dir/espidf.constraints.v6.0.txt" \
  --requirement "$recipe_dir/requirements-build.txt"
"$IDF_PYTHON_ENV_PATH/bin/python" -c \
  'import os,pathlib; (pathlib.Path(os.environ["IDF_PYTHON_ENV_PATH"])/"idf_version.txt").write_text("6.0")'
"$IDF_PYTHON_ENV_PATH/bin/python" -m pip check
```

The version marker identifies this manually provisioned virtual environment to
the pinned IDF export/check scripts. It does not modify IDF source. Package pins
are version locks, not a vendored wheel archive or a cryptographic attestation.

## Build the application image

On the reference Apple Clang 21 host, mpy-cross needs the host-only
`-fomit-frame-pointer` flag. No corresponding firmware compiler flag is added.
The wrappers below keep CMake pinned and Ninja limited to four workers.

```sh
export PATH="$IDF_PYTHON_ENV_PATH/bin:$runtime_root/host-venv/bin:$PATH"
cd "$runtime_root/circuitpython"
make -C mpy-cross -j4 PYTHON="$IDF_PYTHON_ENV_PATH/bin/python" CFLAGS_EXTRA=-fomit-frame-pointer

export BM83_RUNTIME_BUILD_ROOT="$runtime_root"
mkdir -p "$runtime_root/bounded-tools"
cat > "$runtime_root/bounded-tools/ninja" <<'SH'
#!/bin/sh
exec "$BM83_RUNTIME_BUILD_ROOT/host-venv/bin/ninja" -j4 "$@"
SH
cat > "$runtime_root/bounded-tools/cmake" <<'SH'
#!/bin/sh
exec "$BM83_RUNTIME_BUILD_ROOT/host-venv/bin/cmake" "$@"
SH
chmod 700 "$runtime_root/bounded-tools/ninja" "$runtime_root/bounded-tools/cmake"
. "$idf_source/export.sh"
export PATH="$runtime_root/bounded-tools:$PATH"
export CMAKE_BUILD_PARALLEL_LEVEL=4
cd "$runtime_root/circuitpython/ports/espressif"
make -j4 BOARD=espressif_esp32s3_devkitc_1_n8r8 PYTHON="$IDF_PYTHON_ENV_PATH/bin/python" \
  build-espressif_esp32s3_devkitc_1_n8r8/circuitpython-firmware.bin
```

The output `circuitpython-firmware.bin` is the app-only image for offset
`0x10000`, limited to the stock 2 MiB `ota_0` partition. **Do not flash the
combined `firmware.bin` at address zero.** The build can also generate bootloader
and partition reference files as dependencies; they are not update targets.

Record the image/ELF digests, complete generated `esp-idf/sdkconfig` and
`esp-idf/config/sdkconfig.h`, the patch, recursive submodule status, tools and
build logs. Check `CONFIG_BT_NIMBLE_MAX_BONDS=8`,
`CONFIG_BT_NIMBLE_MAX_CCCDS=24`, and `CONFIG_BT_NIMBLE_NVS_PERSIST=y` in sdkconfig.
The reference compiled `CIRCUITPY_BLE_FILE_SERVICE=1`,
`CIRCUITPY_BLE_SERIAL_SERVICE=1`, and `CIRCUITPY_SETTINGS_TOML=1`; the real setter
branch supports `supervisor.runtime.ble_workflow = False`.

Use `esptool --chip esp32s3 image-info` for offline checksum/header inspection,
then construct/review the manifest described in
[the guarded update guide](../../docs/ble-runtime-update.md). Default validation
with `tools/update_circuitpython_runtime.py` never accesses hardware. A build
success or offline validation does not establish a hardware-tested runtime.

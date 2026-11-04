# Build CircuitPython deployment files

The repository includes a `build_mpy.sh` script to compile Python modules into bytecode (`.mpy` files) for improved performance and reduced memory usage on CircuitPython devices.

## Prerequisites

The build uses **CircuitPython 10.3.1's `mpy-cross`**. The required version and
the Linux x86_64 download's SHA-256 are recorded in
[`tools/mpy_cross_pin.env`](../../tools/mpy_cross_pin.env). `build_mpy.sh` checks the
version on every host and records the selected compiler in `dist/BUILD_INFO.txt`.
It refuses other versions (set `MPY_CROSS_ALLOW_UNPINNED=1` only for experiments).

The automatic fetcher supports **Linux x86_64 and x86_64 WSL only**:

```bash
# Linux x86_64 / x86_64 WSL: download and verify into tools/mpy-cross/
./scripts/fetch_mpy_cross.sh
```

On **macOS, Linux ARM or Windows Git Bash**, install or build a native compiler
for that host from [Adafruit's CircuitPython 10.3.1 source](https://github.com/adafruit/circuitpython/tree/10.3.1/mpy-cross),
then select it with `MPY_CROSS` as shown below. The fetcher's Linux executable
cannot run directly on macOS or Windows. Git Bash requires a native Windows
compiler; alternatively, use the Linux fetcher inside x86_64 WSL.

Do not use `pip install mpy-cross`: that installs MicroPython's compiler, which
is a different compiler. Check that `--version` starts with `CircuitPython 10.3.1`.

## Building with bash

```bash
# Linux x86_64 / WSL, after the fetch above:
bm83_mpy_cross="$PWD/tools/mpy-cross/mpy-cross"
"$bm83_mpy_cross" --version
MPY_CROSS="$bm83_mpy_cross" bash ./build_mpy.sh
```

For macOS or another host, replace the example path with your installed native
CircuitPython 10.3.1 compiler. Quote the path so spaces work:

```bash
# Example native macOS path; replace with your actual installed compiler.
bm83_mpy_cross="$HOME/Tools/CircuitPython 10.3.1/mpy-cross"
# Git Bash example instead: bm83_mpy_cross="/c/Tools/CircuitPython 10.3.1/mpy-cross.exe"
"$bm83_mpy_cross" --version
MPY_CROSS="$bm83_mpy_cross" bash ./build_mpy.sh
```

Both commands produce the same output layout:

```text
# Output will be in dist/circuitpython/
# ├── boot.py           (early runtime configuration, kept as .py)
# ├── main.py           (kept as .py - entry point must not be compiled)
# ├── settings.toml     (config file, if present)
# └── lib/              (compiled modules)
#     ├── bm83/
#     │   ├── __init__.mpy
#     │   └── bm83.mpy
#     ├── nextion/
#     │   ├── __init__.mpy
#     │   └── display.mpy
#     ├── blehid/
#     │   ├── __init__.mpy
#     │   └── ble.mpy
#     └── utils/
#         ├── __init__.mpy
#         └── common.mpy
```

## Building with WSL (Windows Subsystem for Linux)

```bash
# Open WSL terminal (Ubuntu, Debian, etc.)
cd /mnt/c/path/to/BM83-ESP32-S3-Nextion

# Fetch the pinned mpy-cross if not already present
./scripts/fetch_mpy_cross.sh

# Check the compiler, then run the build script
bm83_mpy_cross="$PWD/tools/mpy-cross/mpy-cross"
"$bm83_mpy_cross" --version
MPY_CROSS="$bm83_mpy_cross" bash ./build_mpy.sh

# The output in dist/circuitpython/ can be copied to your CIRCUITPY drive
# from Windows Explorer at the WSL path shown after build completes
```

## Deployment After Build

1. Copy the entire contents of `dist/circuitpython/` to your `CIRCUITPY` drive.
2. A library-only update does not install changed startup behavior. When updating BLE handoff support, include both `boot.py` and `main.py` as well as the compiled libraries.
3. Make sure the required Adafruit libraries are present in `CIRCUITPY/lib/`:
   - `adafruit_ble/`
   - `adafruit_hid/`
4. Reset the board.

**Recommended flow**: Validate first with plain `.py` files from `firmware/circuitpython/` (`boot.py`, `main.py` and project libraries), then switch to compiled library artifacts from `dist/circuitpython/` for production.

**Note**: The build script preserves `boot.py` and `main.py` as source. Project library modules are compiled to `.mpy` and placed in `dist/circuitpython/lib/`.

**Important compatibility warning**: The `mpy-cross` version used for compilation must match the CircuitPython firmware version on your device. The pin in `tools/mpy_cross_pin.env` records which version that is; when the device's CircuitPython is upgraded, bump the pin in the same change. If you encounter `ValueError: incompatible .mpy file` errors, check the device version against the pin.

**Quick rollback (.mpy → .py)**:
1. Delete deployed project folders/files from `CIRCUITPY` (`lib/bm83`, `lib/nextion`, `lib/blehid`, `lib/utils`, and project `main.py` if needed).
2. Re-copy `firmware/circuitpython/*` to `CIRCUITPY`.
3. Reset the board and re-test in baseline `.py` mode.


Run commands from the repository root. See [deployment and rollback](deployment.md) before copying any output to hardware.

#!/bin/bash
set -euo pipefail

# Build CircuitPython .mpy files into a drag-and-drop-ready dist folder:
# dist/circuitpython/
#   main.py
#   settings.toml (if present)
#   <other non-.py assets...>
#   lib/<packages...>/*.mpy
#
# Source layout expected:
# firmware/circuitpython/
#   main.py
#   settings.toml (optional)
#   lib/<packages...>/*.py

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="${ROOT_DIR}/firmware/circuitpython"
SRC_LIB_DIR="${SRC_DIR}/lib"
DIST_DIR="${ROOT_DIR}/dist/circuitpython"
DIST_LIB_DIR="${DIST_DIR}/lib"

# Allow override (CI will set MPY_CROSS explicitly)
MPY_CROSS="${MPY_CROSS:-mpy-cross}"

# mpy-cross optimization level. -O2 strips docstrings and asserts which
# shrinks .mpy files ~10-25% and speeds import. Firmware code has no
# __doc__ lookups and no assert statements, so -O2 is safe. Override
# via env if you want -O0 (default, full debug info) or -O3 (also
# strips source line numbers — smaller, faster, fuzzier tracebacks).
MPY_CROSS_OPT_LEVEL="${MPY_CROSS_OPT_LEVEL:-2}"

# The mpy-cross version is pinned in tools/mpy_cross_pin.env so dist builds
# are reproducible (issue #148). A mismatched compiler fails the build;
# MPY_CROSS_ALLOW_UNPINNED=1 downgrades that to a warning for local
# experiments (e.g. testing a new CircuitPython release before bumping the pin).
PIN_FILE="${ROOT_DIR}/tools/mpy_cross_pin.env"
BUILD_INFO_FILE="${ROOT_DIR}/dist/BUILD_INFO.txt"

# -------------------------
# Preconditions
# -------------------------
if [[ ! -d "${SRC_DIR}" ]]; then
  echo "Error: Source directory does not exist: ${SRC_DIR}" >&2
  exit 1
fi

if ! command -v "${MPY_CROSS}" >/dev/null 2>&1; then
  echo "mpy-cross not found. Run scripts/fetch_mpy_cross.sh, or set MPY_CROSS=/path/to/mpy-cross." >&2
  exit 1
fi

if [[ ! -f "${PIN_FILE}" ]]; then
  echo "Error: mpy-cross pin file not found: ${PIN_FILE}" >&2
  exit 1
fi
# shellcheck source=tools/mpy_cross_pin.env
source "${PIN_FILE}"

# Some builds exit non-zero for --version; the parsed version is what counts.
MPY_CROSS_VERSION_OUTPUT="$("${MPY_CROSS}" --version 2>&1 || true)"
MPY_CROSS_ACTUAL_VERSION="$(sed -nE 's/^CircuitPython ([^ ]+) on .*/\1/p' <<< "${MPY_CROSS_VERSION_OUTPUT}" | head -n 1)"
if [[ "${MPY_CROSS_ACTUAL_VERSION}" != "${MPY_CROSS_VERSION}" ]]; then
  echo "mpy-cross version mismatch: pinned ${MPY_CROSS_VERSION}, got '${MPY_CROSS_ACTUAL_VERSION:-unknown}'" >&2
  echo "  ${MPY_CROSS} --version: ${MPY_CROSS_VERSION_OUTPUT}" >&2
  if [[ "${MPY_CROSS_ALLOW_UNPINNED:-0}" != "1" ]]; then
    echo "Run scripts/fetch_mpy_cross.sh for the pinned compiler, or set MPY_CROSS_ALLOW_UNPINNED=1." >&2
    exit 1
  fi
  echo "Warning: MPY_CROSS_ALLOW_UNPINNED=1, continuing with an unpinned mpy-cross." >&2
fi

if [[ ! -f "${SRC_DIR}/main.py" ]]; then
  echo "Error: Entry point not found: ${SRC_DIR}/main.py" >&2
  exit 1
fi
if [[ ! -d "${SRC_LIB_DIR}" ]]; then
  echo "Error: Library source directory not found: ${SRC_LIB_DIR}" >&2
  exit 1
fi

# -------------------------
# Clean + create dist dirs
# -------------------------
rm -rf "${DIST_DIR}"
mkdir -p "${DIST_DIR}" "${DIST_LIB_DIR}"

# -------------------------
# Copy entrypoint + config
# -------------------------
# IMPORTANT: Keep entrypoint as .py (do NOT compile main.py)
cp -p "${SRC_DIR}/main.py" "${DIST_DIR}/main.py"

# Copy settings.toml if present (common CircuitPython config file)
if [[ -f "${SRC_DIR}/settings.toml" ]]; then
  cp -p "${SRC_DIR}/settings.toml" "${DIST_DIR}/settings.toml"
fi

# -------------------------
# Copy non-.py assets
# -------------------------
# Copies things like images, json, txt, etc., preserving folder structure,
# while skipping __pycache__.
#
# Note: We don't copy any *.py files (except main.py which we handled above).
if command -v rsync >/dev/null 2>&1; then
  rsync -a \
    --exclude="__pycache__" \
    --exclude="*.py" \
    --exclude="lib/" \
    "${SRC_DIR}/" "${DIST_DIR}/"
else
  echo "rsync not found; falling back to cp. Install rsync for faster builds." >&2
  copy_failed=0

  # Note: `while ... done < <(cmd)` does NOT spawn a subshell in bash, so
  # copy_failed set inside the loop is visible here.
  while IFS= read -r -d '' file; do
    rel_path="${file#"${SRC_DIR}"/}"
    dest="${DIST_DIR}/${rel_path}"
    if ! mkdir -p "$(dirname "${dest}")" || ! cp -p "${file}" "${dest}"; then
      echo "Error: Failed to copy ${file} to ${dest}" >&2
      copy_failed=1
      break
    fi
  done < <(find "${SRC_DIR}" -type f ! -name "*.py" ! -path "*/__pycache__/*" -print0)

  if (( copy_failed )); then
    exit 1
  fi
fi

# -------------------------
# Compile modules to .mpy under dist/lib
# -------------------------
# Compile every .py EXCEPT main.py, preserving package structure under lib/.
# Example:
#   firmware/circuitpython/lib/bm83/bm83.py  -> dist/circuitpython/lib/bm83/bm83.mpy
while IFS= read -r -d '' py_file; do
  rel_path="${py_file#"${SRC_LIB_DIR}"/}"

  out_file="${DIST_LIB_DIR}/${rel_path%.py}.mpy"
  mkdir -p "$(dirname "${out_file}")"
  "${MPY_CROSS}" -O"${MPY_CROSS_OPT_LEVEL}" -o "${out_file}" "${py_file}"
done < <(find "${SRC_LIB_DIR}" -type f -name "*.py" -print0)

# -------------------------
# Record build metadata
# -------------------------
# Kept beside (not inside) dist/circuitpython so it never lands on CIRCUITPY.
{
  echo "mpy_cross_pinned=${MPY_CROSS_VERSION}"
  echo "mpy_cross_version=${MPY_CROSS_VERSION_OUTPUT}"
  echo "mpy_cross_opt_level=${MPY_CROSS_OPT_LEVEL}"
  echo "source_commit=$(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null || echo unknown)"
} > "${BUILD_INFO_FILE}"

echo "✅ MPY build complete: ${DIST_DIR}"
echo "   - mpy-cross: ${MPY_CROSS_VERSION_OUTPUT}"
echo "   - Entry point: ${DIST_DIR}/main.py"
echo "   - Compiled libs: ${DIST_LIB_DIR}/"

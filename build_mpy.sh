#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="${ROOT_DIR}/firmware/circuitpython"
BUILD_DIR="${ROOT_DIR}/build/mpy"
DIST_DIR="${ROOT_DIR}/dist/circuitpython"
MPY_CROSS="${MPY_CROSS:-mpy-cross}"

if ! command -v "${MPY_CROSS}" >/dev/null 2>&1; then
  echo "mpy-cross not found. Install it or set MPY_CROSS=/path/to/mpy-cross."
  exit 1
fi

rm -rf "${BUILD_DIR}" "${DIST_DIR}"
mkdir -p "${BUILD_DIR}" "${DIST_DIR}"

rsync -av --exclude="__pycache__" --exclude="*.py" "${SRC_DIR}/" "${DIST_DIR}/"

while IFS= read -r -d '' py_file; do
  rel_path="${py_file#${SRC_DIR}/}"
  out_file="${DIST_DIR}/${rel_path%.py}.mpy"
  mkdir -p "$(dirname "${out_file}")"
  "${MPY_CROSS}" -o "${out_file}" "${py_file}"
done < <(find "${SRC_DIR}" -type f -name "*.py" -print0)

echo "✅ MPY build complete: ${DIST_DIR}"

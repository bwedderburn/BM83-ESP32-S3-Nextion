#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="${ROOT_DIR}/firmware/circuitpython"
DIST_DIR="${ROOT_DIR}/dist/circuitpython"
MPY_CROSS="${MPY_CROSS:-mpy-cross}"

if ! command -v "${MPY_CROSS}" >/dev/null 2>&1; then
  echo "mpy-cross not found. Install it or set MPY_CROSS=/path/to/mpy-cross."
  exit 1
fi

if [[ ! -d "${SRC_DIR}" ]]; then
  echo "Error: Source directory ${SRC_DIR} does not exist" >&2
  exit 1
fi

rm -rf "${DIST_DIR}"
mkdir -p "${DIST_DIR}"

if command -v rsync >/dev/null 2>&1; then
  rsync -a --exclude="__pycache__" --exclude="*.py" "${SRC_DIR}/" "${DIST_DIR}/"
else
  echo "rsync not found; falling back to cp. Install rsync for faster builds." >&2
  # Use a temp file to track errors in the loop
  error_flag=$(mktemp)
  trap 'rm -f "${error_flag}"' EXIT
  
  while IFS= read -r -d '' file; do
    rel_path="${file#"${SRC_DIR}"/}"
    dest="${DIST_DIR}/${rel_path}"
    if ! mkdir -p "$(dirname "${dest}")" || ! cp -p "${file}" "${dest}"; then
      echo "Error: Failed to copy ${file} to ${dest}" >&2
      touch "${error_flag}"
      break
    fi
  done < <(find "${SRC_DIR}" -type f ! -name "*.py" ! -path "*/__pycache__/*" -print0)
  
  if [[ -f "${error_flag}" ]]; then
    rm -f "${error_flag}"
    exit 1
  fi
  rm -f "${error_flag}"
fi

while IFS= read -r -d '' py_file; do
  rel_path="${py_file#"${SRC_DIR}"/}"
  out_file="${DIST_DIR}/${rel_path%.py}.mpy"
  mkdir -p "$(dirname "${out_file}")"
  "${MPY_CROSS}" -o "${out_file}" "${py_file}"
done < <(find "${SRC_DIR}" -type f -name "*.py" -print0)

echo "✅ MPY build complete: ${DIST_DIR}"

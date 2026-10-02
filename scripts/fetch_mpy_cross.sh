#!/bin/bash
set -euo pipefail

# Download the pinned CircuitPython mpy-cross (tools/mpy_cross_pin.env) and
# verify its sha256 and reported version before it is used.
#
# Usage: scripts/fetch_mpy_cross.sh [output_path]
#   output_path defaults to tools/mpy-cross/mpy-cross
#
# Then build with:  MPY_CROSS=tools/mpy-cross/mpy-cross ./build_mpy.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIN_FILE="${ROOT_DIR}/tools/mpy_cross_pin.env"
OUT="${1:-${ROOT_DIR}/tools/mpy-cross/mpy-cross}"
S3_BASE="https://adafruit-circuit-python.s3.amazonaws.com"

# shellcheck source=../tools/mpy_cross_pin.env
source "${PIN_FILE}"

if [[ "$(uname -s)-$(uname -m)" != "Linux-x86_64" ]]; then
  echo "Error: only a linux-amd64 checksum is pinned (WSL works)." >&2
  echo "Elsewhere, install CircuitPython mpy-cross ${MPY_CROSS_VERSION} by hand and set MPY_CROSS." >&2
  exit 1
fi

mkdir -p "$(dirname "${OUT}")"
tmp="$(mktemp "${OUT}.XXXXXX")"
trap 'rm -f "${tmp}"' EXIT

curl -fsSL -o "${tmp}" "${S3_BASE}/${MPY_CROSS_LINUX_AMD64_KEY}"

actual_sha="$(sha256sum "${tmp}" | cut -d' ' -f1)"
if [[ "${actual_sha}" != "${MPY_CROSS_LINUX_AMD64_SHA256}" ]]; then
  echo "Error: sha256 mismatch for ${MPY_CROSS_LINUX_AMD64_KEY}" >&2
  echo "  expected ${MPY_CROSS_LINUX_AMD64_SHA256}" >&2
  echo "  got      ${actual_sha}" >&2
  exit 1
fi

chmod +x "${tmp}"
mv "${tmp}" "${OUT}"
trap - EXIT

echo "✅ mpy-cross ${MPY_CROSS_VERSION} verified: ${OUT}"
"${OUT}" --version

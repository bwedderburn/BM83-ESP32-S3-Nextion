#!/bin/bash
set -euo pipefail

# Deployment script to copy project files to CIRCUITPY device.
#
# Usage:
#   ./deploy.sh              Deploy .py source from firmware/circuitpython/
#                            (easy to inspect/edit on the board; default).
#   ./deploy.sh --mpy        Deploy compiled .mpy build from dist/circuitpython/
#                            (smaller, faster import; requires build_mpy.sh
#                            to have been run after the last source change).
#   ./deploy.sh -h | --help  Show this help.
#
# CIRCUITPY_PATH overrides the destination drive. On Linux the default
# is /media/$USER/CIRCUITPY; on Windows / Git Bash, set it to the drive
# letter the board mounted as, e.g. CIRCUITPY_PATH=/e/ ./deploy.sh.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${CIRCUITPY_PATH:=/media/${USER:-$(whoami)}/CIRCUITPY}"

MODE="src"  # "src" = firmware/circuitpython (.py), "mpy" = dist/circuitpython (.mpy)

for arg in "$@"; do
  case "$arg" in
    --mpy)
      MODE="mpy"
      ;;
    --src|--py)
      MODE="src"
      ;;
    -h|--help)
      sed -n '4,15p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown flag: $arg" >&2
      echo "Try: $0 --help" >&2
      exit 2
      ;;
  esac
done

if [ "$MODE" = "mpy" ]; then
  SRC_DIR="$REPO_DIR/dist/circuitpython"
  SRC_LABEL="dist/circuitpython (.mpy build)"
  if [ ! -f "$SRC_DIR/main.py" ] || [ ! -d "$SRC_DIR/lib" ]; then
    echo "dist/circuitpython is missing or incomplete." >&2
    echo "Run ./build_mpy.sh first, then retry with --mpy." >&2
    exit 1
  fi
  # Warn if dist looks older than firmware — the .mpy build is stale and
  # would flash older code than what's on disk in firmware/.
  if [ -n "$(find "$REPO_DIR/firmware/circuitpython" -newer "$SRC_DIR/main.py" -type f -print -quit 2>/dev/null)" ]; then
    echo "⚠️  firmware/ has files newer than dist/circuitpython/main.py."
    echo "    The .mpy build may be stale. Run ./build_mpy.sh to refresh."
  fi
else
  SRC_DIR="$REPO_DIR/firmware/circuitpython"
  SRC_LABEL="firmware/circuitpython (.py source)"
fi

if [ ! -d "$CIRCUITPY_PATH" ]; then
  echo "CIRCUITPY drive not found at $CIRCUITPY_PATH" >&2
  echo "If the board is connected, set CIRCUITPY_PATH to its mount point:" >&2
  echo "  CIRCUITPY_PATH=/e/ $0 $*" >&2
  exit 1
fi

echo "Deploying $SRC_LABEL -> $CIRCUITPY_PATH..."

# Prefer rsync (skips unchanged files, fast). Fall back to cp on systems
# without rsync (notably Git Bash / MSYS on Windows). The cp path is a
# full overwrite each time — slower but correct.
if command -v rsync >/dev/null 2>&1; then
  rsync -av --exclude="__pycache__" "$SRC_DIR/main.py" "$CIRCUITPY_PATH/"
  mkdir -p "$CIRCUITPY_PATH/lib"
  rsync -av --exclude="__pycache__" "$SRC_DIR/lib/" "$CIRCUITPY_PATH/lib/"
else
  echo "rsync not found; falling back to cp. Install rsync for faster deploys."
  cp "$SRC_DIR/main.py" "$CIRCUITPY_PATH/main.py"
  mkdir -p "$CIRCUITPY_PATH/lib"
  # cp -r the lib tree, excluding __pycache__ dirs after the fact since
  # plain cp has no --exclude. Faster than find-piping for this size.
  cp -r "$SRC_DIR/lib/." "$CIRCUITPY_PATH/lib/"
  find "$CIRCUITPY_PATH/lib" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
fi

echo "✅ Deployment complete!"

#!/bin/bash
set -euo pipefail

# Deployment script to copy project files to CIRCUITPY device
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${CIRCUITPY_PATH:=/media/${USER:-$(whoami)}/CIRCUITPY}"

if [ ! -d "$CIRCUITPY_PATH" ]; then
  echo "CIRCUITPY drive not found at $CIRCUITPY_PATH"
  exit 1
fi

echo "Deploying to $CIRCUITPY_PATH..."

# Prefer rsync (skips unchanged files, fast). Fall back to cp on systems
# without rsync (notably Git Bash / MSYS on Windows). The cp path is a
# full overwrite each time — slower but correct.
if command -v rsync >/dev/null 2>&1; then
  rsync -av --exclude="__pycache__" "$REPO_DIR/firmware/circuitpython/main.py" "$CIRCUITPY_PATH/"
  mkdir -p "$CIRCUITPY_PATH/lib"
  rsync -av --exclude="__pycache__" "$REPO_DIR/firmware/circuitpython/lib/" "$CIRCUITPY_PATH/lib/"
else
  echo "rsync not found; falling back to cp. Install rsync for faster deploys."
  cp "$REPO_DIR/firmware/circuitpython/main.py" "$CIRCUITPY_PATH/main.py"
  mkdir -p "$CIRCUITPY_PATH/lib"
  # cp -r the lib tree, excluding __pycache__ dirs after the fact since
  # plain cp has no --exclude. Faster than find-piping for this size.
  cp -r "$REPO_DIR/firmware/circuitpython/lib/." "$CIRCUITPY_PATH/lib/"
  find "$CIRCUITPY_PATH/lib" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
fi

echo "✅ Deployment complete!"

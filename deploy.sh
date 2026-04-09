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

rsync -av --exclude="__pycache__" "$REPO_DIR/firmware/circuitpython/main.py" "$CIRCUITPY_PATH/"
mkdir -p "$CIRCUITPY_PATH/lib"
rsync -av --exclude="__pycache__" "$REPO_DIR/firmware/circuitpython/lib/" "$CIRCUITPY_PATH/lib/"

echo "✅ Deployment complete!"

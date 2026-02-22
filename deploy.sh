#!/bin/bash
set -euo pipefail

# Deployment script to copy project files to CIRCUITPY device
CIRCUITPY_PATH="${CIRCUITPY_PATH:-/media/$USER/CIRCUITPY}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_ROOT="${BACKUP_ROOT:-$REPO_DIR/backups}"
SOURCE_DIR="${SOURCE_DIR:-$REPO_DIR/dist/circuitpython}"

if [[ ! -d "$SOURCE_DIR" ]]; then
  SOURCE_DIR="$REPO_DIR/firmware/circuitpython"
fi
if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "Firmware source not found. Checked dist/circuitpython and firmware/circuitpython." >&2
  exit 1
fi

if [ ! -d "$CIRCUITPY_PATH" ]; then
  echo "CIRCUITPY drive not found at $CIRCUITPY_PATH"
  exit 1
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$BACKUP_ROOT/circuitpy-$STAMP"
mkdir -p "$BACKUP_DIR"
echo "Saving backup from $CIRCUITPY_PATH to $BACKUP_DIR..."
if ! rsync -a "$CIRCUITPY_PATH"/ "$BACKUP_DIR"/; then
  echo "Backup failed; deployment aborted." >&2
  exit 1
fi

if [[ "${1:-}" == "--backup-only" ]]; then
  echo "✅ Backup complete (no deployment performed)."
  exit 0
fi

echo "Deploying from $SOURCE_DIR to $CIRCUITPY_PATH..."

rsync -av --exclude="__pycache__" "$SOURCE_DIR"/ "$CIRCUITPY_PATH"/

echo "✅ Deployment complete!"

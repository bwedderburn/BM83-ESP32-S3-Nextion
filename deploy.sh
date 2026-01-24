#!/bin/bash

# Deployment script to copy project files to CIRCUITPY device
# Set this to your mounted CIRCUITPY path
CIRCUITPY_PATH=/media/$USER/CIRCUITPY

if [ ! -d "$CIRCUITPY_PATH" ]; then
  echo "CIRCUITPY drive not found at $CIRCUITPY_PATH"
  exit 1
fi

echo "Deploying to $CIRCUITPY_PATH..."

rsync -av --exclude="__pycache__"   main.py utils/ nextion/ blehid/ bm83/   "$CIRCUITPY_PATH"

echo "✅ Deployment complete!"

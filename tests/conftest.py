"""Pytest configuration file to set up paths for importing firmware modules."""
import sys
from pathlib import Path

# Add firmware directory to path for all tests
FIRMWARE_DIR = Path(__file__).parent.parent / "firmware" / "circuitpython"
sys.path.insert(0, str(FIRMWARE_DIR))

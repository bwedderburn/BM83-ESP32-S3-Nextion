import sys
from pathlib import Path

# Add firmware directory to path
FIRMWARE_DIR = Path(__file__).parent.parent / "firmware" / "circuitpython"
sys.path.insert(0, str(FIRMWARE_DIR))

from utils.common import _sanitize_text, _fmt_ms  # noqa: E402


def test_sanitize_text_basic():
    assert _sanitize_text("Hello!") == "Hello!"
    assert _sanitize_text("Bad\x00Char") == "Bad Char"

def test_fmt_ms():
    assert _fmt_ms(65000) == "1:05"
    assert _fmt_ms(3700000) == "1:01:40"

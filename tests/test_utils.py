from utils.common import _sanitize_text, _fmt_ms


def test_sanitize_text_basic():
    assert _sanitize_text("Hello!") == "Hello!"
    assert _sanitize_text("Bad\x00Char") == "Bad Char"

def test_fmt_ms():
    assert _fmt_ms(65000) == "1:05"
    assert _fmt_ms(3700000) == "1:01:40"

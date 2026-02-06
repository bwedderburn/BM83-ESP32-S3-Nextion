from utils.common import _sanitize_text, _fmt_ms, sanitize_text, fmt_ms


def test_sanitize_text_basic():
    assert _sanitize_text("Hello!") == "Hello!"
    assert _sanitize_text("Bad\x00Char") == "Bad Char"


def test_fmt_ms():
    assert _fmt_ms(65000) == "1:05"
    assert _fmt_ms(3700000) == "1:01:40"


def test_public_sanitize_text_ellipsis():
    assert sanitize_text("A" * 8, max_len=6) == "AAA..."


def test_public_fmt_ms_zero_pad():
    assert fmt_ms(5000) == "00:05"

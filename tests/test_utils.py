from utils.common import (
    TIME_UNKNOWN,
    _fmt_ms,
    _fmt_track_time_ms,
    _normalize_track_time_ms,
    _sanitize_text,
    fmt_ms,
    sanitize_text,
)


def test_sanitize_text_basic():
    assert _sanitize_text("Hello!") == "Hello!"
    assert _sanitize_text("Bad\x00Char") == "Bad Char"


def test_fmt_ms():
    assert _fmt_ms(65000) == "1:05"
    assert _fmt_ms(3700000) == "1:01:40"


def test_normalize_track_time_ms_prefers_playstatus_baseline_for_attr_seconds():
    assert _normalize_track_time_ms("773", ref_ms=773000, from_attr=True) == 773000
    assert _fmt_track_time_ms("773", ref_ms=773000, from_attr=True) == "12:53"


def test_normalize_track_time_ms_rejects_invalid_and_oversized_values():
    assert _normalize_track_time_ms("7:73", from_attr=True) is None
    assert _fmt_track_time_ms("7:73", from_attr=True) == TIME_UNKNOWN
    assert _normalize_track_time_ms(25 * 60 * 60 * 1000) is None


def test_public_sanitize_text_ellipsis():
    assert sanitize_text("A" * 8, max_len=6) == "AAA..."


def test_public_fmt_ms_zero_pad():
    assert fmt_ms(5000) == "00:05"

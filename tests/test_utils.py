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
    assert _normalize_track_time_ms("773", ref_ms=0, from_attr=True) == 773000


def test_normalize_track_time_ms_rejects_invalid_and_oversized_values():
    assert _normalize_track_time_ms("7:73", from_attr=True) is None
    assert _fmt_track_time_ms("7:73", from_attr=True) == TIME_UNKNOWN
    assert _normalize_track_time_ms(25 * 60 * 60 * 1000) is None


def test_public_sanitize_text_ellipsis():
    assert sanitize_text("A" * 8, max_len=6) == "AAA..."


def test_public_fmt_ms_zero_pad():
    assert fmt_ms(5000) == "00:05"


def test_internal_sanitize_text_truncation_stays_ascii():
    """Truncated text must survive the Nextion TX path's ascii encode.

    Regression for the 2026-08 review finding: the old ellipsis was
    U+2026, which _sanitize_impl's 32..126 guarantee never covered and
    which encode("ascii", "replace") in Nextion.tick() rendered as "?"
    on the display. All output chars must stay in the ASCII range.
    """
    out = _sanitize_text("A" * 60, max_len=48)
    assert out.endswith("...")
    assert all(32 <= ord(ch) <= 126 for ch in out)
    assert out.encode("ascii") == out.encode("ascii", "replace")

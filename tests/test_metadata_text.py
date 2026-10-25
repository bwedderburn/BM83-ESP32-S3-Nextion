"""Metadata spacing must render without erasing real Unicode names."""

import pytest

from remote.metadata_text import normalize_metadata_text


@pytest.mark.parametrize("space", [
    "\u0085", "\u00a0", "\u1680", "\u2000", "\u2001", "\u2002", "\u2003",
    "\u2004", "\u2005", "\u2006", "\u2007", "\u2008", "\u2009", "\u200a",
    "\u2028", "\u2029", "\u202f", "\u205f", "\u3000",
])
def test_unicode_spacing_between_words_becomes_visible_space(space):
    assert normalize_metadata_text("Track" + space + "Title") == "Track Title"


def test_double_spaces_retain_their_count():
    assert normalize_metadata_text("Track  Title") == "Track  Title"
    assert normalize_metadata_text("Track\u00a0\u2002Title") == "Track  Title"


def test_controls_become_spaces_without_joining_words():
    assert normalize_metadata_text("A\x00B\tC\nD\rE\x7fF\x80G\x9fH") == "A B C D E F G H"


def test_invisible_break_markers_are_removed():
    assert normalize_metadata_text("\ufeffTrack\u200b\u2060 title\ufeff") == "Track title"


def test_unicode_names_punctuation_and_meaningful_joiners_are_preserved():
    text = "Björk — Jóga ‘Live’ / 東京 / الف\u200cباء / 👩\u200d🎤"
    assert normalize_metadata_text(text) == text
    assert normalize_metadata_text(text).encode("utf-8").decode("utf-8") == text


def test_empty_and_non_string_fields():
    assert normalize_metadata_text(None) == ""
    assert normalize_metadata_text("") == ""
    assert normalize_metadata_text(42) == "42"

"""Keep the captured Windows compound fields separate without broad guesses."""
import pytest

from utils.metadata_fields import recover_metadata_fields


@pytest.mark.parametrize("album_field", [{}, {3: None}, {3: ""}, {3: " \t\r\n "}])
def test_recovers_captured_windows_shape_only_when_album_is_missing(album_field):
    attrs = {1: "Kind", 2: "Plini — Sunhead - EP", 4: "0", **album_field}
    before = dict(attrs)
    recovered = recover_metadata_fields(attrs)
    assert recovered is not attrs
    assert recovered[1] == "Kind"
    assert recovered[2] == "Plini"
    assert recovered[3] == "Sunhead - EP"
    assert recovered[4] == attrs[4] == "0"
    assert attrs == before
    assert recover_metadata_fields(recovered) is recovered


@pytest.mark.parametrize("artist,album", [
    ("Plini", "Sunhead - EP"),
    ("Artist", "Song - Single"),
    ("Björk", "Jóga - Single"),
    ("Chimp Spanner", "At the Dreams Edge"),
    ("Artist", "Left - Right - EP"),
])
def test_retains_album_suffixes_accents_and_genuine_hyphens(artist, album):
    title = "Flâneur (feat. Anomalie)"
    recovered = recover_metadata_fields({1: title, 2: "  " + artist + " — " + album + "  ", 4: "0"})
    assert recovered == {1: title, 2: artist, 3: album, 4: "0"}


@pytest.mark.parametrize("album", ["Explicit album", " Existing - EP ", "—", 0, b"", [], False])
def test_never_overrides_existing_or_untyped_album_data(album):
    attrs = {1: "Song", 2: "Artist — Candidate album", 3: album, 4: "0"}
    assert recover_metadata_fields(attrs) is attrs


@pytest.mark.parametrize("artist", [
    "Plini  Sunhead - EP", "Plini Sunhead - EP", "Plini - Sunhead - EP",
    "Plini – Sunhead - EP", "Plini—Sunhead - EP", "Plini —Sunhead - EP",
    "Plini— Sunhead - EP", "Artist — Album — Another", " — Album", "Artist — ",
    "", "   ", None, 123, b"Artist -- Album",
])
def test_rejects_unobserved_delimiters_ambiguous_and_incomplete_names(artist):
    attrs = {1: "Song", 2: artist, 4: "0"}
    assert recover_metadata_fields(attrs) is attrs


@pytest.mark.parametrize("title", [None, "", " \t ", 12, b"Song"])
def test_requires_a_known_title_before_recovering_compound_artist(title):
    attrs = {1: title, 2: "Artist — Album", 4: "0"}
    assert recover_metadata_fields(attrs) is attrs
    missing = {2: "Artist — Album", 4: "0"}
    assert recover_metadata_fields(missing) is missing


@pytest.mark.parametrize("attrs", [None, (), [], b"", "Artist — Album"])
def test_other_input_types_are_not_reinterpreted(attrs):
    assert recover_metadata_fields(attrs) is attrs


@pytest.mark.parametrize("track", [None, "", "1", "00", " 0 ", 0, 1, False, b"0"])
def test_does_not_split_genuine_artist_without_exact_windows_track_marker(track):
    attrs = {1: "Song", 2: "Artist — Alias", 4: track}
    assert recover_metadata_fields(attrs) is attrs
    missing = {1: "Song", 2: "Artist — Alias"}
    assert recover_metadata_fields(missing) is missing


@pytest.mark.parametrize("extra", [{5: "12"}, {6: "Rock"}, {7: "180000"},
                                   {99: "Unknown"}, {"source": "Windows"}])
def test_does_not_reinterpret_a_different_reply_profile(extra):
    attrs = {1: "Song", 2: "Artist — Alias", 4: "0", **extra}
    assert recover_metadata_fields(attrs) is attrs


def test_full_iphone_style_reply_retains_genuine_em_dash_artist():
    attrs = {1: "Song", 2: "Artist — Alias", 3: "", 4: "0", 5: "12", 6: "Rock", 7: "180000"}
    assert recover_metadata_fields(attrs) is attrs
    assert attrs[2] == "Artist — Alias" and attrs[3] == ""

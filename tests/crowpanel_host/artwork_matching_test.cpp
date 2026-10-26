#include "matching.h"

#include <assert.h>
#include <cstdlib>
#include <iostream>
#include <string>

using artwork_matching::Candidate;
using artwork_matching::Outcome;
using artwork_matching::Query;

static const char *GROUP_A = "a1234567-1234-1234-1234-123456789abc";
static const char *GROUP_B = "b1234567-1234-1234-1234-123456789abc";

static Candidate match(const char *artist = "Artist", const char *album = "Album",
                       const char *title = "Song", const char *group = GROUP_A) {
    return {artist, album, title, group, 100, 1, false, nullptr};
}

static void exact_album() {
    const Query query = {"Artist", "Album", "Song"};
    const Candidate candidates[] = {match("Someone Else"), match()};
    const auto result = artwork_matching::select_album(query, candidates, 2);
    assert(result.outcome == Outcome::Matched && result.index == 1);
}

static void normalized_identity() {
    const Query query = {"  ARTIST  ", "Album\xC2\xA0Name", "Song"};
    const Candidate candidate = match("artist", "album  name");
    assert(artwork_matching::select_album(query, &candidate, 1).outcome == Outcome::Matched);
    assert(artwork_matching::normalized_key("Guns N\xE2\x80\x99 Roses") == "guns n' roses");
    assert(artwork_matching::normalized_key("AC/DC") != artwork_matching::normalized_key("ACDC"));
    assert(artwork_matching::normalized_key("P!nk") != artwork_matching::normalized_key("Pink"));
}

static void missing_album_recording_fallback() {
    const Candidate candidate = match();
    assert(artwork_matching::select_album({"Artist", "", "Song"}, &candidate, 1).outcome == Outcome::NoMatch);
    assert(artwork_matching::select_recording({"Artist", "", "Song"}, &candidate, 1).outcome == Outcome::Matched);
    assert(artwork_matching::select_recording({"Artist", nullptr, " Song "}, &candidate, 1).outcome == Outcome::Matched);
    assert(artwork_matching::select_recording({"Artist", "", ""}, &candidate, 1).outcome == Outcome::NoMatch);
}

static void conservative_remasters() {
    assert(artwork_matching::normalized_key("Album (2011 Remaster)", true) == "album");
    assert(artwork_matching::normalized_key("Album [Remastered 2009]", true) == "album");
    assert(artwork_matching::normalized_key("Album - Remastered", true) == "album");
    assert(artwork_matching::normalized_key("Album (Live)", true) == "album (live)");
    assert(artwork_matching::normalized_key("Album (Deluxe)", true) == "album (deluxe)");
    assert(artwork_matching::normalized_key("Album (2011 Remastered Live)", true) == "album (2011 remastered live)");
    assert(artwork_matching::normalized_key("Album (1800 Remaster)", true) == "album (1800 remaster)");
    const Candidate remaster = match("Artist", "Album (2011 Remaster)", "Song (Remastered 2011)");
    assert(artwork_matching::select_album({"Artist", "Album", "Song"}, &remaster, 1).outcome == Outcome::Matched);
    assert(artwork_matching::select_recording({"Artist", "", "Song"}, &remaster, 1).outcome == Outcome::Matched);
    const Candidate live = match("Artist", "Album (Live)", "Song (Live)");
    assert(artwork_matching::select_album({"Artist", "Album", "Song"}, &live, 1).outcome == Outcome::NoMatch);
    assert(artwork_matching::select_recording({"Artist", "", "Song"}, &live, 1).outcome == Outcome::NoMatch);
}

static void duplicate_editions_same_group() {
    Candidate candidates[] = {match(), match("Artist", "Album (Remastered)")};
    candidates[0].score = 98;
    assert(artwork_matching::select_album({"Artist", "Album", ""}, candidates, 2).index == 1);
    candidates[1].art_id = "A1234567-1234-1234-1234-123456789ABC";
    assert(artwork_matching::select_album({"Artist", "Album", ""}, candidates, 2).outcome == Outcome::Matched);
}

static void multiple_groups_ambiguous() {
    const Candidate candidates[] = {match(), match("Artist", "Other Album", "Song", GROUP_B)};
    assert(artwork_matching::select_recording({"Artist", "", "Song"}, candidates, 2).outcome == Outcome::Ambiguous);
    assert(artwork_matching::select_recording({"Artist", "Album", "Song"}, candidates, 2).outcome == Outcome::Matched);
    const Candidate albums[] = {match(), match("Artist", "Album", "Song", GROUP_B)};
    assert(artwork_matching::select_album({"Artist", "Album", ""}, albums, 2).outcome == Outcome::Ambiguous);
}

static void generic_compilation_and_multiartist() {
    Candidate candidate = match();
    candidate.compilation = true;
    assert(artwork_matching::select_recording({"Artist", "", "Song"}, &candidate, 1).outcome == Outcome::NoMatch);
    candidate = match("Various Artists");
    assert(artwork_matching::select_album({"Various Artists", "Album", "Song"}, &candidate, 1).outcome == Outcome::NoMatch);
    candidate = match();
    candidate.artist_credit_count = 2;
    assert(artwork_matching::select_recording({"Artist", "", "Song"}, &candidate, 1).outcome == Outcome::NoMatch);
    candidate.artist_credit_count = 0;
    assert(artwork_matching::select_album({"Artist", "Album", "Song"}, &candidate, 1).outcome == Outcome::NoMatch);
}

static void no_fuzzy_substrings_or_score_guess() {
    Candidate candidate = match("Artist", "Album", "Song Extended");
    assert(artwork_matching::select_recording({"Artist", "", "Song"}, &candidate, 1).outcome == Outcome::NoMatch);
    candidate = match("Artist Tribute");
    assert(artwork_matching::select_album({"Artist", "Album", ""}, &candidate, 1).outcome == Outcome::NoMatch);
    candidate = match();
    candidate.score = 94;
    assert(artwork_matching::select_album({"Artist", "Album", ""}, &candidate, 1).outcome == Outcome::NoMatch);
    candidate.score = 101;
    assert(artwork_matching::select_album({"Artist", "Album", ""}, &candidate, 1).outcome == Outcome::NoMatch);
}

static void unicode_preservation() {
    const char *artist = "Bj\xC3\xB6rk";
    const char *album = "\xE6\x9D\xB1\xE4\xBA\xAC";
    const char *song = "J\xC3\xB3ga";
    const Candidate candidate = match(artist, album, song);
    assert(artwork_matching::select_album({artist, album, song}, &candidate, 1).outcome == Outcome::Matched);
    assert(artwork_matching::select_recording({artist, "", song}, &candidate, 1).outcome == Outcome::Matched);
    assert(artwork_matching::select_recording({"Bjork", "", song}, &candidate, 1).outcome == Outcome::NoMatch);
    assert(artwork_matching::normalized_key(artist) == "bj\xC3\xB6rk");
    assert(artwork_matching::normalized_key("\xC0\xAF").empty());
    assert(artwork_matching::normalized_key("\xED\xA0\x80").empty());
    assert(artwork_matching::normalized_key("\xE2\x82").empty());
}

static void bounds_and_ids() {
    assert(artwork_matching::valid_mbid(GROUP_A));
    assert(!artwork_matching::valid_mbid(nullptr));
    assert(!artwork_matching::valid_mbid(""));
    assert(!artwork_matching::valid_mbid("../../../../etc/passwd"));
    assert(!artwork_matching::valid_mbid("00000000-0000-0000-0000-000000000000"));
    assert(!artwork_matching::valid_mbid("a1234567-1234-1234-1234-123456789abc?"));
    assert(!artwork_matching::valid_mbid("x1234567-1234-1234-1234-123456789abc"));
    const std::string overlong(artwork_matching::MAX_INPUT_BYTES + 1, 'a');
    assert(artwork_matching::normalized_key(overlong.c_str()).empty());
    const Candidate candidate = match();
    assert(artwork_matching::select_album({overlong.c_str(), "Album", ""}, &candidate, 1).outcome == Outcome::NoMatch);
    assert(artwork_matching::select_album({"Artist", "Album", ""}, nullptr, 1).outcome == Outcome::NoMatch);
    assert(artwork_matching::select_album({"Artist", "Album", ""}, &candidate, 0).outcome == Outcome::NoMatch);
    assert(artwork_matching::select_album({"Artist", "Album", ""}, &candidate,
                                         artwork_matching::MAX_CANDIDATES + 1).outcome == Outcome::NoMatch);
}

static void album_and_title_apostrophe_equivalence_keeps_cache_keys_stable() {
    const Query query = {"Chimp Spanner", "At the Dreams Edge", "Dreams"};
    Candidate candidate = match("Chimp Spanner", "At the Dream's Edge", "Dream's");
    assert(artwork_matching::select_album(query, &candidate, 1).outcome == Outcome::Matched);
    assert(artwork_matching::select_recording(query, &candidate, 1).outcome == Outcome::Matched);
    candidate.album = "At the Dream\xE2\x80\x99s Edge";
    candidate.title = "Dream\xE2\x80\x99s";
    assert(artwork_matching::select_album(query, &candidate, 1).outcome == Outcome::Matched);
    assert(artwork_matching::select_recording(query, &candidate, 1).outcome == Outcome::Matched);
    assert(artwork_matching::normalized_key("At the Dream's Edge", true) == "at the dream's edge");
    assert(artwork_matching::normalized_key("At the Dreams Edge", true) == "at the dreams edge");
    assert(artwork_matching::identity_key("At the Dream's Edge", true) == "at the dreams edge");
    assert(artwork_matching::identity_key("'Dreams'") != artwork_matching::identity_key("Dreams"));
    assert(artwork_matching::identity_key("Dreams'") != artwork_matching::identity_key("Dreams"));
    assert(artwork_matching::identity_key("Dream''s") != artwork_matching::identity_key("Dreams"));
}

static void apostrophe_equivalence_does_not_relax_artist_or_other_identity_rules() {
    Candidate candidate = match("O'Connor", "At the Dream's Edge", "Dream's");
    assert(artwork_matching::select_album({"OConnor", "At the Dreams Edge", ""}, &candidate, 1).outcome == Outcome::NoMatch);
    assert(artwork_matching::select_recording({"OConnor", "", "Dreams"}, &candidate, 1).outcome == Outcome::NoMatch);
    candidate = match("Chimp Spanner", "At the Dream's Edge", "Dream's");
    assert(artwork_matching::select_album({"Chimp Spanner", "At the Drams Edge", ""}, &candidate, 1).outcome == Outcome::NoMatch);
    candidate.score = 94;
    assert(artwork_matching::select_album({"Chimp Spanner", "At the Dreams Edge", ""}, &candidate, 1).outcome == Outcome::NoMatch);
    candidate.score = 100;
    candidate.artist_credit_count = 2;
    assert(artwork_matching::select_album({"Chimp Spanner", "At the Dreams Edge", ""}, &candidate, 1).outcome == Outcome::NoMatch);
    candidate.artist_credit_count = 1;
    candidate.compilation = true;
    assert(artwork_matching::select_album({"Chimp Spanner", "At the Dreams Edge", ""}, &candidate, 1).outcome == Outcome::NoMatch);
    const Candidate ambiguous[] = {
        match("Chimp Spanner", "At the Dream's Edge", "Dream's", GROUP_A),
        match("Chimp Spanner", "At the Dreams Edge", "Dreams", GROUP_B)
    };
    assert(artwork_matching::select_album({"Chimp Spanner", "At the Dreams Edge", ""}, ambiguous, 2).outcome == Outcome::Ambiguous);
}

static void bounded_fallback_query_emission() {
    std::string query;
    assert(artwork_matching::album_fallback_query({"Chimp Spanner", "At the Dreams Edge", ""}, query));
    assert(query == "releasegroup:(at AND the AND dreams~1 AND edge~1) AND artist:\"Chimp Spanner\"");
    assert(artwork_matching::album_fallback_query({"Chimp Spanner", "At the Dream\xE2\x80\x99s Edge", ""}, query));
    assert(query == "releasegroup:(at AND the AND dreams~1 AND edge~1) AND artist:\"Chimp Spanner\"");
    assert(artwork_matching::album_fallback_query({"A \"Quoted\" \\ Artist", "Some Album", ""}, query));
    assert(query == "releasegroup:(some~1 AND album~1) AND artist:\"A \\\"Quoted\\\" \\\\ Artist\"");
    assert(artwork_matching::album_fallback_query({"Artist", "a b c d e f g h", ""}, query));
    assert(query.size() <= artwork_matching::MAX_FALLBACK_QUERY_BYTES);
}

static void unsafe_or_overlong_fallback_is_not_emitted() {
    const char *albums[] = {"", "a b c d e f g h i", "AC/DC", "At-the-Dreams", "Album (Deluxe)",
                            "Album OR artist:Other", "'Album'", "Album'", "Alb''um", "\xE6\x9D\xB1\xE4\xBA\xAC"};
    for (const char *album : albums) {
        std::string output = "must be cleared";
        assert(!artwork_matching::album_fallback_query({"Artist", album, ""}, output));
        assert(output.empty());
    }
    std::string output = "must be cleared";
    assert(!artwork_matching::album_fallback_query({"Various Artists", "Album", ""}, output));
    assert(output.empty());
    assert(!artwork_matching::album_fallback_query({"Artist\nOther", "Album", ""}, output));
    assert(output.empty());
    const std::string long_album(artwork_matching::MAX_INPUT_BYTES + 1, 'a');
    assert(!artwork_matching::album_fallback_query({"Artist", long_album.c_str(), ""}, output));
    assert(output.empty());
    const std::string long_artist(370, 'a');
    assert(!artwork_matching::album_fallback_query({long_artist.c_str(), "Album", ""}, output));
    assert(output.empty());
}

static void typed_source_album_labels() {
    Candidate ep = match("Plini", "Sunhead", "Kind");
    ep.primary_type = "EP";
    const Query query = {"Plini", "Sunhead - EP", "Kind"};
    assert(artwork_matching::select_album(query, &ep, 1).outcome == Outcome::Matched);
    assert(artwork_matching::select_recording(query, &ep, 1).outcome == Outcome::Matched);
    Candidate single = match("Artist", "Song", "Song");
    single.primary_type = "Single";
    assert(artwork_matching::select_album({"Artist", "Song - Single", ""}, &single, 1).outcome == Outcome::Matched);
    // Existing punctuation/whitespace normalization applies before identifying
    // the exact trailing label, without altering the stored cache key.
    assert(artwork_matching::select_album({"Plini", " SUNHEAD \xE2\x80\x93 EP ", ""}, &ep, 1).outcome == Outcome::Matched);
    const Candidate apostrophe = {"Artist", "Dream's", "Song", GROUP_A, 100, 1, false, "EP"};
    assert(artwork_matching::select_album({"Artist", "Dreams - EP", ""}, &apostrophe, 1).outcome == Outcome::Matched);
    assert(artwork_matching::normalized_key("Sunhead - EP", true) == "sunhead - ep");
    assert(artwork_matching::normalized_key("Song - Single", true) == "song - single");
    assert(artwork_matching::normalized_key("Dream's - EP", true) == "dream's - ep");
    assert(artwork_matching::identity_key("Sunhead - EP", true) == "sunhead - ep");
}

static void typed_labels_require_exact_primary_type_only_when_needed() {
    Candidate candidate = match("Plini", "Sunhead", "Kind");
    const Query query = {"Plini", "Sunhead - EP", "Kind"};
    const char *types[] = {nullptr, "", "Album", "Single", "ep", "EP ", "EP/Single"};
    for (const char *type : types) {
        candidate.primary_type = type;
        assert(artwork_matching::select_album(query, &candidate, 1).outcome == Outcome::NoMatch);
        assert(artwork_matching::select_recording(query, &candidate, 1).outcome == Outcome::NoMatch);
    }
    candidate.primary_type = "EP";
    assert(artwork_matching::select_album({"Plini", "Sunhead - Single", ""}, &candidate, 1).outcome == Outcome::NoMatch);
    candidate.primary_type = "Single";
    assert(artwork_matching::select_album(query, &candidate, 1).outcome == Outcome::NoMatch);
    const char *wrong_single_types[] = {nullptr, "", "Album", "EP", "single", "Single "};
    for (const char *type : wrong_single_types) {
        candidate.primary_type = type;
        assert(artwork_matching::select_album({"Plini", "Sunhead - Single", ""}, &candidate, 1).outcome == Outcome::NoMatch);
    }
    candidate.album = "Sunhead - EP";
    // A literal title ending in EP was accepted before typed compatibility;
    // it still matches with no type or even a different primary type.
    for (const char *type : types) {
        candidate.primary_type = type;
        assert(artwork_matching::select_album(query, &candidate, 1).outcome == Outcome::Matched);
    }
    candidate.album = "Sunhead - Single";
    candidate.primary_type = nullptr;
    assert(artwork_matching::select_album({"Plini", "Sunhead - Single", ""}, &candidate, 1).outcome == Outcome::Matched);
    candidate.album = "Sunhead - EP";
    candidate.primary_type = "EP";
    // Only source-label removal is supported, not stripping candidate titles.
    assert(artwork_matching::select_album({"Plini", "Sunhead", ""}, &candidate, 1).outcome == Outcome::NoMatch);
}

static void typed_labels_preserve_other_identity_and_ambiguity_rules() {
    Candidate candidate = match("Artist", "Left - Right", "Song - EP");
    candidate.primary_type = "EP";
    assert(artwork_matching::select_album({"Artist", "Left - Right - EP", ""}, &candidate, 1).outcome == Outcome::Matched);
    assert(artwork_matching::select_album({"Artist", "Left Right - EP", ""}, &candidate, 1).outcome == Outcome::NoMatch);
    assert(artwork_matching::select_recording({"Artist", "", "Song"}, &candidate, 1).outcome == Outcome::NoMatch);
    candidate.album = "Album";
    const char *unchanged[] = {"Album - Live", "Album - Remix", "Album - Deluxe", "Album EP", "Album-Single", "Album (EP)"};
    for (const char *album : unchanged)
        assert(artwork_matching::select_album({"Artist", album, ""}, &candidate, 1).outcome == Outcome::NoMatch);
    candidate.primary_type = "EP";
    candidate.score = 94;
    assert(artwork_matching::select_album({"Artist", "Album - EP", ""}, &candidate, 1).outcome == Outcome::NoMatch);
    candidate.score = 100;
    candidate.artist_credit_count = 2;
    assert(artwork_matching::select_album({"Artist", "Album - EP", ""}, &candidate, 1).outcome == Outcome::NoMatch);
    candidate.artist_credit_count = 1;
    candidate.compilation = true;
    assert(artwork_matching::select_album({"Artist", "Album - EP", ""}, &candidate, 1).outcome == Outcome::NoMatch);
    candidate.compilation = false;
    assert(artwork_matching::select_album({"Artist!", "Album - EP", ""}, &candidate, 1).outcome == Outcome::NoMatch);
    Candidate ambiguous[] = {candidate, match("Artist", "Album", "Song", GROUP_B)};
    ambiguous[1].primary_type = "EP";
    assert(artwork_matching::select_album({"Artist", "Album - EP", ""}, ambiguous, 2).outcome == Outcome::Ambiguous);
    ambiguous[1].album = "Album - EP";
    ambiguous[1].primary_type = nullptr;
    assert(artwork_matching::select_album({"Artist", "Album - EP", ""}, ambiguous, 2).outcome == Outcome::Ambiguous);
}

static void typed_label_candidate_query_is_bounded_and_escaped() {
    std::string output;
    assert(artwork_matching::album_fallback_query({"Plini", "Sunhead - EP", ""}, output));
    assert(output == "releasegroup:(sunhead~1) AND artist:\"Plini\"");
    assert(artwork_matching::album_fallback_query({"Artist", "Dream's - Single", ""}, output));
    assert(output == "releasegroup:(dreams~1) AND artist:\"Artist\"");
    assert(artwork_matching::album_fallback_query({"Artist", "\xE6\x9D\xB1\xE4\xBA\xAC - EP", ""}, output));
    assert(output == "releasegroup:\"\xE6\x9D\xB1\xE4\xBA\xAC\" AND artist:\"Artist\"");
    assert(artwork_matching::album_fallback_query({"A \"Quoted\" \\ Artist", "\xE6\x9D\xB1\"\\\xE4\xBA\xAC - Single", ""}, output));
    assert(output == "releasegroup:\"\xE6\x9D\xB1\\\"\\\\\xE4\xBA\xAC\" AND artist:\"A \\\"Quoted\\\" \\\\ Artist\"");
    assert(artwork_matching::album_fallback_query({"Artist", "a b c d e f g h - EP", ""}, output));
    const char *invalid[] = {"a b c d e f g h i - EP", "AC/DC - EP", "Album (Deluxe) - Single",
                             "\xE6\x9D\xB1\xE4\xBA\xAC - Album", " - EP", " - Single"};
    for (const char *album : invalid) {
        output = "clear me";
        assert(!artwork_matching::album_fallback_query({"Artist", album, ""}, output));
        assert(output.empty());
    }
    const std::string long_artist(370, 'a');
    assert(!artwork_matching::album_fallback_query({long_artist.c_str(), "\xE6\x9D\xB1\xE4\xBA\xAC - EP", ""}, output));
    assert(output.empty());
}

static void encore_source_album_annotations() {
    Candidate candidate = match("Artist", "Album", "Song");
    candidate.primary_type = "Album";
    for (const char *album : {"Album (Encore Edition)", "Album [Encore Edition]",
                              "Album - Encore Edition", " ALBUM (ENCORE EDITION) ",
                              "Album \xE2\x80\x93 Encore Edition"}) {
        assert(artwork_matching::select_album({"Artist", album, ""}, &candidate, 1).outcome == Outcome::Matched);
        assert(artwork_matching::select_recording({"Artist", album, "Song"}, &candidate, 1).outcome == Outcome::Matched);
    }
    // Edition compatibility is album-only; stable cache and song keys do not change.
    assert(artwork_matching::normalized_key("Album (Encore Edition)", true) == "album (encore edition)");
    assert(artwork_matching::identity_key("Album (Encore Edition)", true) == "album (encore edition)");
    assert(artwork_matching::select_recording({"Artist", "", "Song (Encore Edition)"},
                                             &candidate, 1).outcome == Outcome::NoMatch);
}

static void encore_requires_exact_album_type_and_known_annotation() {
    Candidate candidate = match("Artist", "Album", "Song");
    const Query query = {"Artist", "Album (Encore Edition)", "Song"};
    const char *wrong_types[] = {nullptr, "", "EP", "Single", "album", "Album "};
    for (const char *type : wrong_types) {
        candidate.primary_type = type;
        assert(artwork_matching::select_album(query, &candidate, 1).outcome == Outcome::NoMatch);
    }
    candidate.primary_type = "Album";
    for (const char *album : {"Album (Encore)", "Album Encore Edition", "Album(Encore Edition)",
                              "Album (Encore Edition Live)", "Album (Encore Edition Remix)",
                              "Album (Live) (Encore Edition)", "Album (Remix) [Encore Edition]",
                              "Album (Live)", "Album (Remix)", "Album (Deluxe)", "Album (Acoustic)"})
        assert(artwork_matching::select_album({"Artist", album, ""}, &candidate, 1).outcome == Outcome::NoMatch);
    candidate.album = "Album (Encore Edition)";
    candidate.primary_type = "EP";
    assert(artwork_matching::select_album(query, &candidate, 1).outcome == Outcome::Matched);
    assert(artwork_matching::select_album({"Artist", "Album", ""}, &candidate, 1).outcome == Outcome::NoMatch);
}

static void encore_preserves_artist_score_credit_and_unique_group_guards() {
    const Query query = {"Artist", "Album (Encore Edition)", "Song"};
    Candidate candidate = match("Artist", "Album", "Song");
    candidate.primary_type = "Album";
    candidate.artist = "Artist (Encore Edition)";
    assert(artwork_matching::select_album(query, &candidate, 1).outcome == Outcome::NoMatch);
    candidate.artist = "Artist";
    candidate.score = 94;
    assert(artwork_matching::select_album(query, &candidate, 1).outcome == Outcome::NoMatch);
    candidate.score = 100;
    candidate.artist_credit_count = 2;
    assert(artwork_matching::select_album(query, &candidate, 1).outcome == Outcome::NoMatch);
    candidate.artist_credit_count = 1;
    candidate.compilation = true;
    assert(artwork_matching::select_album(query, &candidate, 1).outcome == Outcome::NoMatch);
    candidate.compilation = false;
    Candidate ambiguous[] = {candidate, candidate};
    ambiguous[1].art_id = GROUP_B;
    assert(artwork_matching::select_album(query, ambiguous, 2).outcome == Outcome::Ambiguous);
    ambiguous[1].art_id = GROUP_A;
    assert(artwork_matching::select_album(query, ambiguous, 2).outcome == Outcome::Matched);
}

static void encore_fallback_query_is_strict_escaped_and_bounded() {
    std::string output;
    assert(artwork_matching::album_fallback_query(
        {"Animals As Leaders", "Animals As Leaders (Encore Edition)", ""}, output));
    assert(output == "releasegroup:\"animals as leaders\" AND artist:\"Animals As Leaders\"");
    assert(artwork_matching::album_fallback_query(
        {"A \"Quoted\" \\ Artist", "AC/DC [Encore Edition]", ""}, output));
    assert(output == "releasegroup:\"ac/dc\" AND artist:\"A \\\"Quoted\\\" \\\\ Artist\"");
    assert(artwork_matching::album_fallback_query({"Artist", "\xE6\x9D\xB1\xE4\xBA\xAC - Encore Edition", ""}, output));
    assert(output == "releasegroup:\"\xE6\x9D\xB1\xE4\xBA\xAC\" AND artist:\"Artist\"");
    const std::string escaped(180, '\\');
    assert(!artwork_matching::album_fallback_query(
        {escaped.c_str(), "Album (Encore Edition)", ""}, output));
    assert(output.empty());
}

static void encore_actual_catalog_candidate(int argc, char *argv[]) {
    assert(argc == 7);
    const Candidate candidate = {argv[1], argv[2], "", argv[3],
        static_cast<unsigned>(std::strtoul(argv[4], nullptr, 10)),
        static_cast<unsigned>(std::strtoul(argv[5], nullptr, 10)), false, argv[6]};
    const auto result = artwork_matching::select_album(
        {"Animals As Leaders", "Animals As Leaders (Encore Edition)", ""}, &candidate, 1);
    assert(result.outcome == Outcome::Matched && result.index == 0);
}

int main(int argc, char *argv[]) {
    exact_album();
    normalized_identity();
    missing_album_recording_fallback();
    conservative_remasters();
    duplicate_editions_same_group();
    multiple_groups_ambiguous();
    generic_compilation_and_multiartist();
    no_fuzzy_substrings_or_score_guess();
    unicode_preservation();
    bounds_and_ids();
    album_and_title_apostrophe_equivalence_keeps_cache_keys_stable();
    apostrophe_equivalence_does_not_relax_artist_or_other_identity_rules();
    bounded_fallback_query_emission();
    unsafe_or_overlong_fallback_is_not_emitted();
    typed_source_album_labels();
    typed_labels_require_exact_primary_type_only_when_needed();
    typed_labels_preserve_other_identity_and_ambiguity_rules();
    typed_label_candidate_query_is_bounded_and_escaped();
    encore_source_album_annotations();
    encore_requires_exact_album_type_and_known_annotation();
    encore_preserves_artist_score_credit_and_unique_group_guards();
    encore_fallback_query_is_strict_escaped_and_bounded();
    encore_actual_catalog_candidate(argc, argv);
    std::cout << "23 matching scenarios passed\n";
}

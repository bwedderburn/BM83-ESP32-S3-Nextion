#include "artist_aliases.h"

#include <assert.h>
#include <stdlib.h>
#include <iostream>
#include <string>

using artist_aliases::Alias;
using artwork_matching::Candidate;
using artwork_matching::Outcome;

static const char OWNER[] = "1cbd7faf-938f-4c10-aeb1-426e83d38407";
static const char GROUP[] = "14add676-8dba-44e2-80fe-84b11d20b32a";
static const char OTHER_GROUP[] = "a1234567-1234-1234-1234-123456789abc";
static const char CANONICAL[] = "Jakub Żytecki";
static const char REQUESTED[] = "Jakub Zytecki";

static const char *choose(const Alias *aliases, size_t count, const char *owner = OWNER,
                          const char *requested = REQUESTED, const char *canonical = CANONICAL) {
    return artist_aliases::select(requested, canonical, canonical, owner, aliases, count);
}

static void direct_names_keep_precedence() {
    const Alias broken[] = {{nullptr, "Unknown type"}};
    assert(artist_aliases::select("Credit", "Credit", "Canonical", nullptr, broken, 99) ==
           artist_aliases::direct_match("Credit", "Credit", "Canonical"));
    const char *canonical = "Canonical";
    assert(!artist_aliases::select(" canonical ", "Credit", canonical, nullptr, nullptr, 0));
    assert(!artist_aliases::select(" canonical ", "Credit", canonical, "invalid", nullptr, 0));
    assert(artist_aliases::select(" canonical ", "Credit", canonical, OWNER, nullptr, 0) == canonical);
    assert(artist_aliases::select(" canonical ", nullptr, canonical, nullptr, nullptr, 0) == canonical);
    assert(!artist_aliases::direct_match(REQUESTED, CANONICAL, CANONICAL));
}

static void provider_alias_is_exact_and_owned() {
    const Alias aliases[] = {{REQUESTED, "Search hint"}};
    assert(choose(aliases, 1) == aliases[0].name);
    assert(choose(aliases, 1, OWNER, "JAKUB ZYTECKI") == aliases[0].name);
    const Alias unrelated[] = {{"Jakub Zytecki Tribute", "Artist name"}};
    assert(!choose(unrelated, 1));
    const Alias accents[] = {{CANONICAL, "Artist name"}};
    assert(!choose(accents, 1));  // No general Ż -> Z transliteration.
    assert(!choose(nullptr, 0));
    const char *ids[] = {nullptr, "", "invalid", "../../id", "00000000-0000-0000-0000-000000000000"};
    for (const char *id : ids) assert(!choose(aliases, 1, id));
}

static void alias_types_and_complete_list_validation() {
    const char *types[] = {nullptr, "Artist name", "Legal name", "Search hint"};
    for (const char *type : types) {
        const Alias aliases[] = {{REQUESTED, type}};
        assert(choose(aliases, 1));
    }
    const char *bad[] = {"", "artist name", "Artist name ", "Other", "Unknown type"};
    for (const char *type : bad) {
        const Alias aliases[] = {{REQUESTED, type}};
        assert(!choose(aliases, 1));
    }
    const Alias malformed_after_match[] = {{REQUESTED, "Search hint"}, {nullptr, "Artist name"}};
    assert(!choose(malformed_after_match, 2));
    const Alias bad_type_after_match[] = {{REQUESTED, "Search hint"}, {"Other", "Unknown"}};
    assert(!choose(bad_type_after_match, 2));
}

static void bounded_valid_utf8_only() {
    const std::string long_name(artwork_matching::MAX_INPUT_BYTES + 1, 'x');
    const char *bad[] = {nullptr, "", "   ", "Various Artists", "Unknown Artist", "Bad\nName",
                         "\xC0\xAF", "\xED\xA0\x80", "\xE2\x82", long_name.c_str()};
    for (const char *name : bad) {
        const Alias aliases[] = {{name, "Artist name"}};
        assert(!choose(aliases, 1));
    }
    const Alias good[] = {{REQUESTED, "Search hint"}};
    assert(!choose(good, 1, OWNER, "\xC0\xAF"));
    assert(!choose(good, 1, OWNER, REQUESTED, "\xC0\xAF"));
    assert(!choose(good, 1, OWNER, REQUESTED, "Various Artists"));
    Alias aliases[artist_aliases::MAX_ALIASES + 1];
    for (size_t i = 0; i < artist_aliases::MAX_ALIASES + 1; ++i) aliases[i] = {"Other", nullptr};
    aliases[artist_aliases::MAX_ALIASES - 1] = {REQUESTED, "Search hint"};
    assert(choose(aliases, artist_aliases::MAX_ALIASES));
    assert(!choose(aliases, artist_aliases::MAX_ALIASES + 1));
    assert(!choose(nullptr, 1));
}

static void matching_guards_still_apply() {
    const Alias alias[] = {{REQUESTED, "Search hint"}};
    const char *artist = choose(alias, 1);
    const artwork_matching::Query query = {REQUESTED, "Nothing Lasts, Nothing's Lost", "Grow Up"};
    const Candidate good = {artist, "Nothing Lasts, Nothing’s Lost", "Grow Up", GROUP, 100, 1, false, "Album"};
    assert(artwork_matching::select_album(query, &good, 1).outcome == Outcome::Matched);
    assert(artwork_matching::select_recording({REQUESTED, "", "Grow Up"}, &good, 1).outcome == Outcome::Matched);
    Candidate bad = good;
    bad.score = 94;
    assert(artwork_matching::select_album(query, &bad, 1).outcome == Outcome::NoMatch);
    bad = good; bad.artist_credit_count = 2;
    assert(artwork_matching::select_album(query, &bad, 1).outcome == Outcome::NoMatch);
    bad = good; bad.compilation = true;
    assert(artwork_matching::select_album(query, &bad, 1).outcome == Outcome::NoMatch);
    bad = good; bad.album = "Different Album";
    assert(artwork_matching::select_album(query, &bad, 1).outcome == Outcome::NoMatch);
    bad = good; bad.art_id = OWNER;  // A valid, different group cannot collapse ambiguity.
    const Candidate ambiguous[] = {good, bad};
    assert(artwork_matching::select_album(query, ambiguous, 2).outcome == Outcome::Ambiguous);
    bad = good; bad.art_id = "invalid";
    assert(artwork_matching::select_album(query, &bad, 1).outcome == Outcome::NoMatch);
    Candidate ep = {artist, "Release", "Song", OTHER_GROUP, 100, 1, false, "Album"};
    assert(artwork_matching::select_album({REQUESTED, "Release - EP", ""}, &ep, 1).outcome == Outcome::NoMatch);
    ep.primary_type = "EP";
    assert(artwork_matching::select_album({REQUESTED, "Release - EP", ""}, &ep, 1).outcome == Outcome::Matched);
    assert(artwork_matching::normalized_key(query.artist) == "jakub zytecki");
    assert(artwork_matching::normalized_key(query.album) == "nothing lasts, nothing's lost");
}

static void captured_provider_fixture(int argc, char **argv) {
    // Arguments are parsed directly from the stored, unmodified HTTP200 JSON
    // by the Python runner. Matching still uses the actual production helper.
    assert(argc == 11);
    const Alias aliases[] = {{argv[4], argv[5][0] ? argv[5] : nullptr}};
    const char *artist = artist_aliases::select(REQUESTED, argv[1], argv[2], argv[3], aliases, 1);
    assert(artist);
    const Candidate candidate = {artist, argv[6], nullptr, argv[7],
                                 static_cast<unsigned>(atoi(argv[8])),
                                 static_cast<unsigned>(atoi(argv[9])), false, argv[10]};
    assert(artwork_matching::select_album({REQUESTED, "Nothing Lasts, Nothing's Lost", ""},
                                          &candidate, 1).outcome == Outcome::Matched);
    const Candidate canonical = {argv[1], argv[6], nullptr, argv[7], 100, 1, false, argv[10]};
    assert(artwork_matching::select_album({REQUESTED, "Nothing Lasts, Nothing's Lost", ""},
                                          &canonical, 1).outcome == Outcome::NoMatch);
}

int main(int argc, char **argv) {
    direct_names_keep_precedence();
    provider_alias_is_exact_and_owned();
    alias_types_and_complete_list_validation();
    bounded_valid_utf8_only();
    matching_guards_still_apply();
    captured_provider_fixture(argc, argv);
    std::cout << "artist aliases: captured Jakub response and conservative guards passed\n";
}

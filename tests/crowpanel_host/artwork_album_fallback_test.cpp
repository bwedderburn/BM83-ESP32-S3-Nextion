#include "album_fallback.h"

#include <assert.h>
#include <iostream>
#include <string>

using album_fallback::Candidate;
using artwork_matching::Outcome;
using artwork_matching::Query;

static const char IMAGE[] =
    "https://cdn-images.dzcdn.net/images/cover/a5322381832a95d9e25ca30c0b28adc3/250x250-000000-80-0-0.jpg";
static const char BASELINE_IMAGE[] =
    "https://cdn-images.dzcdn.net/images/cover/a5322381832a95d9e25ca30c0b28adc3/120x120-000000-80-0-0.jpg";
static const Query POLARIZATION = {"Polarization", "Chasing the Light", "Damages"};

static Candidate match(const char *artist = "Polarization", const char *album = "Chasing the Light",
                       uint64_t id = 184925292, const char *type = "album", const char *image = IMAGE) {
    return {artist, album, id, type, image};
}

static void exact_identity() {
    const Candidate candidate = match();
    assert(album_fallback::select(POLARIZATION, &candidate, 1).outcome == Outcome::Matched);
    const Candidate baseline = match("Polarization", "Chasing the Light", 184925292, "album", BASELINE_IMAGE);
    assert(album_fallback::select(POLARIZATION, &baseline, 1).outcome == Outcome::Matched);
    assert(album_fallback::select({" POLARIZATION ", "CHASING\xC2\xA0THE LIGHT", ""},
                                 &candidate, 1).index == 0);
    const Candidate incorrect[] = {
        match("Another Artist"), match("Polarization & Another"),
        match("Polarization", "Chasing Light"), match("Polarization", "Chasing the Light (Deluxe)"),
        match("Polarization", "Chasing the Light (Live)")
    };
    for (const Candidate &item : incorrect)
        assert(album_fallback::select(POLARIZATION, &item, 1).outcome == Outcome::NoMatch);
    const Candidate remaster = match("Polarization", "Chasing the Light (2012 Remaster)");
    assert(album_fallback::select(POLARIZATION, &remaster, 1).outcome == Outcome::Matched);
    const Candidate apostrophe = match("Chimp Spanner", "At the Dream's Edge");
    assert(album_fallback::select({"Chimp Spanner", "At the Dreams Edge", ""},
                                 &apostrophe, 1).outcome == Outcome::Matched);
}

static void identifiers_and_ambiguity() {
    const Candidate duplicates[] = {match(), match()};
    assert(album_fallback::select(POLARIZATION, duplicates, 2).outcome == Outcome::Matched);
    const Candidate ambiguous[] = {match(), match("Polarization", "Chasing the Light", 2)};
    assert(album_fallback::select(POLARIZATION, ambiguous, 2).outcome == Outcome::Ambiguous);
    const Candidate zero = match("Polarization", "Chasing the Light", 0);
    assert(album_fallback::select(POLARIZATION, &zero, 1).outcome == Outcome::NoMatch);
    assert(album_fallback::select(POLARIZATION, nullptr, 1).outcome == Outcome::NoMatch);
    assert(album_fallback::select(POLARIZATION, duplicates, 0).outcome == Outcome::NoMatch);
    assert(album_fallback::select(POLARIZATION, duplicates,
                                 album_fallback::MAX_CANDIDATES + 1).outcome == Outcome::NoMatch);
    for (const char *artist : {"", "Various Artists", "Various", "Unknown Artist", "[unknown]"}) {
        const Candidate generic = match(artist);
        assert(album_fallback::select({artist, "Chasing the Light", ""},
                                     &generic, 1).outcome == Outcome::NoMatch);
    }
    const Candidate candidate = match();
    assert(album_fallback::select({"Polarization", "", "Damages"},
                                 &candidate, 1).outcome == Outcome::NoMatch);
    const std::string long_text(artwork_matching::MAX_INPUT_BYTES + 1, 'a');
    assert(album_fallback::select({long_text.c_str(), "Album", ""},
                                 &candidate, 1).outcome == Outcome::NoMatch);
}

static void source_store_labels() {
    Candidate ep = match("Plini", "Sunhead", 1, "ep");
    assert(album_fallback::select({"Plini", "Sunhead - EP", ""}, &ep, 1).outcome == Outcome::Matched);
    assert(album_fallback::select({"Plini", "Sunhead - Single", ""}, &ep, 1).outcome == Outcome::NoMatch);
    ep.record_type = "album";
    assert(album_fallback::select({"Plini", "Sunhead - EP", ""}, &ep, 1).outcome == Outcome::NoMatch);
    ep.record_type = nullptr;
    assert(album_fallback::select({"Plini", "Sunhead - EP", ""}, &ep, 1).outcome == Outcome::NoMatch);
    const Candidate single = match("Artist", "Song", 2, "single");
    assert(album_fallback::select({"Artist", "Song - Single", ""}, &single, 1).outcome == Outcome::Matched);
    const Candidate literal = match("Artist", "Left - Right - EP", 2);
    assert(album_fallback::select({"Artist", "Left - Right - EP", ""},
                                 &literal, 1).outcome == Outcome::Matched);
    assert(album_fallback::select({"Artist", "Left Right - EP", ""},
                                 &literal, 1).outcome == Outcome::NoMatch);
}

static void urls_are_exact() {
    assert(album_fallback::valid_image_url(IMAGE));
    assert(album_fallback::valid_image_url(BASELINE_IMAGE));
    assert(!album_fallback::valid_image_url(nullptr));
    assert(!album_fallback::valid_image_url(""));
    const std::string good = IMAGE;
    const char *bad[] = {
        "http://cdn-images.dzcdn.net/images/cover/0123456789abcdef0123456789abcdef/250x250-000000-80-0-0.jpg",
        "https://cdn-images.dzcdn.net.evil.test/images/cover/0123456789abcdef0123456789abcdef/250x250-000000-80-0-0.jpg",
        "https://cdn-images.dzcdn.net:443/images/cover/0123456789abcdef0123456789abcdef/250x250-000000-80-0-0.jpg",
        "https://user@cdn-images.dzcdn.net/images/cover/0123456789abcdef0123456789abcdef/250x250-000000-80-0-0.jpg",
        "https://cdn-images.dzcdn.net/images/cover/0123456789ABCDEF0123456789ABCDEF/250x250-000000-80-0-0.jpg",
        "https://cdn-images.dzcdn.net/images/cover/0123456789abcdef0123456789abcdeg/250x250-000000-80-0-0.jpg",
        "https://cdn-images.dzcdn.net/images/cover/0123456789abcdef0123456789abcde/250x250-000000-80-0-0.jpg",
        "https://cdn-images.dzcdn.net/images/cover/0123456789abcdef0123456789abcdef/500x500-000000-80-0-0.jpg"
    };
    for (const char *url : bad) {
        assert(!album_fallback::valid_image_url(url));
        const Candidate candidate = match("Polarization", "Chasing the Light", 1, "album", url);
        assert(album_fallback::select(POLARIZATION, &candidate, 1).outcome == Outcome::NoMatch);
    }
    for (const char *suffix : {"?x=1", "#fragment", "/", "\n", " ", "%00"})
        assert(!album_fallback::valid_image_url((good + suffix).c_str()));
}

static void api_image_urls_are_canonical_ids() {
    assert(album_fallback::valid_api_image_url("https://api.deezer.com/album/184925292/image"));
    assert(album_fallback::valid_api_image_url("https://api.deezer.com/album/1/image"));
    assert(album_fallback::valid_api_image_url("https://api.deezer.com/album/18446744073709551615/image"));
    assert(!album_fallback::valid_api_image_url(nullptr));
    for (const char *id : {"", "0", "00", "01", "-1", "+1", "1.0", "1e3", "abc",
                           "1/../../", "1%2f", "18446744073709551616", "99999999999999999999999"}) {
        const std::string url = std::string("https://api.deezer.com/album/") + id + "/image";
        assert(!album_fallback::valid_api_image_url(url.c_str()));
    }
    for (const char *url : {
            "http://api.deezer.com/album/1/image", "https://api.deezer.com.evil.test/album/1/image",
            "https://api.deezer.com:443/album/1/image", "https://user@api.deezer.com/album/1/image",
            "https://api.deezer.com/album/1/image?size=medium", "https://api.deezer.com/album/1/image#x",
            "https://api.deezer.com/album/1/image/", "https://api.deezer.com/album/1/image\n",
            "https://api.deezer.com/artist/1/image"})
        assert(!album_fallback::valid_api_image_url(url));
}

static void queries_escape_and_bound() {
    std::string query = "old";
    assert(album_fallback::search_query(POLARIZATION, query));
    assert(query == "artist:\"Polarization\" album:\"chasing the light\"");
    assert(album_fallback::search_query({"A \"Quoted\" \\ Artist", "A \"Quoted\" \\ Album", ""}, query));
    assert(query == "artist:\"A \\\"Quoted\\\" \\\\ Artist\" album:\"a \\\"quoted\\\" \\\\ album\"");
    assert(album_fallback::search_query({"Plini", "Sunhead - EP", ""}, query));
    assert(query == "artist:\"Plini\" album:\"sunhead\"");
    assert(album_fallback::search_query({"Artist", "Album (2012 Remastered)", ""}, query));
    assert(query == "artist:\"Artist\" album:\"album\"");
    for (const char *album : {"", "\nAlbum", "Album\t", "\xC0\xAF", "\xED\xA0\x80"}) {
        query = "old";
        assert(!album_fallback::search_query({"Artist", album, ""}, query));
        assert(query.empty());
    }
    for (const char *artist : {"", "Various Artists", "[unknown]", "Artist\x7F"}) {
        assert(!album_fallback::search_query({artist, "Album", ""}, query));
        assert(query.empty());
    }
    const std::string long_text(artwork_matching::MAX_INPUT_BYTES + 1, 'a');
    assert(!album_fallback::search_query({long_text.c_str(), "Album", ""}, query));
    assert(query.empty());
    const std::string fits(180, 'a');
    assert(album_fallback::search_query({fits.c_str(), fits.c_str(), ""}, query));
    const std::string escaped(100, '\\');
    assert(!album_fallback::search_query({escaped.c_str(), escaped.c_str(), ""}, query));
    assert(query.empty());
}

static void encore_album_type_and_identity() {
    const Query query = {"Animals As Leaders", "Animals As Leaders (Encore Edition)", ""};
    Candidate candidate = match("Animals As Leaders", "Animals As Leaders", 1, "album");
    assert(album_fallback::select(query, &candidate, 1).outcome == Outcome::Matched);
    const char *wrong_types[] = {nullptr, "", "ep", "single", "Album"};
    for (const char *type : wrong_types) {
        candidate.record_type = type;
        assert(album_fallback::select(query, &candidate, 1).outcome == Outcome::NoMatch);
    }
    candidate.record_type = "album";
    candidate.artist = "Another Artist";
    assert(album_fallback::select(query, &candidate, 1).outcome == Outcome::NoMatch);
    candidate.artist = "Animals As Leaders";
    candidate.album = "Animals As Leaders (Live)";
    assert(album_fallback::select(query, &candidate, 1).outcome == Outcome::NoMatch);
    std::string output;
    assert(album_fallback::search_query(query, output));
    assert(output == "artist:\"Animals As Leaders\" album:\"animals as leaders\"");
}

int main() {
    exact_identity();
    identifiers_and_ambiguity();
    source_store_labels();
    urls_are_exact();
    api_image_urls_are_canonical_ids();
    queries_escape_and_bound();
    encore_album_type_and_identity();
    std::cout << "album fallback checks passed\n";
}

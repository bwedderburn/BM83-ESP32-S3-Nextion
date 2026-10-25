// Conservative Deezer album lookup after a validated MusicBrainz album has
// no Cover Art Archive image. No network, JSON, storage or hardware dependency.
#pragma once

#include "matching.h"

namespace album_fallback {

static const size_t MAX_CANDIDATES = 8;
static const size_t MAX_QUERY_BYTES = 384;

struct Candidate {
    const char *artist;
    const char *album;
    uint64_t id;
    const char *record_type;
    const char *image_url;
};

// Accept only the bounded 250px or baseline-compatible 120px JPEG thumbnail
// forms. The caller must
// still validate every HTTP redirect and verify TLS issuer/hostname/dates.
inline bool valid_image_url(const char *url) {
    std::string value;
    if (!artwork_matching::detail::bounded_text(url, value)) return false;
    const char prefix[] = "https://cdn-images.dzcdn.net/images/cover/";
    const char suffix[] = "/250x250-000000-80-0-0.jpg";
    const char small_suffix[] = "/120x120-000000-80-0-0.jpg";
    const size_t start = sizeof(prefix) - 1;
    if (value.size() != start + 32 + sizeof(suffix) - 1 ||
        value.compare(0, start, prefix) != 0 ||
        (value.compare(start + 32, sizeof(suffix) - 1, suffix) != 0 &&
         value.compare(start + 32, sizeof(small_suffix) - 1, small_suffix) != 0)) return false;
    for (size_t i = start; i < start + 32; ++i)
        if (!((value[i] >= '0' && value[i] <= '9') ||
              (value[i] >= 'a' && value[i] <= 'f'))) return false;
    return true;
}

// The API's canonical image endpoint can redirect to a baseline JPEG. Only a
// canonical positive uint64 album ID is accepted; no credentials, ports,
// fragments, query strings, alternate paths or overflowing IDs are permitted.
inline bool valid_api_image_url(const char *url) {
    std::string value;
    if (!artwork_matching::detail::bounded_text(url, value)) return false;
    const char prefix[] = "https://api.deezer.com/album/";
    const char suffix[] = "/image";
    const size_t start = sizeof(prefix) - 1, tail = sizeof(suffix) - 1;
    if (value.size() <= start + tail || value.size() > start + 20 + tail ||
        value.compare(0, start, prefix) != 0 ||
        value.compare(value.size() - tail, tail, suffix) != 0 ||
        value[start] < '1' || value[start] > '9') return false;
    uint64_t id = 0;
    const uint64_t maximum = UINT64_MAX;
    for (size_t i = start; i < value.size() - tail; ++i) {
        if (value[i] < '0' || value[i] > '9') return false;
        const unsigned digit = static_cast<unsigned>(value[i] - '0');
        if (id > (maximum - digit) / 10) return false;
        id = id * 10 + digit;
    }
    return id != 0;
}

namespace detail {

inline const char *strip_source_label(std::string &album) {
    const char *type = artwork_matching::detail::strip_source_album_label(album);
    if (!type) return nullptr;
    return strcmp(type, "EP") == 0 ? "ep" : "single";
}

inline bool safe_query_text(const char *input, std::string &value) {
    if (!artwork_matching::detail::bounded_text(input, value)) return false;
    for (size_t i = 0; i < value.size();) {
        uint32_t code;
        if (!artwork_matching::detail::next_codepoint(value, i, code) ||
            code < 32 || (code >= 0x7F && code <= 0x9F)) return false;
    }
    return true;
}

}  // namespace detail

// Deezer's advanced search accepts quoted artist/album fields. Retrieval may
// omit a trailing source store label; selection still verifies full identity
// or the corresponding record_type. No fuzzy or substring matching is used.
inline bool search_query(const artwork_matching::Query &query, std::string &output) {
    output.clear();
    std::string original_artist, original_album;
    if (!detail::safe_query_text(query.artist, original_artist) ||
        !detail::safe_query_text(query.album, original_album)) return false;
    const std::string artist = artwork_matching::normalized_key(query.artist);
    std::string album = artwork_matching::normalized_key(query.album, true);
    if (artwork_matching::detail::generic_artist(artist) || album.empty()) return false;
    detail::strip_source_label(album);
    std::string result = "artist:";
    artwork_matching::detail::append_quoted(result, original_artist);
    result += " album:";
    artwork_matching::detail::append_quoted(result, album);
    if (result.size() > MAX_QUERY_BYTES) return false;
    output.swap(result);
    return true;
}

inline artwork_matching::Selection select(const artwork_matching::Query &query,
                                          const Candidate *candidates, size_t count) {
    using artwork_matching::Outcome;
    const artwork_matching::Selection none = {Outcome::NoMatch, -1};
    if (!candidates || !count || count > MAX_CANDIDATES) return none;
    const std::string artist = artwork_matching::normalized_key(query.artist);
    const std::string album = artwork_matching::identity_key(query.album, true);
    if (artwork_matching::detail::generic_artist(artist) || album.empty()) return none;
    std::string base_album = album;
    const char *type = detail::strip_source_label(base_album);
    int selected = -1;
    for (size_t i = 0; i < count; ++i) {
        const Candidate &candidate = candidates[i];
        if (!candidate.id || !valid_image_url(candidate.image_url) ||
            artwork_matching::normalized_key(candidate.artist) != artist) continue;
        const std::string candidate_album = artwork_matching::identity_key(candidate.album, true);
        if (candidate_album != album &&
            (!type || candidate_album != base_album || !candidate.record_type ||
             strcmp(type, candidate.record_type) != 0)) continue;
        if (selected < 0) selected = static_cast<int>(i);
        else if (candidates[selected].id != candidate.id) return {Outcome::Ambiguous, -1};
    }
    return selected < 0 ? none : artwork_matching::Selection{Outcome::Matched, selected};
}

}  // namespace album_fallback

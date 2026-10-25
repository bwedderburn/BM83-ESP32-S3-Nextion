// Exact MusicBrainz artist-credit/alias policy. No JSON, network or hardware.
// Aliases must come from the same single-credit artist object as owner_id;
// callers validate JSON container/string types before passing these views.
#pragma once

#include "matching.h"

namespace artist_aliases {

static const size_t MAX_ALIASES = 16;

struct Alias {
    const char *name;
    const char *type;  // nullptr = an untyped MusicBrainz alias.
};

namespace detail {

inline bool artist_key(const char *name, std::string &key) {
    std::string input;
    if (!name || !artwork_matching::detail::bounded_text(name, input)) return false;
    for (size_t offset = 0; offset < input.size();) {
        uint32_t code;
        if (!artwork_matching::detail::next_codepoint(input, offset, code) ||
            code < 32 || (code >= 0x7F && code <= 0x9F)) return false;
    }
    key = artwork_matching::normalized_key(name);
    return !artwork_matching::detail::generic_artist(key);
}

inline bool valid_type(const char *type) {
    if (!type) return true;
    std::string value;
    if (!artwork_matching::detail::bounded_text(type, value)) return false;
    return value == "Artist name" || value == "Legal name" || value == "Search hint";
}

}  // namespace detail

// Preserve legacy credit-name precedence: fall back to canonical only when
// the credited name is absent. Exact old responses need no optional aliases
// or artist MBID. A different canonical name is an owned alternative below.
inline const char *direct_match(const char *requested, const char *credited, const char *canonical) {
    std::string target, name;
    if (!detail::artist_key(requested, target)) return nullptr;
    if (credited) return detail::artist_key(credited, name) && name == target ? credited : nullptr;
    if (detail::artist_key(canonical, name) && name == target) return canonical;
    return nullptr;
}

// Return a provider-owned name with the requested exact normalized identity.
// This does not alter metadata/cache keys, transliterate accents, relax album
// matching or bypass score, credit-count, compilation and group uniqueness.
inline const char *select(const char *requested, const char *credited, const char *canonical,
                          const char *owner_id, const Alias *aliases, size_t count) {
    if (const char *direct = direct_match(requested, credited, canonical)) return direct;
    std::string target, canonical_key, credited_key;
    if (!detail::artist_key(requested, target) || !detail::artist_key(canonical, canonical_key) ||
        (credited && !detail::artist_key(credited, credited_key)) ||
        !artwork_matching::valid_mbid(owner_id)) return nullptr;
    if (canonical_key == target) return canonical;
    if (!aliases || !count || count > MAX_ALIASES) return nullptr;
    const char *matched = nullptr;
    for (size_t i = 0; i < count; ++i) {
        std::string name;
        // Validate the entire list even after finding a match. A malformed
        // sibling entry must not turn a partial/invalid alias set into proof.
        if (!detail::artist_key(aliases[i].name, name) || !detail::valid_type(aliases[i].type)) return nullptr;
        if (!matched && name == target) matched = aliases[i].name;
    }
    return matched;
}

}  // namespace artist_aliases

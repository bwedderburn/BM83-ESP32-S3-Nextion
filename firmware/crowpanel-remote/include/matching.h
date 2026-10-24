// Conservative, bounded MusicBrainz -> Cover Art Archive match.
// No JSON, HTTP, Arduino, LVGL, filesystem or hardware dependencies.
//
// MusicBrainz search score is only a filter, not proof of identity. Callers
// must populate complete credited artist names, artist-credit counts and
// Compilation secondary-type flags from the JSON response. art_id is a
// RELEASE-GROUP MBID, never a specific pressing/edition's release MBID.
// Primary schemas: https://musicbrainz.org/doc/MusicBrainz_API/Search
//                 https://musicbrainz.org/doc/Cover_Art_Archive/API
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <string>

namespace artwork_matching {

static const size_t MAX_INPUT_BYTES = 384;
static const size_t MAX_CANDIDATES = 32;
static const unsigned MIN_SCORE = 95;
static const size_t MAX_FALLBACK_TOKENS = 8;
static const size_t MAX_FALLBACK_QUERY_BYTES = 384;

struct Query {
    const char *artist;
    const char *album;
    const char *title;
};

struct Candidate {
    const char *artist;
    const char *album;
    const char *title;
    const char *art_id;  // MusicBrainz release-group MBID.
    unsigned score;     // MusicBrainz search score, 0..100.
    unsigned artist_credit_count;
    bool compilation;
};

enum class Outcome { NoMatch, Matched, Ambiguous };

struct Selection {
    Outcome outcome;
    int index;  // Valid only when outcome == Matched; otherwise -1.
};

namespace detail {

inline bool bounded_text(const char *text, std::string &out) {
    out.clear();
    if (!text) return true;
    size_t size = 0;
    while (size <= MAX_INPUT_BYTES && text[size]) ++size;
    if (size > MAX_INPUT_BYTES) return false;  // Never compare truncated names.
    out.assign(text, size);
    return true;
}

inline bool next_codepoint(const std::string &text, size_t &offset, uint32_t &code) {
    const uint8_t lead = static_cast<uint8_t>(text[offset++]);
    if (lead < 0x80) { code = lead; return true; }
    unsigned tail;
    uint32_t minimum;
    if (lead >= 0xC2 && lead <= 0xDF) { code = lead & 0x1F; tail = 1; minimum = 0x80; }
    else if (lead >= 0xE0 && lead <= 0xEF) { code = lead & 0x0F; tail = 2; minimum = 0x800; }
    else if (lead >= 0xF0 && lead <= 0xF4) { code = lead & 7; tail = 3; minimum = 0x10000; }
    else return false;
    if (offset + tail > text.size()) return false;
    while (tail--) {
        const uint8_t byte = static_cast<uint8_t>(text[offset++]);
        if ((byte & 0xC0) != 0x80) return false;
        code = (code << 6) | (byte & 0x3F);
    }
    return code >= minimum && code <= 0x10FFFF && !(code >= 0xD800 && code <= 0xDFFF);
}

inline bool whitespace(uint32_t code) {
    return code <= 32 || (code >= 0x7F && code <= 0x9F) || code == 0xA0 || code == 0x1680 ||
           (code >= 0x2000 && code <= 0x200A) || code == 0x2028 || code == 0x2029 ||
           code == 0x202F || code == 0x205F || code == 0x3000;
}

inline bool normalize(const char *text, std::string &out) {
    std::string input;
    out.clear();
    if (!bounded_text(text, input)) return false;
    bool space = false;
    for (size_t offset = 0; offset < input.size();) {
        const size_t start = offset;
        uint32_t code;
        if (!next_codepoint(input, offset, code)) { out.clear(); return false; }
        if (whitespace(code)) { space = !out.empty(); continue; }
        if (code == 0x200B || code == 0x2060 || code == 0xFEFF) continue;
        if (space) { out += ' '; space = false; }
        if (code >= 'A' && code <= 'Z') out += static_cast<char>(code + ('a' - 'A'));
        else if (code == 0x2018 || code == 0x2019) out += '\'';
        else if (code == 0x201C || code == 0x201D) out += '"';
        else if ((code >= 0x2010 && code <= 0x2014) || code == 0x2212) out += '-';
        else if (code == 0x2026) out += "...";
        else out.append(input, start, offset - start);
    }
    return true;
}

inline bool year(const std::string &value) {
    return value.size() == 4 && (value.compare(0, 2, "19") == 0 || value.compare(0, 2, "20") == 0) &&
           value[2] >= '0' && value[2] <= '9' && value[3] >= '0' && value[3] <= '9';
}

inline bool remaster_word(const std::string &value) {
    return value == "remaster" || value == "remastered";
}

inline bool remaster_annotation(const std::string &value) {
    if (remaster_word(value)) return true;
    const size_t gap = value.find(' ');
    if (gap == std::string::npos || value.find(' ', gap + 1) != std::string::npos) return false;
    const std::string a = value.substr(0, gap), b = value.substr(gap + 1);
    return (year(a) && remaster_word(b)) || (remaster_word(a) && year(b));
}

inline void strip_remaster(std::string &value) {
    if (value.empty()) return;
    size_t start = std::string::npos;
    size_t annotation = 0, annotation_size = 0;
    if (value.back() == ')' || value.back() == ']') {
        const char opening = value.back() == ')' ? '(' : '[';
        const size_t bracket = value.rfind(opening);
        if (bracket > 0 && bracket != std::string::npos && value[bracket - 1] == ' ') {
            start = bracket - 1;
            annotation = bracket + 1;
            annotation_size = value.size() - annotation - 1;
        }
    } else {
        const size_t dash = value.rfind(" - ");
        if (dash != std::string::npos) {
            start = dash;
            annotation = dash + 3;
            annotation_size = value.size() - annotation;
        }
    }
    if (start != std::string::npos && start > 0 &&
        remaster_annotation(value.substr(annotation, annotation_size))) value.resize(start);
}

inline bool normalized(const char *text, bool strip, std::string &out) {
    if (!normalize(text, out)) return false;
    if (strip) strip_remaster(out);
    return true;
}

inline bool ascii_word(char value) {
    return (value >= 'a' && value <= 'z') || (value >= 'A' && value <= 'Z') ||
           (value >= '0' && value <= '9');
}

inline bool identity_normalized(const char *text, bool strip, std::string &out) {
    if (!normalized(text, strip, out)) return false;
    std::string identity;
    identity.reserve(out.size());
    for (size_t i = 0; i < out.size(); ++i) {
        // Only omit an apostrophe inside an ASCII alphanumeric word. Leading,
        // trailing and repeated quote marks remain part of the identity.
        if (out[i] == '\'' && i > 0 && i + 1 < out.size() &&
            ascii_word(out[i - 1]) && ascii_word(out[i + 1])) continue;
        identity += out[i];
    }
    out.swap(identity);
    return true;
}

inline bool generic_artist(const std::string &artist) {
    return artist.empty() || artist == "various artists" || artist == "various" ||
           artist == "unknown artist" || artist == "[unknown]";
}

inline char lower_hex(char value) {
    return value >= 'A' && value <= 'F' ? static_cast<char>(value + ('a' - 'A')) : value;
}

inline bool same_id(const char *a, const char *b) {
    for (size_t i = 0; i < 36; ++i) if (lower_hex(a[i]) != lower_hex(b[i])) return false;
    return true;
}

}  // namespace detail

// ASCII case/whitespace and typographic punctuation are normalized. Other UTF-8
// letters are preserved byte-for-byte: no accent removal, transliteration,
// fuzzy substring matching or unsupported claim of complete Unicode casefold.
// Only a strict trailing remaster/remastered + optional 1900..2099 year may
// be removed. Live/remix/acoustic/deluxe qualifiers remain part of identity.
inline std::string normalized_key(const char *text, bool strip_remaster_suffix = false) {
    std::string out;
    detail::normalized(text, strip_remaster_suffix, out);
    return out;
}

// Comparison equivalence is deliberately separate from the stable cache key.
// In-word Dream's/Dreams differences compare equally; all other existing
// normalized characters and Unicode letters remain significant.
inline std::string identity_key(const char *text, bool strip_remaster_suffix = false) {
    std::string out;
    detail::identity_normalized(text, strip_remaster_suffix, out);
    return out;
}

// Candidate retrieval only: at most one worker fallback may use this query,
// after a complete successful strict search returned zero results. Candidates
// must still pass select_album's full identity/score/unique-group checks.
// Output is Lucene text, not URL encoded. False always leaves output empty.
inline bool album_fallback_query(const Query &query, std::string &output) {
    output.clear();
    std::string artist, original_artist, album;
    if (!detail::normalized(query.artist, false, artist) || detail::generic_artist(artist) ||
        !detail::bounded_text(query.artist, original_artist) ||
        !detail::normalized(query.album, true, album) || album.empty()) return false;
    for (size_t i = 0; i < original_artist.size();) {
        uint32_t code;
        if (!detail::next_codepoint(original_artist, i, code) || code < 32 || (code >= 0x7F && code <= 0x9F))
            return false;
    }

    std::string words[MAX_FALLBACK_TOKENS];
    size_t count = 0;
    bool in_word = false;
    for (size_t i = 0; i < album.size(); ++i) {
        const char value = album[i];
        if (value == ' ') { in_word = false; continue; }
        if (value == '\'') {
            if (i == 0 || i + 1 >= album.size() || !detail::ascii_word(album[i - 1]) ||
                !detail::ascii_word(album[i + 1])) return false;
            continue;
        }
        if (!detail::ascii_word(value)) return false;
        if (!in_word) {
            if (count == MAX_FALLBACK_TOKENS) return false;
            ++count;
            in_word = true;
        }
        words[count - 1] += value;
    }
    if (!count) return false;
    std::string result = "releasegroup:(";
    for (size_t i = 0; i < count; ++i) {
        if (i) result += " AND ";
        result += words[i];
        if (words[i].size() >= 4) result += "~1";
    }
    result += ") AND artist:\"";
    for (size_t i = 0; i < original_artist.size(); ++i) {
        const char value = original_artist[i];
        if (value == '"' || value == '\\') result += '\\';
        result += value;
    }
    result += '"';
    if (result.size() > MAX_FALLBACK_QUERY_BYTES) return false;
    output.swap(result);
    return true;
}

inline bool valid_mbid(const char *id) {
    if (!id) return false;
    bool nonzero = false;
    for (size_t i = 0; i < 36; ++i) {
        const char c = id[i];
        if (!c) return false;
        if (i == 8 || i == 13 || i == 18 || i == 23) {
            if (c != '-') return false;
        } else {
            const char lower = detail::lower_hex(c);
            if (!((lower >= '0' && lower <= '9') || (lower >= 'a' && lower <= 'f'))) return false;
            if (lower != '0') nonzero = true;
        }
    }
    return id[36] == '\0' && nonzero;
}

namespace detail {

inline Selection select(const Query &query, const Candidate *candidates, size_t count, bool recording) {
    const Selection none = {Outcome::NoMatch, -1};
    if (!candidates || count == 0 || count > MAX_CANDIDATES) return none;
    std::string artist, album, title;
    if (!normalized(query.artist, false, artist) || generic_artist(artist) ||
        !identity_normalized(query.album, true, album)) return none;
    if (recording) {
        if (!identity_normalized(query.title, true, title) || title.empty()) return none;
    } else if (album.empty()) return none;

    int selected = -1;
    for (size_t i = 0; i < count; ++i) {
        const Candidate &candidate = candidates[i];
        if (candidate.compilation || candidate.artist_credit_count != 1 ||
            candidate.score < MIN_SCORE || candidate.score > 100 || !valid_mbid(candidate.art_id)) continue;
        std::string credited_artist;
        if (!normalized(candidate.artist, false, credited_artist) || generic_artist(credited_artist) ||
            credited_artist != artist) continue;
        if (!album.empty()) {
            std::string candidate_album;
            if (!identity_normalized(candidate.album, true, candidate_album) || candidate_album != album) continue;
        }
        if (recording) {
            std::string candidate_title;
            if (!identity_normalized(candidate.title, true, candidate_title) || candidate_title != title) continue;
        }
        if (selected < 0) selected = static_cast<int>(i);
        else if (!same_id(candidates[selected].art_id, candidate.art_id)) return {Outcome::Ambiguous, -1};
        else if (candidate.score > candidates[selected].score) selected = static_cast<int>(i);
    }
    return selected < 0 ? none : Selection{Outcome::Matched, selected};
}

}  // namespace detail

inline Selection select_album(const Query &query, const Candidate *candidates, size_t count) {
    return detail::select(query, candidates, count, false);
}

// Windows often supplies artist/title with no album. That is sufficient only
// when all accepted recording matches resolve to the same release group.
// When the query does include an album, it must match too.
inline Selection select_recording(const Query &query, const Candidate *candidates, size_t count) {
    return detail::select(query, candidates, count, true);
}

}  // namespace artwork_matching

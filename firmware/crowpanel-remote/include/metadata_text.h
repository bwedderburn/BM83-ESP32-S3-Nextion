// Small display-only composition; raw metadata and artwork identity stay intact.
#pragma once

#include <stddef.h>
#include <stdint.h>

namespace metadata_text {
namespace detail {

inline bool decode(const char *source, uint32_t &code, size_t &width) {
    const uint8_t first = static_cast<uint8_t>(source[0]);
    uint32_t minimum;
    if (first < 0x80) {
        code = first;
        width = 1;
        return true;
    } else if (first >= 0xC2 && first <= 0xDF) {
        code = first & 0x1F;
        width = 2;
        minimum = 0x80;
    } else if (first >= 0xE0 && first <= 0xEF) {
        code = first & 0x0F;
        width = 3;
        minimum = 0x800;
    } else if (first >= 0xF0 && first <= 0xF4) {
        code = first & 0x07;
        width = 4;
        minimum = 0x10000;
    } else {
        return false;
    }
    for (size_t i = 1; i < width; ++i) {
        const uint8_t next = static_cast<uint8_t>(source[i]);
        if ((next & 0xC0) != 0x80) return false;  // Also stops at a truncated NUL.
        code = (code << 6) | (next & 0x3F);
    }
    return code >= minimum && code <= 0x10FFFF && !(code >= 0xD800 && code <= 0xDFFF);
}

}  // namespace detail

// Compose exactly Latin/Cyrillic O or o followed by U+0308. This is neither
// general NFC nor transliteration. Input must be NUL terminated; invalid UTF-8
// or insufficient output space returns false with a valid, terminated prefix.
// No partial UTF-8 character is emitted. A zero-capacity/null destination fails.
inline bool compose_diaeresis(const char *source, char *destination, size_t capacity) {
    if (!destination || capacity == 0) return false;
    if (!source) {
        destination[0] = '\0';
        return false;
    }
    size_t used = 0;
    while (*source) {
        uint32_t code;
        size_t width;
        if (!detail::decode(source, code, width)) {
            destination[used] = '\0';
            return false;
        }
        char bytes[4];
        size_t count = width;
        for (size_t i = 0; i < width; ++i) bytes[i] = source[i];
        const char *next = source + width;
        uint32_t composed = 0;
        if (code == 'O') composed = 0x00D6;
        else if (code == 'o') composed = 0x00F6;
        else if (code == 0x041E) composed = 0x04E6;
        else if (code == 0x043E) composed = 0x04E7;
        if (composed && static_cast<uint8_t>(next[0]) == 0xCC &&
            static_cast<uint8_t>(next[1]) == 0x88) {
            bytes[0] = static_cast<char>(0xC0 | (composed >> 6));
            bytes[1] = static_cast<char>(0x80 | (composed & 0x3F));
            count = 2;
            width += 2;
        }
        if (count >= capacity - used) {
            destination[used] = '\0';
            return false;
        }
        for (size_t i = 0; i < count; ++i) destination[used++] = bytes[i];
        source += width;
    }
    destination[used] = '\0';
    return true;
}

}  // namespace metadata_text

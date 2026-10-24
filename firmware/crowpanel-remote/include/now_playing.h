// Pure C++11 bounded BMS2 decoder and playback-clock model; no hardware APIs.
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace now_playing {

static const uint32_t UNKNOWN = 0xFFFFFFFFU;
static const size_t MAX_TEXT_BYTES = 96;
static const size_t FRAME_MAX = 64;
static const size_t HEADER_SIZE = 16;
static const size_t FRAGMENT_SIZE = 48;
static const size_t PAYLOAD_FIXED = 18;
static const size_t MAX_PAYLOAD = PAYLOAD_FIXED + 3 * MAX_TEXT_BYTES;
static const uint32_t FRESH_MS = 6000;
static const uint32_t EXTRAPOLATE_MS = 5000;

struct NowPlayingState {
    bool power_on, connected, aux;
    uint8_t play_status, eq_index;
    uint32_t duration_ms, position_ms, position_age_ms;
    char title[MAX_TEXT_BYTES + 1], artist[MAX_TEXT_BYTES + 1], album[MAX_TEXT_BYTES + 1];
};

inline uint16_t read16(const uint8_t *p) {
    return static_cast<uint16_t>((static_cast<uint16_t>(p[0]) << 8) | p[1]);
}

inline uint32_t read32(const uint8_t *p) {
    return (static_cast<uint32_t>(p[0]) << 24) | (static_cast<uint32_t>(p[1]) << 16) |
           (static_cast<uint32_t>(p[2]) << 8) | p[3];
}

inline uint16_t crc16(const uint8_t *data, size_t len) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; ++i) {
        crc ^= static_cast<uint16_t>(data[i]) << 8;
        for (unsigned bit = 0; bit < 8; ++bit) {
            crc = static_cast<uint16_t>((crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1);
        }
    }
    return crc;
}

inline bool valid_utf8(const uint8_t *data, size_t len) {
    size_t i = 0;
    while (i < len) {
        const uint8_t lead = data[i++];
        if (lead < 0x80) {
            if (lead < 32 || lead == 127) return false;
            continue;
        }
        unsigned remaining;
        uint32_t code;
        uint32_t minimum;
        if (lead >= 0xC2 && lead <= 0xDF) { remaining = 1; code = lead & 0x1F; minimum = 0x80; }
        else if (lead >= 0xE0 && lead <= 0xEF) { remaining = 2; code = lead & 0x0F; minimum = 0x800; }
        else if (lead >= 0xF0 && lead <= 0xF4) { remaining = 3; code = lead & 7; minimum = 0x10000; }
        else return false;
        if (i + remaining > len) return false;
        for (unsigned j = 0; j < remaining; ++j) {
            if ((data[i] & 0xC0) != 0x80) return false;
            code = (code << 6) | (data[i++] & 0x3F);
        }
        if (code < minimum || code > 0x10FFFF || (code >= 0xD800 && code <= 0xDFFF)) return false;
    }
    return true;
}

class NowPlayingModel {
public:
    NowPlayingState state;

    NowPlayingModel() { reset(); }

    void reset() {
        memset(&state, 0, sizeof(state));
        state.play_status = state.eq_index = 0xFF;
        state.duration_ms = state.position_ms = state.position_age_ms = UNKNOWN;
        have_ = assembling_ = retired_valid_ = expired_ = false;
        session_ = assembly_session_ = retired_session_ = committed_at_ = sample_at_ = 0;
        seq_ = assembly_seq_ = assembly_crc_ = assembly_size_ = 0;
        assembly_count_ = mask_ = 0;
        assembly_at_ = 0;
    }

    bool have_snapshot() const { return have_; }

    bool fresh(uint32_t now_ms) const {
        if (!have_ || expired_) return false;
        if (static_cast<uint32_t>(now_ms - committed_at_) >= FRESH_MS) expired_ = true;
        return !expired_;
    }

    uint32_t position(uint32_t now_ms) const {
        if (!fresh(now_ms) || !state.power_on || !state.connected || state.aux ||
            state.position_ms == UNKNOWN || state.position_age_ms == UNKNOWN ||
            state.position_age_ms > EXTRAPOLATE_MS) return UNKNOWN;
        uint64_t result = state.position_ms;
        // Fast-forward/reverse have no known rate: show source snapshots only.
        if (state.play_status == 1) {
            const uint64_t age = static_cast<uint64_t>(state.position_age_ms) +
                                 static_cast<uint32_t>(now_ms - sample_at_);
            if (age > EXTRAPOLATE_MS) return UNKNOWN;
            result += age;
        }
        if (state.duration_ms != UNKNOWN && result > state.duration_ms) result = state.duration_ms;
        return result >= UNKNOWN ? UNKNOWN - 1 : static_cast<uint32_t>(result);
    }

    bool accept(const uint8_t *frame, size_t len, uint32_t now_ms) {
        if (!frame || len <= HEADER_SIZE || len > FRAME_MAX || memcmp(frame, "BMS2", 4) != 0) return false;
        const uint32_t session = read32(frame + 4);
        const uint16_t seq = read16(frame + 8);
        const uint8_t index = frame[10], count = frame[11];
        const uint16_t size = read16(frame + 12), crc = read16(frame + 14);
        if (size < PAYLOAD_FIXED || size > MAX_PAYLOAD || count == 0 || count > 7 || index >= count ||
            count != (size + FRAGMENT_SIZE - 1) / FRAGMENT_SIZE) return false;
        const size_t offset = static_cast<size_t>(index) * FRAGMENT_SIZE;
        const size_t remaining = size - offset;
        const size_t piece = remaining < FRAGMENT_SIZE ? remaining : FRAGMENT_SIZE;
        if (len != HEADER_SIZE + piece) return false;
        if (retired_valid_ && session == retired_session_) return false;
        if (have_ && session == session_ && !newer(seq, seq_)) return false;

        if (assembling_ && static_cast<uint32_t>(now_ms - assembly_at_) >= FRESH_MS) assembling_ = false;
        if (!assembling_ || session != assembly_session_ || seq != assembly_seq_) {
            if (assembling_ && session == assembly_session_ && !newer(seq, assembly_seq_)) return false;
            // A different boot starts only at fragment zero, preventing an old
            // trailing fragment from displacing a live session's assembly.
            if ((have_ && session != session_) || (assembling_ && session != assembly_session_)) {
                if (index != 0) return false;
            }
            assembling_ = true;
            assembly_session_ = session;
            assembly_seq_ = seq;
            assembly_size_ = size;
            assembly_crc_ = crc;
            assembly_count_ = count;
            assembly_at_ = now_ms;
            mask_ = 0;
        }
        if (size != assembly_size_ || crc != assembly_crc_ || count != assembly_count_) return false;
        const uint8_t bit = static_cast<uint8_t>(1U << index);
        if (mask_ & bit) return false;
        memcpy(payload_ + offset, frame + HEADER_SIZE, piece);
        mask_ |= bit;
        if (mask_ != static_cast<uint8_t>((1U << count) - 1U)) return false;
        assembling_ = false;
        if (crc16(payload_, size) != crc) return false;
        NowPlayingState incoming = {};
        if (!decode(incoming, size)) return false;
        if (have_ && session != session_) { retired_session_ = session_; retired_valid_ = true; }
        state = incoming;
        session_ = session;
        seq_ = seq;
        have_ = true;
        expired_ = false;
        committed_at_ = now_ms;
        sample_at_ = assembly_at_;
        return true;
    }

private:
    bool have_, assembling_, retired_valid_;
    mutable bool expired_;
    uint32_t session_, assembly_session_, retired_session_, committed_at_, sample_at_, assembly_at_;
    uint16_t seq_, assembly_seq_, assembly_crc_, assembly_size_;
    uint8_t assembly_count_, mask_;
    uint8_t payload_[MAX_PAYLOAD];

    static bool newer(uint16_t candidate, uint16_t previous) {
        const uint16_t distance = static_cast<uint16_t>(candidate - previous);
        return distance != 0 && distance < 0x8000;
    }

    bool decode(NowPlayingState &out, size_t len) const {
        if (payload_[0] & ~7U) return false;
        const uint8_t status = payload_[1];
        if (status > 4 && status != 0xFF) return false;
        const size_t title_len = payload_[15], artist_len = payload_[16], album_len = payload_[17];
        if (title_len > MAX_TEXT_BYTES || artist_len > MAX_TEXT_BYTES || album_len > MAX_TEXT_BYTES ||
            PAYLOAD_FIXED + title_len + artist_len + album_len != len) return false;
        size_t offset = PAYLOAD_FIXED;
        const size_t sizes[] = {title_len, artist_len, album_len};
        char *strings[] = {out.title, out.artist, out.album};
        for (unsigned i = 0; i < 3; ++i) {
            if (!valid_utf8(payload_ + offset, sizes[i])) return false;
            memcpy(strings[i], payload_ + offset, sizes[i]);
            strings[i][sizes[i]] = '\0';
            offset += sizes[i];
        }
        out.power_on = (payload_[0] & 1) != 0;
        out.connected = (payload_[0] & 2) != 0;
        out.aux = (payload_[0] & 4) != 0;
        out.play_status = status;
        out.eq_index = payload_[2];
        out.duration_ms = read32(payload_ + 3);
        out.position_ms = read32(payload_ + 7);
        out.position_age_ms = read32(payload_ + 11);
        return true;
    }
};

}  // namespace now_playing

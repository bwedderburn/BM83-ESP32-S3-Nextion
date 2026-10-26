// Pure C++11 BLS1 status decoder; independent of playback snapshot freshness.
#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace ble_status {

static const size_t FRAME_SIZE = 19;
static const uint32_t FRESH_MS = 3000;

enum Mode {
    MODE_ENABLED = 0,
    MODE_PAUSING = 1,
    MODE_PAUSED = 2,
    MODE_ERROR = 3
};

enum Flag {
    FLAG_INTENT = 1,
    FLAG_READY = 2,
    FLAG_CONNECTED = 4,
    FLAG_ADVERTISING = 8
};

struct Status {
    uint32_t session, request_seq;
    uint16_t sequence;
    uint8_t mode, flags, error;
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

class Decoder {
public:
    Status state;

    Decoder() { reset(); }

    void reset() {
        memset(&state, 0, sizeof(state));
        memset(retired_, 0, sizeof(retired_));
        have_ = expired_ = false;
        received_at_ = 0;
        retired_count_ = retired_next_ = 0;
    }

    bool have_status() const { return have_; }

    bool fresh(uint32_t now_ms) const {
        if (!have_ || expired_) return false;
        if (static_cast<uint32_t>(now_ms - received_at_) >= FRESH_MS) expired_ = true;
        return !expired_;
    }

    bool confirmed_paused(uint32_t now_ms) const {
        return fresh(now_ms) && state.mode == MODE_PAUSED;
    }

    bool accept(const uint8_t *frame, size_t len, uint32_t now_ms) {
        if (!frame || len != FRAME_SIZE || memcmp(frame, "BLS1", 4) != 0 ||
            crc16(frame, 17) != read16(frame + 17)) return false;
        Status incoming;
        incoming.session = read32(frame + 4);
        incoming.sequence = read16(frame + 8);
        incoming.mode = frame[10];
        incoming.flags = frame[11];
        incoming.request_seq = read32(frame + 12);
        incoming.error = frame[16];
        if (incoming.mode > MODE_ERROR || (incoming.flags & 0xF0) || incoming.error > 7) return false;
        const bool intent = (incoming.flags & FLAG_INTENT) != 0;
        if (incoming.mode == MODE_ENABLED && (!intent || incoming.error)) return false;
        if (incoming.mode == MODE_PAUSING && (intent || incoming.error)) return false;
        // Paused requires a ready adapter with no intent, connection or advertising.
        if (incoming.mode == MODE_PAUSED && (incoming.flags != FLAG_READY || incoming.error)) {
            return false;
        }
        // ERROR retains actual flags, including connections left after failure.
        if (incoming.mode == MODE_ERROR && !incoming.error) return false;
        for (size_t i = 0; i < retired_count_; ++i) {
            if (incoming.session == retired_[i]) return false;
        }
        if (have_ && incoming.session == state.session) {
            const uint16_t distance = static_cast<uint16_t>(incoming.sequence - state.sequence);
            if (distance == 0 || distance >= 0x8000) return false;
        }
        if (have_ && incoming.session != state.session) {
            // Bound replay history without allocation. Recent boot packets can
            // never replace a newer boot, even after its status has expired.
            retired_[retired_next_] = state.session;
            retired_next_ = static_cast<uint8_t>((retired_next_ + 1) % RETIRED_CAPACITY);
            if (retired_count_ < RETIRED_CAPACITY) ++retired_count_;
        }
        state = incoming;
        received_at_ = now_ms;
        have_ = true;
        expired_ = false;
        return true;
    }

private:
    static const size_t RETIRED_CAPACITY = 8;
    bool have_;
    mutable bool expired_;
    uint32_t received_at_, retired_[RETIRED_CAPACITY];
    uint8_t retired_count_, retired_next_;
};

}  // namespace ble_status

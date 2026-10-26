// Settings-page request confirmation; MAC delivery never completes a request.
#pragma once
#include "ble_status.h"

namespace ble_control {

enum Result { IDLE, WAITING, CONFIRMED, FAILED, TIMED_OUT, RESTARTED };
static const uint32_t REQUEST_TIMEOUT_MS = 6500;

class Control {
public:
    ble_status::Decoder status;
    Result result;

    Control() { reset(); }

    void reset() { status.reset(); result = IDLE; }

    bool can_request(uint32_t now) const {
        return result != WAITING && status.fresh(now) &&
               (status.state.flags & ble_status::FLAG_READY) &&
               status.state.mode != ble_status::MODE_PAUSING;
    }

    bool begin(bool pause, uint32_t request_seq, uint32_t now) {
        if (!can_request(now)) return false;
        pause_ = pause;
        request_ = request_seq;
        session_ = status.state.session;
        baseline_ = status.state.sequence;
        sent_at_ = now;
        result = WAITING;
        return true;
    }

    void tick(uint32_t now) {
        if (result != WAITING) return;
        if (status.fresh(now)) {
            const ble_status::Status &s = status.state;
            const uint16_t distance = static_cast<uint16_t>(s.sequence - baseline_);
            if (s.session != session_) { result = RESTARTED; return; }
            if (distance && distance < 0x8000 && s.request_seq == request_) {
                if (s.mode == ble_status::MODE_ERROR) { result = FAILED; return; }
                if ((pause_ && status.confirmed_paused(now)) ||
                    (!pause_ && s.mode == ble_status::MODE_ENABLED &&
                     (s.flags & ble_status::FLAG_READY) &&
                     (s.flags & (ble_status::FLAG_CONNECTED | ble_status::FLAG_ADVERTISING)))) {
                    result = CONFIRMED;
                    return;
                }
            }
        }
        if (static_cast<uint32_t>(now - sent_at_) >= REQUEST_TIMEOUT_MS) result = TIMED_OUT;
    }

private:
    bool pause_;
    uint32_t request_, session_, sent_at_;
    uint16_t baseline_;
};

}  // namespace ble_control

// Bounded relative-volume requests from the center-return slider.
// No absolute source volume is known. Call direction_due() from the UI loop,
// send its standalone BT_VOLUP / BT_VOLDN token synchronously, then call
// on_sent() with the completion time and radio delivery result.

#pragma once
#include <stdint.h>

class VolumeAdjustment {
public:
    enum { MAX_STEPS = 5, INTERVAL_MS = 200, EXPIRY_MS = 3000 };

    VolumeAdjustment()
        : remaining_(0), requested_at_(0), completed_at_(0),
          has_completion_(false), offered_(false) {}

    // Replace an old gesture, clamping before arithmetic (including INT_MIN).
    // Previous send completion still governs pacing across gestures.
    void request(int steps, uint32_t now) {
        cancel();
        remaining_ = steps > MAX_STEPS ? MAX_STEPS
                   : steps < -MAX_STEPS ? -MAX_STEPS : steps;
        requested_at_ = now;
    }

    // Use on a new touch, press loss, another button, or send failure.
    void cancel() {
        remaining_ = 0;
        offered_ = false;
    }

    // Offer at most one step; it remains pending until on_sent(). All elapsed
    // times use unsigned subtraction so a normal millis() wrap is harmless.
    int direction_due(uint32_t now) {
        if (!remaining_) return 0;
        if (elapsed(now, requested_at_) >= EXPIRY_MS) {
            cancel();
            return 0;
        }
        if (offered_) return 0;
        if (has_completion_ && elapsed(now, completed_at_) < INTERVAL_MS) return 0;
        offered_ = true;
        return remaining_ > 0 ? 1 : -1;
    }

    // Pair immediately with the synchronous send offered above. A failed/off
    // link cancels all remaining steps; a slow send cannot create a catch-up
    // burst or extend the original request's lifetime.
    void on_sent(uint32_t now, bool delivered) {
        if (!offered_) return;
        offered_ = false;
        completed_at_ = now;
        has_completion_ = true;
        if (!delivered || elapsed(now, requested_at_) >= EXPIRY_MS) {
            remaining_ = 0;
            return;
        }
        remaining_ += remaining_ > 0 ? -1 : 1;
    }

    // Signed remaining steps, including an offered but unfinished step.
    int pending() const { return remaining_; }

private:
    static uint32_t elapsed(uint32_t now, uint32_t then) { return now - then; }

    int remaining_;
    uint32_t requested_at_;
    uint32_t completed_at_;
    bool has_completion_;
    bool offered_;
};

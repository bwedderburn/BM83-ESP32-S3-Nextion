// Bounded local recovery for a committed artwork AP; no radio or reset APIs.
#pragma once

#include <stdint.h>

namespace network_recovery {

// Avoid allocating WiFi.SSID() strings in every UI loop. A lost association
// invalidates immediately; a new IP generation requires a new identity check.
class CommittedTargetCheck {
public:
    CommittedTargetCheck() { clear(); }

    void clear() { valid_ = matched_ = false; checked_at_ = generation_ = 0; }

    bool due(bool associated, uint32_t generation, uint32_t now) {
        if (!associated) { clear(); return false; }
        return !valid_ || generation != generation_ ||
               static_cast<uint32_t>(now - checked_at_) >= 1000;
    }

    void record(bool matched, uint32_t generation, uint32_t now) {
        valid_ = true;
        matched_ = matched;
        generation_ = generation;
        checked_at_ = now;
    }

    bool confirmed(bool associated, uint32_t generation) const {
        return associated && valid_ && matched_ && generation == generation_;
    }

private:
    bool valid_, matched_;
    uint32_t checked_at_, generation_;
};

class Policy {
public:
    enum class PauseReason : uint8_t { None, PeerMissing, ApUnavailable };
    static const uint32_t PEER_MISSING_MS = 10000;
    static const uint32_t PEER_STABLE_MS = 3000;
    static const uint32_t REARM_STABLE_MS = 30000;
    static const uint8_t MAX_ATTEMPTS = 3;

    Policy() { disable(); }

    // A boot/manual join or committed USB enrollment starts a new episode.
    void enable(uint32_t now) {
        disable();
        enabled_ = true;
        missing_since_ = wait_since_ = now;
    }

    // Explicitly disabled/trial profiles never become automatic candidates.
    void disable() {
        enabled_ = paused_ = suspended_ = known_ = fresh_ = connected_ = false;
        attempts_ = 0;
        reason_ = PauseReason::None;
        missing_since_ = fresh_since_ = connected_since_ = wait_since_ = 0;
    }

    void peer(bool fresh, uint32_t now) {
        if (suspended_) return;
        if (!known_ || (fresh_ && !fresh)) missing_since_ = now;
        if ((!known_ || !fresh_) && fresh) fresh_since_ = now;
        known_ = true;
        fresh_ = fresh;
    }

    void peer(bool playback_fresh, bool status_fresh, uint32_t now) {
        peer(playback_fresh || status_fresh, now);
    }

    void connected(bool connected, uint32_t now) {
        if (suspended_) return;
        if (connected && !connected_) connected_since_ = now;
        connected_ = connected;
        // A brief successful join cannot reset the retry budget and thrash.
        if (enabled_ && !paused_ && connected_ && fresh_ &&
            elapsed(now, connected_since_, REARM_STABLE_MS) &&
            elapsed(now, fresh_since_, REARM_STABLE_MS)) attempts_ = 0;
    }

    bool peer_missing(uint32_t now) const {
        // Also used by the existing USB trial-link verification. Only the
        // committed-profile flag below grants automatic recovery permission.
        return !suspended_ && known_ && !fresh_ &&
               elapsed(now, missing_since_, PEER_MISSING_MS);
    }

    void pause(PauseReason reason, uint32_t now) {
        if (!enabled_ || suspended_) return;
        paused_ = true;
        connected_ = false;
        reason_ = reason;
        wait_since_ = now;
    }

    bool local_join_due(uint32_t now) const {
        return enabled_ && paused_ && !suspended_ && known_ && fresh_ &&
               attempts_ < MAX_ATTEMPTS &&
               elapsed(now, fresh_since_, PEER_STABLE_MS) &&
               elapsed(now, wait_since_, retry_wait_ms());
    }

    // Caller invokes this only after selecting the existing active profile.
    bool begin_local_join(uint32_t now) {
        if (!local_join_due(now)) return false;
        ++attempts_;
        paused_ = false;
        connected_ = false;
        reason_ = PauseReason::None;
        return true;
    }

    void suspend() { suspended_ = true; connected_ = false; }

    void resume(uint32_t now) {
        suspended_ = false;
        known_ = fresh_ = connected_ = false;
        missing_since_ = wait_since_ = now;
        // Keep auto-paused versus explicitly disabled, and keep its budget.
    }

    bool auto_paused() const { return enabled_ && paused_; }
    // Finding a returning peer must not itself depend on receiving that peer.
    // Listening never consumes/rearms the separate bounded AP-join budget.
    bool idle_discovery_allowed(uint32_t now) const { return auto_paused() && peer_missing(now); }
    bool exhausted() const { return auto_paused() && attempts_ >= MAX_ATTEMPTS; }
    uint8_t attempts() const { return attempts_; }
    PauseReason reason() const { return reason_; }

private:
    bool enabled_, paused_, suspended_, known_, fresh_, connected_;
    uint8_t attempts_;
    PauseReason reason_;
    uint32_t missing_since_, fresh_since_, connected_since_, wait_since_;

    static bool elapsed(uint32_t now, uint32_t since, uint32_t duration) {
        return static_cast<uint32_t>(now - since) >= duration;
    }

    uint32_t retry_wait_ms() const {
        return attempts_ == 0 ? 5000 : attempts_ == 1 ? 30000 : 60000;
    }
};

// Cooperative passive listening: no probe sends, waits or semantic commands.
// The caller performs at most the single returned channel change per tick.
class IdleChannelSweep {
public:
    static const uint32_t DWELL_MS = 2500;
    static const uint32_t COOLDOWN_MS = 10000;
    static const uint8_t CHANNELS = 13;

    IdleChannelSweep() : channel_(0), cooling_(false), changed_at_(0) {}

    uint8_t tick(bool allowed, uint32_t now) {
        if (!allowed) { cancel(now); return 0; }
        if (!channel_) {
            if (cooling_ && static_cast<uint32_t>(now - changed_at_) < COOLDOWN_MS) return 0;
            channel_ = 1;
            cooling_ = false;
            changed_at_ = now;
            return channel_;
        }
        if (static_cast<uint32_t>(now - changed_at_) < DWELL_MS) return 0;
        changed_at_ = now;  // Never catch up with multiple hops after a delayed tick.
        if (channel_ < CHANNELS) return ++channel_;
        channel_ = 0;
        cooling_ = true;
        return 0;
    }

    void cancel(uint32_t now) {
        if (channel_) postpone(now);
    }

    // User controls and native errors defer background listening, even between sweeps.
    void postpone(uint32_t now) { channel_ = 0; cooling_ = true; changed_at_ = now; }
    bool active() const { return channel_ != 0; }

private:
    uint8_t channel_;
    bool cooling_;
    uint32_t changed_at_;
};

// Software queue clearing cannot fence a delayed native callback. After a hop,
// require newly validated publications spanning the stability window, and spend
// an AP attempt only on a new receipt, never on TTL-retained freshness alone.
class PostHopReceiptGuard {
public:
    PostHopReceiptGuard() { reset(); }
    void reset() { required_ = have_ = received_ = false; first_ = last_ = 0; }
    void require() { reset(); required_ = true; }

    void observe(bool fresh, bool newly_received, uint32_t now) {
        received_ = false;
        if (!required_) return;
        if (!fresh) { have_ = false; return; }
        if (newly_received) {
            if (!have_) { first_ = now; have_ = true; }
            last_ = now;
            received_ = true;
        }
    }

    bool ready() const {
        return !required_ || (have_ && received_ &&
            static_cast<uint32_t>(last_ - first_) >= Policy::PEER_STABLE_MS);
    }

private:
    bool required_, have_, received_;
    uint32_t first_, last_;
};

}  // namespace network_recovery

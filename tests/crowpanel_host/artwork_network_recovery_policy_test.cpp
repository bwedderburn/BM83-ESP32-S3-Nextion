#include "network_recovery_policy.h"
#include "ble_status.h"
#include "now_playing.h"

#include <assert.h>
#include <stdint.h>

using network_recovery::Policy;
using network_recovery::IdleChannelSweep;
using network_recovery::PostHopReceiptGuard;

static void unavailable(Policy &policy, uint32_t now) {
    policy.peer(false, now);
    policy.connected(false, now);
    assert(policy.peer_missing(now + Policy::PEER_MISSING_MS));
    policy.pause(Policy::PauseReason::PeerMissing, now + Policy::PEER_MISSING_MS);
}

static void startup_orders_and_health() {
    Policy controller_first;
    controller_first.enable(0);
    controller_first.peer(true, 0);  // Either validated BMS2 or BLS2 is health.
    controller_first.connected(true, 0);
    assert(!controller_first.peer_missing(12000));
    assert(!controller_first.local_join_due(12000));

    Policy panel_first;
    panel_first.enable(0);
    panel_first.peer(false, 0);
    assert(!panel_first.peer_missing(9999));
    // A late controller is discovered locally after AP fallback.
    assert(panel_first.peer_missing(10000));
    panel_first.pause(Policy::PauseReason::PeerMissing, 10000);
    panel_first.peer(true, 20000);
    assert(!panel_first.local_join_due(22999));
    assert(panel_first.begin_local_join(23000));
    assert(panel_first.attempts() == 1);
    assert(!panel_first.begin_local_join(23001));

    Policy brief_loss;
    brief_loss.enable(0);
    brief_loss.peer(true, 0);
    brief_loss.peer(false, 6000);
    brief_loss.peer(true, 15000);
    assert(!brief_loss.peer_missing(16000));
    assert(!brief_loss.auto_paused());
    // Playback can remain stale while validated BLS2 keeps transport fresh.
    brief_loss.peer(true, 22000);
    assert(!brief_loss.peer_missing(40000));
}

static void bounded_ap_failures_and_rearm() {
    Policy policy;
    policy.enable(0);
    policy.peer(true, 0);
    policy.pause(Policy::PauseReason::ApUnavailable, 20000);
    assert(policy.reason() == Policy::PauseReason::ApUnavailable);
    assert(!policy.begin_local_join(24999));
    assert(policy.begin_local_join(25000));
    policy.pause(Policy::PauseReason::ApUnavailable, 45000);
    assert(!policy.begin_local_join(74999));
    assert(policy.begin_local_join(75000));
    policy.pause(Policy::PauseReason::ApUnavailable, 95000);
    assert(!policy.begin_local_join(154999));
    assert(policy.begin_local_join(155000));
    policy.pause(Policy::PauseReason::ApUnavailable, 175000);
    assert(policy.exhausted());
    assert(!policy.begin_local_join(1000000));
    // A manual retry is allowed to start another bounded episode.
    policy.enable(1000000);
    assert(policy.attempts() == 0 && !policy.auto_paused());

    unavailable(policy, 1000000);
    policy.peer(true, 1011000);
    assert(policy.begin_local_join(1015000));
    policy.connected(true, 1016000);
    policy.connected(true, 1045999);
    assert(policy.attempts() == 1);
    policy.connected(true, 1046000);
    assert(policy.attempts() == 0);
}

static void fresh_hysteresis_and_instability_budget() {
    Policy policy;
    policy.enable(0);
    unavailable(policy, 0);
    policy.peer(true, 12000);
    policy.peer(false, 14000);
    policy.peer(true, 15000);
    assert(!policy.begin_local_join(17999));
    assert(policy.begin_local_join(18000));
    policy.connected(true, 18000);
    policy.peer(false, 19000);
    policy.connected(false, 19000);
    assert(policy.peer_missing(29000));
    policy.pause(Policy::PauseReason::PeerMissing, 29000);
    policy.peer(true, 30000);
    // A brief join must not reset the attempts/cooldown and cause hopping.
    assert(policy.attempts() == 1);
    assert(!policy.begin_local_join(58999));
    assert(policy.begin_local_join(59000));
}

static void disabled_trial_and_sleep() {
    Policy disabled;
    disabled.peer(true, 0);
    disabled.pause(Policy::PauseReason::PeerMissing, 10000);
    assert(!disabled.begin_local_join(100000));
    disabled.suspend();
    disabled.resume(200000);
    disabled.peer(true, 200000);
    assert(!disabled.begin_local_join(300000));

    Policy trial;
    trial.peer(false, 0);
    assert(trial.peer_missing(10000));  // USB verification still detects loss.
    trial.pause(Policy::PauseReason::PeerMissing, 10000);
    trial.peer(true, 11000);
    assert(!trial.begin_local_join(30000));  // Pending profile is not permission.

    Policy automatic;
    automatic.enable(0);
    unavailable(automatic, 0);
    automatic.peer(true, 11000);
    automatic.suspend();
    assert(!automatic.begin_local_join(100000));
    automatic.resume(100000);
    assert(automatic.auto_paused());
    assert(!automatic.begin_local_join(110000));  // Old health is discarded.
    automatic.peer(true, 110000);
    assert(!automatic.begin_local_join(112999));
    assert(automatic.begin_local_join(113000));
    assert(automatic.attempts() == 1);
    automatic.pause(Policy::PauseReason::ApUnavailable, 120000);
    automatic.suspend();
    automatic.resume(130000);
    automatic.peer(true, 130000);
    assert(automatic.attempts() == 1);  // Sleep cannot reset bounded budget.
    assert(!automatic.begin_local_join(159999));
    assert(automatic.begin_local_join(160000));
    automatic.disable();  // Explicit user pause beats a returning peer.
    automatic.peer(true, 170000);
    assert(!automatic.begin_local_join(1000000));
}

static void wrap_safe() {
    const uint32_t before_wrap = UINT32_MAX - 2000;
    Policy policy;
    policy.enable(before_wrap);
    policy.peer(false, before_wrap);
    assert(!policy.peer_missing(before_wrap + 9999));
    assert(policy.peer_missing(before_wrap + 10000));
    policy.pause(Policy::PauseReason::PeerMissing, before_wrap + 10000);
    policy.peer(true, before_wrap + 12000);
    assert(!policy.begin_local_join(before_wrap + 14999));
    assert(policy.begin_local_join(before_wrap + 15000));
}

static void validated_status_without_playback() {
    // Real decoder, fixed cross-language fixture, no invented transport ACK.
    const uint8_t golden[] = {0x42, 0x4c, 0x53, 0x32, 0x12, 0x34, 0x56, 0x78,
        0x9a, 0xbc, 0xde, 0xf0, 0x00, 0x0b, 0x01, 0x02, 0x03, 0x04, 0x00, 0x43, 0xcb};
    now_playing::NowPlayingModel playback;
    ble_status::Decoder status;
    Policy policy;
    policy.enable(0);
    policy.peer(playback.fresh(0), status.fresh(0), 0);
    assert(status.accept(golden, sizeof(golden), 1000));
    policy.peer(playback.fresh(1000), status.fresh(1000), 1000);
    assert(!playback.fresh(1000));  // The UI still has no playback information.
    assert(!policy.peer_missing(10000));
    policy.peer(playback.fresh(3999), status.fresh(3999), 3999);
    policy.peer(playback.fresh(4000), status.fresh(4000), 4000);
    // Duplicate or corrupt frames must not restart the health grace period.
    assert(!status.accept(golden, sizeof(golden), 7999));
    uint8_t corrupt[sizeof(golden)];
    for (unsigned i = 0; i < sizeof(golden); ++i) corrupt[i] = golden[i];
    corrupt[20] ^= 1;
    assert(!status.accept(corrupt, sizeof(corrupt), 7999));
    policy.peer(playback.fresh(7999), status.fresh(7999), 7999);
    assert(!policy.peer_missing(13999));
    assert(policy.peer_missing(14000));
}

static void bounded_committed_identity_checks() {
    network_recovery::CommittedTargetCheck cache;
    assert(cache.due(true, 1, 0));
    assert(!cache.confirmed(true, 1));
    cache.record(true, 1, 0);
    assert(cache.confirmed(true, 1));
    assert(!cache.due(true, 1, 999));
    assert(cache.due(true, 1, 1000));
    cache.record(false, 1, 1000);
    assert(!cache.confirmed(true, 1));  // Wrong AP cannot rearm the budget.
    assert(!cache.due(true, 1, 1999));
    assert(cache.due(true, 1, 2000));
    cache.record(true, 1, 2000);
    assert(!cache.due(false, 1, 2001));  // Disconnection invalidates immediately.
    assert(!cache.confirmed(false, 1));
    assert(cache.due(true, 1, 2002));  // Even same-generation association rechecks.
    cache.record(true, 1, 2002);
    assert(!cache.confirmed(true, 2));
    assert(cache.due(true, 2, 2003));  // New GOT_IP skips the one-second wait.
    cache.record(true, 2, 2003);
    cache.clear();  // Trial/profile/sleep transitions must invalidate permission.
    assert(!cache.confirmed(true, 2));
    const uint32_t before_wrap = UINT32_MAX - 500;
    cache.record(true, 2, before_wrap);
    assert(!cache.due(true, 2, before_wrap + 999));
    assert(cache.due(true, 2, before_wrap + 1000));
}

static void passive_sweep_bounds_and_wrap() {
    IdleChannelSweep sweep;
    assert(sweep.tick(true, 0) == 1);
    assert(sweep.tick(true, 0) == 0);  // Never more than one channel per tick.
    for (uint8_t channel = 2; channel <= 13; ++channel) {
        const uint32_t due = (channel - 1) * IdleChannelSweep::DWELL_MS;
        assert(sweep.tick(true, due - 1) == 0);
        assert(sweep.tick(true, due) == channel);
    }
    assert(sweep.tick(true, 32500) == 0);  // End dwell, then a real cooldown.
    assert(sweep.tick(true, 42499) == 0);
    assert(sweep.tick(true, 42500) == 1);  // Repeats; not a finite three-scan budget.
    assert(sweep.tick(true, 100000) == 2);  // Delayed service never catches up in a loop.
    assert(sweep.tick(true, 100000) == 0);
    assert(sweep.tick(true, 102499) == 0);
    assert(sweep.tick(true, 102500) == 3);

    IdleChannelSweep wrapped;
    const uint32_t near_wrap = UINT32_MAX - 1000;
    assert(wrapped.tick(true, near_wrap) == 1);
    assert(wrapped.tick(true, near_wrap + 2499) == 0);
    assert(wrapped.tick(true, near_wrap + 2500) == 2);
    wrapped.postpone(near_wrap + 2501);
    assert(wrapped.tick(true, near_wrap + 12500) == 0);
    assert(wrapped.tick(true, near_wrap + 12501) == 1);
}

static void passive_cancellation_and_ap_budget() {
    IdleChannelSweep sweep;
    assert(sweep.tick(false, 0) == 0);  // Busy/export/trial/sleep is not permission.
    assert(sweep.tick(true, 100) == 1);
    assert(sweep.tick(false, 101) == 0);
    assert(!sweep.active());
    assert(sweep.tick(true, 10100) == 0);
    assert(sweep.tick(true, 10101) == 1);
    sweep.postpone(10102);  // A control request owns the radio first.
    assert(sweep.tick(true, 20101) == 0);
    assert(sweep.tick(true, 20102) == 1);

    Policy policy;
    assert(!policy.idle_discovery_allowed(100000));  // Disabled/trial never starts it.
    policy.enable(0);
    policy.peer(true, 0);
    policy.pause(Policy::PauseReason::ApUnavailable, 20000);
    assert(policy.begin_local_join(25000));
    policy.pause(Policy::PauseReason::ApUnavailable, 45000);
    assert(policy.begin_local_join(75000));
    policy.pause(Policy::PauseReason::ApUnavailable, 95000);
    assert(policy.begin_local_join(155000));
    policy.pause(Policy::PauseReason::ApUnavailable, 175000);
    policy.peer(false, 175000);
    assert(policy.idle_discovery_allowed(185000));
    for (uint32_t now = 185000; now < 400000; now += 100)
        sweep.tick(policy.idle_discovery_allowed(now), now);
    assert(policy.attempts() == 3 && policy.exhausted());
    policy.peer(true, 400000);
    assert(!policy.idle_discovery_allowed(400000));
    assert(!policy.begin_local_join(403000));  // Listening did not rearm AP attempts.
    policy.suspend();
    assert(!policy.idle_discovery_allowed(500000));
    policy.resume(500000);
    policy.peer(false, 500000);
    assert(policy.idle_discovery_allowed(510000));
    policy.disable();
    assert(!policy.idle_discovery_allowed(1000000));
}

static void late_controller_without_input_closes_circular_wait() {
    // Legacy behavior: its one scan runs while the controller is absent,
    // leaves home channel1, and no received frames can authorize AP rejoin.
    Policy legacy;
    legacy.enable(0);
    legacy.peer(false, 0);
    legacy.pause(Policy::PauseReason::PeerMissing, 10000);
    for (uint32_t now = 10000; now <= 120000; now += 100) {
        legacy.peer(false, now);  // Peer returns on ch11 at60s; home ch1 cannot hear it.
        assert(!legacy.begin_local_join(now));
    }

    Policy policy;
    IdleChannelSweep sweep;
    PostHopReceiptGuard receipts;
    ble_status::Decoder status;
    policy.enable(0);
    policy.peer(false, 0);
    policy.pause(Policy::PauseReason::PeerMissing, 10000);
    uint8_t channel = 1;
    unsigned hops = 0, completed_sweeps = 0;
    uint32_t first_received = 0, joined_at = 0, last_hop = 0;
    // No BMS2 and no button/semantic token: only real validated BLS2 frames
    // become available once a controller returning after60s is being heard.
    for (uint32_t now = 10000; now <= 120000; now += 100) {
        bool newly_received = false;
        if (now >= 60000 && channel == 11 && now % 1000 == 0) {
            uint8_t frame[] = {0x42, 0x4c, 0x53, 0x32, 0x12, 0x34, 0x56, 0x78,
                0, 0, 0, 0, 0, 0x0b, 1, 2, 3, 4, 0, 0, 0};
            const uint32_t sequence = now / 1000;
            frame[8] = sequence >> 24; frame[9] = sequence >> 16;
            frame[10] = sequence >> 8; frame[11] = sequence;
            const uint16_t crc = ble_status::crc16(frame, 19);
            frame[19] = crc >> 8; frame[20] = crc;
            assert(status.accept(frame, sizeof(frame), now));
            newly_received = true;
            if (!first_received) first_received = now;
        }
        policy.peer(false, status.fresh(now), now);  // Paused/no playback is sufficient.
        receipts.observe(status.fresh(now), newly_received, now);
        policy.connected(false, now);
        if (receipts.ready() && policy.begin_local_join(now)) { joined_at = now; break; }
        const uint8_t next = sweep.tick(policy.idle_discovery_allowed(now), now);
        if (next) {
            if (hops) assert(now - last_hop >= IdleChannelSweep::DWELL_MS);
            if (next == 1) ++completed_sweeps;
            ++hops; last_hop = now;
            if (channel != next) { receipts.require(); status.reset(); }
            channel = next;
        }
    }
    assert(completed_sweeps >= 2);  // Survived the first complete offline sweep.
    assert(first_received >= 60000 && first_received < 85000);
    assert(joined_at >= first_received + 3000 && joined_at < 90000);
    assert(channel == 11);  // Fresh frames held the found channel through stability.
    assert(policy.attempts() == 1);
}

static void cached_post_hop_snapshot_cannot_spend_an_ap_attempt() {
    Policy policy;
    PostHopReceiptGuard receipts;
    policy.enable(0);
    unavailable(policy, 0);
    receipts.require();
    // A delayed native BMS2 completed after a hop. Its decoder TTL can remain
    // fresh for6s; that alone is not3s of progressing on-channel reception.
    policy.peer(true, 20000);
    receipts.observe(true, true, 20000);
    for (uint32_t now = 20100; now <= 23000; now += 100) {
        policy.peer(true, now);
        receipts.observe(true, false, now);
        assert(!receipts.ready());
    }
    assert(policy.local_join_due(23000));  // Legacy freshness-only gate was open.
    assert(policy.attempts() == 0);
    receipts.observe(true, true, 23100);  // A new validated publication spans the hold.
    assert(receipts.ready());
    assert(policy.begin_local_join(23100));
    receipts.observe(true, false, 23200);
    assert(!receipts.ready());  // Each deferred attempt needs an actual new receipt.
    receipts.observe(false, false, 30000);
    receipts.observe(true, true, 40000);
    assert(!receipts.ready());
    receipts.observe(true, true, 43000);
    assert(receipts.ready());

    receipts.require();
    const uint32_t near_wrap = UINT32_MAX - 1000;
    receipts.observe(true, true, near_wrap);
    receipts.observe(true, true, near_wrap + 2999);
    assert(!receipts.ready());
    receipts.observe(true, true, near_wrap + 3000);
    assert(receipts.ready());
}

int main() {
    startup_orders_and_health();
    bounded_ap_failures_and_rearm();
    fresh_hysteresis_and_instability_budget();
    disabled_trial_and_sleep();
    wrap_safe();
    validated_status_without_playback();
    bounded_committed_identity_checks();
    passive_sweep_bounds_and_wrap();
    passive_cancellation_and_ap_budget();
    late_controller_without_input_closes_circular_wait();
    cached_post_hop_snapshot_cannot_spend_an_ap_attempt();
}

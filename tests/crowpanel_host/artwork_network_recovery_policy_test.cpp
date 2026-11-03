#include "network_recovery_policy.h"
#include "ble_status.h"
#include "now_playing.h"

#include <assert.h>
#include <stdint.h>

using network_recovery::Policy;

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

int main() {
    startup_orders_and_health();
    bounded_ap_failures_and_rearm();
    fresh_hysteresis_and_instability_budget();
    disabled_trial_and_sleep();
    wrap_safe();
    validated_status_without_playback();
    bounded_committed_identity_checks();
}

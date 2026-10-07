// Pure C++11 host scenarios: no Arduino, radio, serial, or hardware access.
#include "volume_adjustment.h"

#include <cstdio>
#include <cstring>
#include <limits>

namespace {
int failures = 0;

void expect(bool ok, const char *message) {
    if (!ok) {
        std::printf("FAIL: %s\n", message);
        ++failures;
    }
}

void clamping_and_completion() {
    VolumeAdjustment queue;
    expect(queue.pending() == 0 && queue.direction_due(0) == 0, "idle sends nothing");
    queue.request(std::numeric_limits<int>::max(), 0);
    expect(queue.pending() == 5, "positive request clamps to five");
    for (uint32_t n = 0; n < 5; ++n) {
        expect(queue.direction_due(n * 200) == 1, "clamped up step offered");
        expect(queue.pending() == 5 - static_cast<int>(n), "offer does not consume a step");
        expect(queue.direction_due(n * 200) == 0, "unfinished offer cannot be sent twice");
        queue.on_sent(n * 200, true);
    }
    expect(queue.pending() == 0 && queue.direction_due(1000) == 0, "exactly five steps finish");
    queue.request(std::numeric_limits<int>::min(), 1000);
    expect(queue.pending() == -5, "negative extreme safely clamps to minus five");
    expect(queue.direction_due(1000) == -1, "negative request uses down direction");
    queue.on_sent(1000, true);
    expect(queue.pending() == -4, "successful down step moves remaining count toward zero");
}

void pacing_after_blocked_send() {
    VolumeAdjustment queue;
    queue.request(3, 1000);
    expect(queue.direction_due(1000) == 1, "first step immediately due");
    queue.on_sent(1600, true);  // synchronous radio call blocked for 600 ms
    expect(queue.direction_due(1600) == 0, "no catch-up step after blocked send");
    expect(queue.direction_due(1799) == 0, "wait a full 200 ms after completion");
    expect(queue.direction_due(1800) == 1, "next step due exactly at completion plus 200 ms");
    queue.on_sent(1805, true);
    expect(queue.direction_due(2004) == 0, "pacing follows actual latest completion");
    expect(queue.direction_due(2005) == 1, "third step uses latest completion deadline");
}

void replacement_and_cancel() {
    VolumeAdjustment queue;
    queue.request(5, 0);
    expect(queue.direction_due(0) == 1, "first up step due");
    queue.on_sent(40, true);
    queue.request(-2, 50);
    expect(queue.pending() == -2, "new gesture replaces previous remaining steps");
    expect(queue.direction_due(239) == 0, "replacement cannot bypass pacing");
    expect(queue.direction_due(240) == -1, "replacement direction due after pacing");
    queue.on_sent(250, true);
    queue.cancel();
    expect(queue.pending() == 0 && queue.direction_due(2000) == 0, "press loss cancels old commands");
    queue.request(2, 300);
    expect(queue.direction_due(449) == 0, "cancel retains completion pacing");
    queue.request(0, 450);
    expect(queue.pending() == 0 && queue.direction_due(450) == 0, "center release sends nothing");
    queue.on_sent(451, true);
    expect(queue.pending() == 0, "unpaired completion does not create work");
}

void failure_stops_queue() {
    VolumeAdjustment queue;
    queue.request(5, 0);
    expect(queue.direction_due(0) == 1, "offer initial step");
    queue.on_sent(70, false);
    expect(queue.pending() == 0 && queue.direction_due(500) == 0, "no-ack or off cancels all remaining steps");
    queue.request(-1, 100);
    expect(queue.direction_due(269) == 0, "failed attempt still governs pacing");
    expect(queue.direction_due(270) == -1, "only a fresh gesture permits later work");
}

void expiry() {
    VolumeAdjustment queue;
    queue.request(3, 100);
    expect(queue.direction_due(3099) == 1, "request still valid just before three seconds");
    queue.on_sent(3100, true);
    expect(queue.pending() == 0, "completion at expiry discards unsent remainder");
    queue.request(-5, 4000);
    expect(queue.direction_due(7000) == 0 && queue.pending() == 0, "stalled loop expires exactly at deadline");
    expect(queue.direction_due(10000) == 0, "reconnect cannot replay expired steps");
    queue.request(5, 11000);
    expect(queue.direction_due(11000) == 1, "new request starts normally");
    queue.on_sent(14001, true);
    expect(queue.pending() == 0, "very slow send cannot extend original lifetime");
}

void wraparound() {
    VolumeAdjustment queue;
    const uint32_t start = 0xFFFFFF00U;
    queue.request(-2, start);
    expect(queue.direction_due(start) == -1, "first step offered before millis wrap");
    queue.on_sent(start + 100U, true);
    expect(queue.direction_due(start + 299U) == 0, "completion pacing spans wrap");
    expect(queue.direction_due(start + 300U) == -1, "due exactly after wrap-safe interval");
    queue.on_sent(start + 310U, true);
    expect(queue.pending() == 0, "wrapped request completes normally");
    queue.request(5, start);
    expect(queue.direction_due(start + 3000U) == 0 && queue.pending() == 0,
           "expiry also spans millis wrap");
}

struct Scenario { const char *name; void (*run)(); };
const Scenario scenarios[] = {
    {"clamping_and_completion", clamping_and_completion},
    {"pacing_after_blocked_send", pacing_after_blocked_send},
    {"replacement_and_cancel", replacement_and_cancel},
    {"failure_stops_queue", failure_stops_queue},
    {"expiry", expiry},
    {"wraparound", wraparound},
};
}  // namespace

int main(int argc, char **argv) {
    if (argc == 2 && std::strcmp(argv[1], "--list") == 0) {
        for (const Scenario &scenario : scenarios) std::puts(scenario.name);
        return 0;
    }
    if (argc == 2) {
        for (const Scenario &scenario : scenarios) {
            if (std::strcmp(argv[1], scenario.name) == 0) {
                scenario.run();
                return failures ? 1 : 0;
            }
        }
    }
    std::fprintf(stderr, "usage: volume_adjustment_test --list | <scenario>\n");
    return 2;
}

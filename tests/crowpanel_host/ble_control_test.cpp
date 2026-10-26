#include "ble_control.h"
#include <assert.h>
#include <string.h>

static void put32(uint8_t *out, uint32_t value) {
    for (int i = 3; i >= 0; --i) { out[i] = static_cast<uint8_t>(value); value >>= 8; }
}

static bool report(ble_control::Control &control, uint32_t session, uint16_t sequence,
                   uint8_t mode, uint8_t flags, uint32_t request, uint32_t now,
                   uint8_t error = 0) {
    uint8_t frame[19] = {'B', 'L', 'S', '1'};
    put32(frame + 4, session);
    frame[8] = static_cast<uint8_t>(sequence >> 8);
    frame[9] = static_cast<uint8_t>(sequence);
    frame[10] = mode;
    frame[11] = flags;
    put32(frame + 12, request);
    frame[16] = error;
    const uint16_t crc = ble_status::crc16(frame, 17);
    frame[17] = static_cast<uint8_t>(crc >> 8);
    frame[18] = static_cast<uint8_t>(crc);
    const bool accepted = control.status.accept(frame, sizeof(frame), now);
    control.tick(now);
    return accepted;
}

static void pause_confirmation() {
    ble_control::Control control;
    assert(!control.can_request(0));
    assert(report(control, 1, 10, 0, 7, 0, 0));
    assert(control.begin(true, 42, 0));
    // Receiving a MAC ACK never calls any confirmation method. Even a valid
    // duplicate, unrelated request, or Pausing report cannot complete Pause.
    assert(!report(control, 1, 10, 2, 2, 42, 100));
    assert(report(control, 1, 11, 2, 2, 41, 200));
    assert(control.result == ble_control::WAITING);
    assert(report(control, 1, 12, 1, 6, 42, 300));
    assert(control.result == ble_control::WAITING);
    assert(!control.can_request(300));
    assert(report(control, 1, 13, 2, 2, 42, 400));
    assert(control.result == ble_control::CONFIRMED);
    assert(control.status.confirmed_paused(400));
    assert(control.can_request(400));
}

static void enable_confirmation() {
    ble_control::Control control;
    assert(report(control, 1, 0xFFFF, 2, 2, 0, 0));
    assert(control.begin(false, 43, 0));
    assert(report(control, 1, 0, 0, 3, 43, 100));  // Intent alone is insufficient.
    assert(control.result == ble_control::WAITING);
    assert(report(control, 1, 1, 0, 11, 43, 200));
    assert(control.result == ble_control::CONFIRMED);
    assert(control.begin(true, 44, 200));
    assert(report(control, 1, 2, 3, 7, 44, 300, 3));  // Failed termination, still connected.
    assert(control.result == ble_control::FAILED);
    assert(!control.status.confirmed_paused(300));
}

static void stale_reboot_and_deadline() {
    ble_control::Control control;
    assert(report(control, 1, 1, 0, 7, 0, 0xFFFFFF00));
    assert(control.begin(true, 42, 0xFFFFFF00));
    control.tick(0xFFFFFF00 + 3000U);
    assert(!control.can_request(0xFFFFFF00 + 3000U));
    assert(!control.status.confirmed_paused(0xFFFFFF00 + 3000U));
    control.tick(0xFFFFFF00 + 6500U);
    assert(control.result == ble_control::TIMED_OUT);
    control.reset();
    assert(!control.can_request(0));
    assert(report(control, 1, 1, 0, 7, 0, 0));
    assert(control.begin(true, 42, 0));
    assert(report(control, 2, 1, 2, 2, 42, 100));
    assert(control.result == ble_control::RESTARTED);  // Same echo from a different boot is not success.
    assert(!report(control, 1, 2, 2, 2, 42, 200));
}

int main(int argc, char **argv) {
    assert(argc == 2);
    if (strcmp(argv[1], "pause") == 0) pause_confirmation();
    else if (strcmp(argv[1], "enable") == 0) enable_confirmation();
    else if (strcmp(argv[1], "expiry") == 0) stale_reboot_and_deadline();
    else return 2;
    return 0;
}

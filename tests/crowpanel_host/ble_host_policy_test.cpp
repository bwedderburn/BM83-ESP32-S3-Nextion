#include "ble_host_policy.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
namespace hp = ble_host_policy;
static const uint8_t A[8] = {1,2,3,4,5,6,7,8}, B[8] = {8,7,6,5,4,3,2,1};
static const uint16_t CONNECT_FLAGS = hp::READY | hp::CONNECTED_FLAG | hp::ENCRYPTED |
    hp::BONDED | hp::HID_READY | hp::PERSISTED | hp::FILTER_READY;

static size_t unhex(const char *value, uint8_t *out) {
    const size_t length = strlen(value); assert(length % 2 == 0 && length / 2 <= 360);
    for (size_t i = 0; i < length / 2; ++i) {
        unsigned byte = 0; assert(sscanf(value + i * 2, "%2x", &byte) == 1); out[i] = static_cast<uint8_t>(byte);
    }
    return length / 2;
}

static size_t fragment(uint8_t *out, const uint8_t *body, size_t total, uint8_t kind,
                       uint8_t index, uint32_t session, uint32_t sequence) {
    const size_t count = (total + 44) / 45, offset = index * 45;
    const size_t bytes = total - offset < 45 ? total - offset : 45;
    memcpy(out, "BHP1", 4); hp::put32(out + 4, session); hp::put32(out + 8, sequence);
    out[12] = kind; out[13] = index; out[14] = count; hp::put16(out + 15, total);
    memcpy(out + 17, body + offset, bytes);
    hp::put16(out + 17 + bytes, ble_status::crc16(out, 17 + bytes));
    return 19 + bytes;
}
static void status_body(uint8_t *p, uint32_t request = 0, uint32_t operation = 10,
                        uint16_t flags = CONNECT_FLAGS, uint8_t state = hp::CONNECTED,
                        uint8_t mode = hp::AUTO, const uint8_t *target = A, uint32_t generation = 3) {
    memset(p, 0, 63); p[0] = 1; p[1] = 1;
    hp::put32(p + 3, 77); hp::put32(p + 7, request); hp::put32(p + 11, operation);
    hp::put32(p + 15, operation); hp::put32(p + 19, generation); hp::put32(p + 23, 5);
    p[27] = p[28] = mode; p[29] = state; hp::put16(p + 30, flags);
    if (target) memcpy(p + 47, target, 8);
    if (flags & hp::CONNECTED_FLAG) memcpy(p + 55, target, 8);
}
static size_t list_body(uint8_t *p, uint32_t generation = 3, const char *alias = "Desk") {
    memset(p, 0, 278); p[0] = 1; hp::put32(p + 1, generation); p[5] = 2;
    size_t offset = 6;
    memcpy(p + offset, A, 8); p[offset + 8] = hp::OUR_SEC | hp::PEER_SEC | hp::CCCD | hp::RESUMABLE;
    p[offset + 9] = strlen(alias); memcpy(p + offset + 10, alias, strlen(alias)); offset += 10 + strlen(alias);
    memcpy(p + offset, B, 8); p[offset + 8] = hp::RESUMABLE; p[offset + 9] = 0;
    return offset + 10;
}
static bool publish(hp::Decoder &d, const uint8_t *body, size_t total, uint8_t kind,
                    uint32_t sequence, uint32_t now, uint32_t session = 101) {
    uint8_t frame[64]; bool accepted = false;
    for (size_t index = 0; index < (total + 44) / 45; ++index) {
        const size_t n = fragment(frame, body, total, kind, index, session, sequence);
        accepted = d.accept(frame, n, now + index);
    }
    return accepted;
}
static void seed(hp::Control &c, uint32_t now = 0) {
    uint8_t body[278]; status_body(body);
    assert(publish(c.decoder, body, 63, 1, 1, now));
    const size_t count = list_body(body); assert(publish(c.decoder, body, count, 2, 2, now + 2));
    c.tick(now + 3); uint8_t handshake[32];
    assert(!c.can_manage(now + 3));
    assert(c.handshake_request(now + 3, handshake, sizeof(handshake)) == 32);
    assert(handshake[16] == hp::LIST && ble_status::read32(handshake + 17) == 1);
    status_body(body, ble_status::read32(handshake + 12)); body[1] = 4; hp::put32(body + 3, c.client_session);
    assert(publish(c.decoder, body, 63, 1, 2, now + 4)); c.tick(now + 5);
    assert(c.admitted(now + 5) && c.choose(0, now + 5));
}
static void report(hp::Control &c, uint8_t *body, uint32_t sequence, uint32_t now) {
    assert(publish(c.decoder, body, 63, 1, sequence, now)); c.tick(now + 1);
}

static void codec_and_aliases() {
    uint8_t out[64] = {};
    const size_t n = hp::command(out, sizeof(out), 101, 77, 0xFFFFFFFFU, hp::SELECT, 3, A);
    assert(n == 32 && !memcmp(out, "BHC1", 4));
    assert(ble_status::read32(out + 4) == 101 && ble_status::read32(out + 8) == 77);
    assert(ble_status::read32(out + 12) == 0xFFFFFFFFU && out[16] == 2 && out[29] == 0);
    assert(!memcmp(out + 21, A, 8) && ble_status::read16(out + 30) == ble_status::crc16(out, 30));
    assert(!hp::command(out, sizeof(out), 101, 77, 1, hp::SELECT, 3));
    assert(!hp::command(out, sizeof(out), 101, 77, 1, hp::DISCONNECT, 3, A));
    assert(!hp::command(out, sizeof(out), 0, 77, 1, hp::DISCONNECT, 3));
    uint8_t seconds[2]; hp::put16(seconds, 60);
    assert(hp::command(out, sizeof(out), 101, 77, 0, hp::ENROLL, 3, nullptr, seconds, 2) == 34);
    hp::put16(seconds, 121); assert(!hp::command(out, sizeof(out), 101, 77, 1, hp::ENROLL, 3, nullptr, seconds, 2));
    const uint8_t good[] = {'M',0xC3,0xA1,'c'};
    assert(hp::valid_alias(good, sizeof(good)) && hp::valid_alias(nullptr, 0));
    const uint8_t controls[][4] = {{'a','\n',0,0},{0xC2,0x80,0,0},{0xC0,0xAF,0,0},{0xED,0xA0,0x80,0},{0xF4,0x90,0x80,0x80}};
    const size_t sizes[] = {2,2,2,3,4};
    for (size_t i = 0; i < 5; ++i) assert(!hp::valid_alias(controls[i], sizes[i]));
    uint8_t long_name[25]; memset(long_name, 'x', sizeof(long_name)); assert(!hp::valid_alias(long_name, sizeof(long_name)));
}

static void reassembly_and_validation() {
    hp::Decoder d; uint8_t status[63], list[278], a[64], b[64]; status_body(status);
    const size_t n1 = fragment(a, status, 63, 1, 1, 101, 1);
    assert(!d.accept(a, n1, 10) && !d.fresh_status(10));
    const size_t ln = list_body(list); assert(publish(d, list, ln, 2, 2, 11));
    const size_t n0 = fragment(b, status, 63, 1, 0, 101, 1);
    assert(d.accept(b, n0, 12) && d.coherent_list(12));
    assert(d.list.count == 2 && !strcmp(d.list.peers[0].alias, "Desk"));
    assert(!d.accept(b, n0, 13));  // Completed duplicate cannot refresh.
    assert(!d.accept(a, n1 - 1, 14));
    a[n1 - 1] ^= 1; assert(!d.accept(a, n1, 14));
    // Changed duplicate poisons only its packet; a later publication heals it.
    fragment(b, status, 63, 1, 0, 101, 3); assert(!d.accept(b, n0, 20));
    b[17 + 15] ^= 1; hp::put16(b + n0 - 2, ble_status::crc16(b, n0 - 2)); assert(!d.accept(b, n0, 21));
    const size_t tail = fragment(a, status, 63, 1, 1, 101, 3); assert(!d.accept(a, tail, 22));
    assert(publish(d, status, 63, 1, 4, 23));
    // Expired partial frames cannot join a late tail, including tick wrap.
    const uint32_t near_wrap = 0xFFFFFF00U;
    fragment(b, status, 63, 1, 0, 101, 5); assert(!d.accept(b, n0, near_wrap));
    fragment(a, status, 63, 1, 1, 101, 5); assert(!d.accept(a, tail, near_wrap + 2000U));
    assert(publish(d, status, 63, 1, 6, near_wrap + 2001U));
    // Strict list validation does not replace the last committed list.
    list[6] = 0; memset(list + 6, 0, 8); assert(!publish(d, list, ln, 2, 7, 100));
    list_body(list); memcpy(list + 20, A, 8); assert(!publish(d, list, ln, 2, 8, 101));
    status[0] = 2; assert(!publish(d, status, 63, 1, 9, 102));
}

static void ordering_sessions_and_stale() {
    hp::Decoder d; uint8_t body[278]; status_body(body);
    assert(publish(d, body, 63, 1, 0xFFFFFFFFU, 100));
    assert(publish(d, body, 63, 1, 0, 110));
    assert(!publish(d, body, 63, 1, 0xFFFFFFFFU, 120));
    assert(!d.fresh_status(5111)); assert(!d.fresh_status(111));
    assert(publish(d, body, 63, 1, 80000, 100000));
    assert(publish(d, body, 63, 1, 1, 100100, 202));
    assert(!publish(d, body, 63, 1, 80001, 100200, 101));
    assert(!d.fresh_list(100200));
    body[0] = 0; body[29] = hp::UNSUPPORTED;
    assert(publish(d, body, 63, 1, 2, 100300, 202)); assert(!d.supported(100301));
    uint8_t old[21] = {'B','L','S','2'}; assert(!d.accept(old, sizeof(old), 100301));
    assert(ble_status::FRAME_SIZE == 21);
}

static void connection_completion_races() {
    hp::Control c(77); seed(c); uint8_t command[64], body[278];
    assert(c.begin(hp::SELECT, 5, command, sizeof(command)) == 32);
    const uint32_t request = ble_status::read32(command + 12);
    status_body(body, request, 0); report(c, body, 3, 10); assert(c.result == hp::PENDING);
    status_body(body, request, 10); report(c, body, 4, 15); assert(c.result == hp::PENDING); // Previous operation cannot complete a same-host request.
    status_body(body, request, 20, CONNECT_FLAGS & ~hp::READY); report(c, body, 5, 20); assert(c.result == hp::PENDING);
    status_body(body, request, 0); report(c, body, 6, 25); assert(c.result == hp::PENDING); // Current packet must still carry the matching submitted operation.
    status_body(body, request, 20, CONNECT_FLAGS & ~hp::HID_READY); report(c, body, 7, 30); assert(c.result == hp::PENDING);
    status_body(body, request, 20); report(c, body, 8, 40); assert(c.result == hp::CONFIRMED);
    assert(c.begin(hp::SELECT, 45, command, sizeof(command)));
    const uint32_t next = ble_status::read32(command + 12);
    status_body(body, next - 1, 20); report(c, body, 9, 50); assert(c.result == hp::PENDING);
    status_body(body, next, 0); report(c, body, 10, 60); assert(c.result == hp::PENDING);
    status_body(body, next, 21); report(c, body, 11, 70); assert(c.result == hp::CONFIRMED);
    // Explicit Disconnect supersedes an in-flight connect; old echoes cannot win.
    assert(c.begin(hp::SELECT, 75, command, sizeof(command)));
    const uint32_t obsolete = ble_status::read32(command + 12);
    assert(c.begin(hp::DISCONNECT, 76, command, sizeof(command)));
    const uint32_t pause = ble_status::read32(command + 12);
    status_body(body, obsolete, 22); report(c, body, 12, 80); assert(c.result == hp::PENDING);
    status_body(body, pause, 23, hp::READY | hp::PERSISTED, hp::PAUSED_STATE, hp::PAUSED, nullptr);
    report(c, body, 13, 90); assert(c.result == hp::CONFIRMED);
}

static void golden_commands() {
    const char *expected[] = {
        "42484331a1b2c3d411223344ffffffff0000000001000000000000000000b1e4",
        "42484331a1b2c3d411223344ffffffff0100000000000000000000000000a5c0",
        "42484331a1b2c3d411223344ffffffff02000000030102030405060708002bfd",
        "42484331a1b2c3d411223344ffffffff0300000000000000000000000002003ce211",
        "42484331a1b2c3d411223344ffffffff0400000003010203040506070805506920c3a9bb14",
        "42484331a1b2c3d411223344ffffffff05000000030102030405060708005bfb"};
    uint8_t frame[64], golden[360], seconds[2] = {0,60}; const uint8_t alias[] = {'P','i',' ',0xC3,0xA9};
    for (unsigned op = 0; op <= 5; ++op) {
        const uint8_t *payload = op == 3 ? seconds : op == 4 ? alias : nullptr;
        const size_t bytes = op == 3 ? 2 : op == 4 ? 5 : 0;
        const size_t actual = hp::command(frame, sizeof(frame), 0xA1B2C3D4U, 0x11223344U, 0xFFFFFFFFU,
                                         static_cast<hp::Opcode>(op), op == 0 ? 1 : op == 2 || op == 4 || op == 5 ? 3 : 0,
                                         op == 2 || op == 4 || op == 5 ? A : nullptr, payload, bytes);
        const size_t wanted = unhex(expected[op], golden); assert(actual == wanted && !memcmp(frame, golden, actual));
    }
}

static void golden_frames(int argc, char **argv) {
    assert(argc >= 4); hp::Decoder decoder; uint8_t frame[360];
    for (int index = 3; index < argc; ++index) {
        const size_t length = unhex(argv[index], frame);
        const bool committed = decoder.accept(frame, length, 100 + index);
        assert(committed == (index == argc - 1));
    }
    if (!strcmp(argv[2], "status")) {
        assert(decoder.status.native_version == 1 && decoder.status.native_operation == 42);
        assert(decoder.status.reason == 0x213 && decoder.status.flags == CONNECT_FLAGS);
        assert(decoder.status.client_session == 0x11223344 && decoder.status.request_sequence == 0xFFFFFFFFU);
    } else if (!strcmp(argv[2], "max_list")) {
        assert(decoder.list.count == 8 && decoder.list.bond_generation == 3);
        for (size_t index = 0; index < 8; ++index) {
            assert(strlen(decoder.list.peers[index].alias) == 24);
            assert(decoder.list.peers[index].id[7] == index + 1);
        }
    } else { assert(!strcmp(argv[2], "unsupported")); assert(!decoder.supported(200)); }
}

static void generations_waiting_and_reboots() {
    hp::Control c(77); seed(c); uint8_t command[64], body[278];
    status_body(body, 0, 10, CONNECT_FLAGS, hp::CONNECTED, hp::AUTO, A, 4); report(c, body, 3, 10);
    assert(!c.can_connect(11));  // A fresh status cannot bless the old generation list.
    const size_t ln = list_body(body, 4); assert(publish(c.decoder, body, ln, 2, 4, 12)); assert(c.can_connect(13));
    assert(c.begin(hp::SELECT, 15, command, sizeof(command)));
    const uint32_t request = ble_status::read32(command + 12);
    status_body(body, request, 20, hp::READY | hp::PERSISTED | hp::FILTER_READY | hp::ADVERTISING, hp::WAITING, hp::AUTO, A, 4);
    report(c, body, 5, 20); assert(c.result == hp::WAITING_HOST && c.can_connect(21));
    c.tick(20000); assert(c.result == hp::WAITING_HOST); // Offline policy is honest, not a fabricated connection.
    assert(!c.can_connect(20000));
    status_body(body, request, 20, CONNECT_FLAGS, hp::CONNECTED, hp::AUTO, A, 4);
    report(c, body, 6, 20001); assert(c.result == hp::CONFIRMED);
    const size_t count = list_body(body, 4); assert(publish(c.decoder, body, count, 2, 7, 20003));
    assert(!c.can_manage(20004));
    assert(c.handshake_request(20004, command, sizeof(command)) == 32);
    status_body(body, ble_status::read32(command + 12), 20, CONNECT_FLAGS, hp::CONNECTED, hp::AUTO, A, 4); body[1] = 4;
    report(c, body, 8, 20005); assert(c.can_manage(20006));
    assert(c.begin(hp::DISCONNECT, 20007, command, sizeof(command)));
    status_body(body, ble_status::read32(command + 12), 21, hp::READY | hp::PERSISTED, hp::PAUSED_STATE, hp::PAUSED, nullptr);
    assert(publish(c.decoder, body, 63, 1, 1, 20008, 303)); c.tick(20009); assert(c.result == hp::RESTARTED);
    assert(!publish(c.decoder, body, 63, 1, 9, 20010, 101));
}

static void alias_enroll_errors_and_wrap() {
    hp::Control c(77, 0xFFFFFFFEU); seed(c); uint8_t command[64], body[278];
    assert(c.begin(hp::ALIAS, 5, command, sizeof(command), "Work") == 36);
    assert(ble_status::read32(command + 12) == 0);
    status_body(body, 0, 20); body[1] = 3; report(c, body, 3, 10); assert(c.result == hp::PENDING);
    const size_t ln = list_body(body, 3, "Work"); assert(publish(c.decoder, body, ln, 2, 4, 12)); c.tick(13); assert(c.result == hp::CONFIRMED);
    assert(c.begin(hp::ENROLL, 20, command, sizeof(command), nullptr, 60) == 34);
    const uint32_t request = ble_status::read32(command + 12);
    status_body(body, request, 21, hp::READY | hp::PERSISTED | hp::ADVERTISING | hp::FILTER_READY, hp::ENROLLING, hp::ENROLL_MODE, nullptr);
    hp::put16(body + 45, 59); report(c, body, 5, 30); assert(c.result == hp::PAIRING);
    status_body(body, request, 21, CONNECT_FLAGS, hp::CONNECTED, hp::AUTO, B, 4); report(c, body, 6, 40); assert(c.result == hp::CONFIRMED);
    assert(c.begin(hp::DISCONNECT, 45, command, sizeof(command)));
    status_body(body, ble_status::read32(command + 12), 22); body[1] = 2; body[2] = 4;
    report(c, body, 7, 50); assert(c.result == hp::REJECTED);
    assert(c.begin(hp::DISCONNECT, 55, command, sizeof(command)));
    status_body(body, ble_status::read32(command + 12), 23, hp::READY, hp::ERROR_STATE, hp::PAUSED, nullptr);
    body[32] = 2; hp::put32(body + 33, 0xFFFFFFFFU); report(c, body, 8, 60); assert(c.result == hp::FAILED && c.decoder.status.error_code == -1);
    assert(c.begin(hp::DISCONNECT, 65, command, sizeof(command))); c.tick(15065); assert(c.result == hp::TIMED_OUT);
}

static void durability_and_availability() {
    hp::Control c(77); seed(c); uint8_t command[64], body[278];
    assert(c.begin(hp::DISCONNECT, 5, command, sizeof(command)));
    const uint32_t request = ble_status::read32(command + 12);
    status_body(body, request, 20, hp::READY, hp::PAUSED_STATE, hp::PAUSED, nullptr);
    report(c, body, 3, 10); assert(c.result == hp::PENDING); // Persisted false is never success.
    status_body(body, request, 20, hp::READY | hp::PERSISTED | hp::ADVERTISING, hp::PAUSED_STATE, hp::PAUSED, nullptr);
    report(c, body, 4, 20); assert(c.result == hp::PENDING);
    status_body(body, request, 20, hp::READY | hp::PERSISTED, hp::PAUSED_STATE, hp::PAUSED, nullptr);
    body[32] = 2; hp::put32(body + 33, 9); report(c, body, 5, 30); assert(c.result == hp::FAILED);
    // Unsupported/stale state cannot start any mutating request.
    status_body(body); body[0] = 0; body[29] = hp::UNSUPPORTED; report(c, body, 6, 40);
    assert(!c.can_manage(41) && !c.begin(hp::DISCONNECT, 41, command, sizeof(command)));
    status_body(body); report(c, body, 7, 50);
    assert(!c.can_manage(5051) && !c.begin(hp::ENROLL, 5051, command, sizeof(command)));
    // A later coherent epoch recovers; a reboot clears even a terminal result.
    report(c, body, 8, 6000); assert(c.can_manage(6001));
    assert(publish(c.decoder, body, 63, 1, 1, 6010, 404)); c.tick(6011);
    assert(c.result == hp::RESTARTED && !c.selection(6011));
}

static void alias_generation_and_external_supersession() {
    hp::Control c(77); seed(c); uint8_t command[64], body[278];
    assert(c.begin(hp::ALIAS, 5, command, sizeof(command), "Work"));
    const uint32_t request = ble_status::read32(command + 12);
    status_body(body, request, 20); report(c, body, 3, 10); assert(c.result == hp::PENDING);
    const size_t count = list_body(body, 4, "Work"); assert(publish(c.decoder, body, count, 2, 4, 12)); c.tick(13);
    assert(c.result == hp::PENDING && !c.can_connect(13)); // New list cannot bless old status generation.
    status_body(body, request, 20, CONNECT_FLAGS, hp::CONNECTED, hp::AUTO, A, 4); body[1] = 3;
    report(c, body, 5, 20); assert(c.result == hp::CONFIRMED);
    assert(c.begin(hp::SELECT, 25, command, sizeof(command)));
    const uint32_t selection = ble_status::read32(command + 12);
    status_body(body, selection, 21, CONNECT_FLAGS & ~hp::READY, hp::CONNECTED, hp::AUTO, A, 4);
    report(c, body, 6, 30); assert(c.result == hp::PENDING);
    status_body(body, 99, 22); hp::put32(body + 3, 88); report(c, body, 7, 40);
    assert(c.result == hp::SUPERSEDED);
    assert(c.begin(hp::ENROLL, 45, command, sizeof(command), nullptr, 60));
    const uint32_t enroll = ble_status::read32(command + 12);
    status_body(body, enroll, 23, hp::READY | hp::PERSISTED, hp::PAUSED_STATE, hp::PAUSED, nullptr);
    report(c, body, 8, 50); assert(c.result == hp::ENROLLMENT_ENDED);
}

static void handshake_retry_migration_and_replay() {
    hp::Control c(77); uint8_t body[278], frame[64], first[32];
    status_body(body, 0, 0, hp::READY, hp::PAUSED_STATE, hp::PAUSED, nullptr, 0);
    body[1] = 0; hp::put32(body + 3, 0);
    assert(publish(c.decoder, body, 63, 1, 1, 0));
    memset(body, 0, 6); body[0] = 1; assert(publish(c.decoder, body, 6, 2, 2, 2));
    assert(!c.begin(hp::DISCONNECT, 3, frame, sizeof(frame)));
    assert(c.handshake_request(3, first, sizeof(first)) == 32);
    const uint32_t old_request = ble_status::read32(first + 12);
    assert(first[16] == hp::LIST && ble_status::read32(first + 17) == 1);
    assert(!c.handshake_request(752, frame, sizeof(frame)));
    assert(c.handshake_request(753, frame, sizeof(frame)) == 32 && !memcmp(frame, first, 32));
    assert(c.handshake_request(1503, frame, sizeof(frame)) == 32 && !memcmp(frame, first, 32));
    assert(!c.handshake_request(2253, frame, sizeof(frame)));
    c.tick(2503); assert(!c.holding() && !c.can_manage(2503));
    status_body(body, 0, 0, hp::READY, hp::PAUSED_STATE, hp::PAUSED, nullptr, 0); body[1] = 0;
    report(c, body, 3, 2600);
    assert(!c.handshake_request(3502, frame, sizeof(frame)));
    assert(c.handshake_request(3503, frame, sizeof(frame)) == 32);
    const uint32_t current_request = ble_status::read32(frame + 12);
    assert(current_request != old_request && ble_status::read32(frame + 17) == 3);
    // A delayed accepted old LIST cannot admit the current outstanding request.
    status_body(body, old_request, 0, hp::READY, hp::PAUSED_STATE, hp::PAUSED, nullptr, 0); body[1] = 4;
    report(c, body, 4, 3510); assert(!c.can_manage(3511));
    status_body(body, current_request, 0, hp::READY, hp::PAUSED_STATE, hp::PAUSED, nullptr, 0); body[1] = 4;
    report(c, body, 5, 3520);
    // The old list is still fresh/coherent. First-boot policy need not already
    // be persisted merely to discover/admit a client.
    assert(c.admitted(3521) && !(c.decoder.status.flags & hp::PERSISTED));
    assert(!c.handshake_request(3522, frame, sizeof(frame)));
    assert(c.begin(hp::DISCONNECT, 3523, frame, sizeof(frame)) == 32);
    status_body(body, ble_status::read32(frame + 12), 1, hp::READY | hp::PERSISTED, hp::PAUSED_STATE, hp::PAUSED, nullptr, 0);
    report(c, body, 6, 3530); assert(c.result == hp::CONFIRMED);
    c.invalidate_link(); assert(!c.can_manage(3531));
    status_body(body, 0, 1, hp::READY | hp::PERSISTED, hp::PAUSED_STATE, hp::PAUSED, nullptr, 0);
    assert(publish(c.decoder, body, 63, 1, 7, 3540));
    memset(body, 0, 6); body[0] = 1; assert(publish(c.decoder, body, 6, 2, 8, 3542));
    assert(c.handshake_request(3543, frame, sizeof(frame)) == 32);
    assert(ble_status::read32(frame + 12) != current_request && frame[16] == hp::LIST);
}

static void more_than_eight_panel_reboots_and_unrelated_rejections() {
    for (uint32_t boot = 0; boot < 20; ++boot) {
        hp::Control c(1000 + boot); uint8_t body[278], frame[64]; const uint32_t seq = 10 * boot + 1;
        status_body(body); assert(publish(c.decoder, body, 63, 1, seq, 0));
        const size_t count = list_body(body); assert(publish(c.decoder, body, count, 2, seq, 2));
        assert(!c.can_manage(3) && c.handshake_request(3, frame, sizeof(frame)) == 32);
        assert(frame[16] == hp::LIST && ble_status::read32(frame + 8) == 1000 + boot);
        const uint32_t handshake = ble_status::read32(frame + 12);
        status_body(body, handshake); hp::put32(body + 3, 1000 + boot); body[1] = 4;
        report(c, body, seq + 1, 4); assert(c.admitted(5));
        assert(c.begin(hp::DISCONNECT, 6, frame, sizeof(frame)) == 32);
        const uint32_t pause = ble_status::read32(frame + 12);
        status_body(body, pause, 20, 0, hp::SWITCHING, hp::PAUSED, nullptr); hp::put32(body + 3, 1000 + boot);
        report(c, body, seq + 2, 10); assert(c.result == hp::PENDING);
        // A separate reply rejecting another replayed client is not a new
        // accepted operation and cannot supersede this acknowledged request.
        status_body(body, 88, 20, 0, hp::SWITCHING, hp::PAUSED, nullptr); hp::put32(body + 3, 999); body[1] = 2; body[2] = 11;
        report(c, body, seq + 3, 20); assert(c.result == hp::PENDING && c.admitted(21));
        status_body(body, pause, 20, hp::READY | hp::PERSISTED, hp::PAUSED_STATE, hp::PAUSED, nullptr); hp::put32(body + 3, 1000 + boot);
        report(c, body, seq + 4, 30); assert(c.result == hp::CONFIRMED);
    }
}

static void admission_lost_never_retries_mutation() {
    hp::Control c(77); seed(c); uint8_t body[278], frame[64];
    assert(c.begin(hp::SELECT, 6, frame, sizeof(frame)) == 32);
    const uint32_t rejected = ble_status::read32(frame + 12);
    status_body(body, rejected, 10); body[1] = 2; body[2] = 11;
    report(c, body, 3, 10); assert(c.result == hp::REJECTED && !c.can_manage(11));
    assert(!c.handshake_request(1009, frame, sizeof(frame)));
    assert(c.handshake_request(1011, frame, sizeof(frame)) == 32 && frame[16] == hp::LIST);
    const uint32_t handshake = ble_status::read32(frame + 12);
    status_body(body, rejected, 20); report(c, body, 4, 1020);
    assert(!c.can_manage(1021)); // Late old selected-host state does not retry or complete the rejected action.
    status_body(body, handshake, 20); body[1] = 4; report(c, body, 5, 1030);
    assert(c.can_manage(1031) && !c.handshake_request(1031, frame, sizeof(frame)));
    assert(c.begin(hp::SELECT, 1032, frame, sizeof(frame)) == 32);
    const uint32_t explicit_new = ble_status::read32(frame + 12);
    status_body(body, explicit_new, 20); report(c, body, 6, 1040); assert(c.result == hp::PENDING);
    status_body(body, explicit_new, 21); report(c, body, 7, 1050); assert(c.result == hp::CONFIRMED);
}

static void local_link_loss_keeps_boot_and_sequence_history() {
    hp::Control c(77); seed(c); uint8_t body[278], frame[64], command[64];
    status_body(body); assert(publish(c.decoder, body, 63, 1, 10, 10, 202)); c.tick(12);
    const size_t count = list_body(body); assert(publish(c.decoder, body, count, 2, 11, 13, 202));
    status_body(body);
    const size_t head = fragment(frame, body, 63, 1, 0, 202, 12);
    assert(!c.decoder.accept(frame, head, 14)); // In-flight assembly must not survive a local interruption.
    c.invalidate_link();
    assert(c.decoder.session == 202 && c.decoder.status_sequence == 10);
    assert(!c.decoder.fresh_status(15) && !c.decoder.fresh_list(15));
    assert(!c.can_manage(15) && !c.selection(15) && !c.begin(hp::DISCONNECT, 15, command, sizeof(command)));
    const size_t tail = fragment(frame, body, 63, 1, 1, 202, 12);
    assert(!c.decoder.accept(frame, tail, 16));
    assert(!publish(c.decoder, body, 63, 1, 99, 17, 101)); // Previously retired controller boot stays retired.
    assert(!publish(c.decoder, body, 63, 1, 10, 19, 202)); // Cached current-boot status cannot restore freshness.
    const size_t old_list = list_body(body); assert(!publish(c.decoder, body, old_list, 2, 11, 21, 202));
    assert(!c.decoder.fresh_status(22) && !c.decoder.fresh_list(22));
    status_body(body); assert(publish(c.decoder, body, 63, 1, 13, 23, 202));
    const size_t new_list = list_body(body); assert(publish(c.decoder, body, new_list, 2, 14, 25, 202));
    assert(c.handshake_request(26, command, sizeof(command)) == 32 && command[16] == hp::LIST);
    status_body(body, ble_status::read32(command + 12)); body[1] = 4;
    assert(publish(c.decoder, body, 63, 1, 15, 27, 202)); c.tick(29);
    assert(c.can_manage(29) && c.decoder.session == 202);
    c.invalidate_link(); c.invalidate_link();
    assert(!publish(c.decoder, body, 63, 1, 100, 30, 101));
    assert(!publish(c.decoder, body, 63, 1, 15, 32, 202));
    assert(publish(c.decoder, body, 63, 1, 16, 34, 202));
}

static void native_enrollment_timeout_is_closed_not_successful() {
    hp::Control c(77); seed(c); uint8_t body[278], command[64];
    assert(c.begin(hp::ENROLL, 6, command, sizeof(command), nullptr, 60));
    const uint32_t request = ble_status::read32(command + 12);
    status_body(body, request, 20, hp::READY | hp::PERSISTED, hp::PAUSED_STATE, hp::PAUSED, nullptr);
    body[32] = 1; hp::put32(body + 33, 6); // Actual native POLICY / HP_TIMEOUT.
    report(c, body, 3, 10);
    assert(c.result == hp::ENROLLMENT_ENDED && c.result != hp::CONFIRMED);
    assert(c.decoder.status.error_domain == 1 && c.decoder.status.error_code == 6);
    assert(c.begin(hp::ENROLL, 15, command, sizeof(command), nullptr, 60));
    status_body(body, ble_status::read32(command + 12), 21, hp::READY | hp::PERSISTED | hp::ADVERTISING,
                hp::PAUSED_STATE, hp::PAUSED, nullptr);
    body[32] = 1; hp::put32(body + 33, 6); report(c, body, 4, 20);
    assert(c.result == hp::FAILED); // An advertising/incompletely closed window is not the normal terminal case.
}


static size_t remaining_host(uint8_t *body, uint32_t generation) {
    memset(body, 0, 278); body[0] = 1; hp::put32(body + 1, generation); body[5] = 1;
    memcpy(body + 6, B, 8); body[14] = hp::RESUMABLE;
    return 16;
}

static void forget_requires_paused_confirmation_and_new_inventory() {
    hp::Control c(77); seed(c); uint8_t body[278], frame[64];
    assert(!c.can_forget(6) && !c.begin(hp::FORGET, 6, frame, sizeof(frame)));
    status_body(body, 0, 10, hp::READY | hp::PERSISTED, hp::PAUSED_STATE, hp::PAUSED, A);
    report(c, body, 3, 10);
    assert(c.can_forget(12));
    const hp::Status paused = c.decoder.status;
    const uint16_t active[] = {hp::ADVERTISING, hp::CONNECTED_FLAG};
    for (uint16_t flag : active) {
        c.decoder.status.flags |= flag; assert(!c.can_forget(12)); c.decoder.status = paused;
    }
    const uint16_t required[] = {hp::READY, hp::PERSISTED};
    for (uint16_t flag : required) {
        c.decoder.status.flags &= ~flag; assert(!c.can_forget(12)); c.decoder.status = paused;
    }
    c.decoder.status.requested_mode = hp::AUTO; assert(!c.can_forget(12)); c.decoder.status = paused;
    c.decoder.status.applied_mode = hp::AUTO; assert(!c.can_forget(12)); c.decoder.status = paused;
    c.decoder.status.state = hp::WAITING; assert(!c.can_forget(12)); c.decoder.status = paused;
    c.decoder.status.error_domain = 2; assert(!c.can_forget(12)); c.decoder.status = paused;
    c.decoder.status.error_code = 9; assert(!c.can_forget(12)); c.decoder.status = paused;
    c.decoder.status.flags |= hp::ENCRYPTED | hp::BONDED | hp::HID_READY | hp::FILTER_READY;
    c.decoder.status.enrollment_remaining = 1; memcpy(c.decoder.status.connected, A, 8);
    assert(c.can_forget(12)); c.decoder.status = paused; // Cached observations add no admission gates.
    c.decoder.status.bond_generation = 4; assert(!c.can_forget(12)); c.decoder.status = paused;
    c.decoder.list.peers[0].flags |= hp::PEER_CONNECTED; assert(!c.can_forget(12));
    c.decoder.list.peers[0].flags = 0; assert(c.can_forget(12)); // A non-resumable saved host can be forgotten.
    c.clear_selection(); assert(!c.can_forget(12)); assert(c.choose(0, 12));
    assert(c.begin(hp::FORGET, 12, frame, sizeof(frame)) == 32);
    assert(c.last_opcode() == hp::FORGET && frame[16] == 5 && ble_status::read32(frame + 17) == 3);
    assert(!memcmp(frame + 21, A, 8) && !c.can_forget(12));
    assert(!c.begin(hp::FORGET, 12, frame, sizeof(frame)));
    const uint32_t request = ble_status::read32(frame + 12);
    status_body(body, request, 20, hp::READY | hp::PERSISTED, hp::PAUSED_STATE, hp::PAUSED, nullptr, 3);
    body[1] = 3; report(c, body, 4, 20); assert(c.result == hp::PENDING);
    size_t size = remaining_host(body, 3);
    assert(publish(c.decoder, body, size, 2, 5, 22)); c.tick(23);
    assert(c.result == hp::PENDING); // A missing host at the old generation is insufficient.
    status_body(body, request, 20, hp::READY | hp::PERSISTED, hp::PAUSED_STATE, hp::PAUSED, nullptr, 4);
    body[1] = 3; report(c, body, 6, 24); assert(c.result == hp::PENDING); // Old list cannot confirm new status.
    size = list_body(body, 4);
    assert(publish(c.decoder, body, size, 2, 7, 26)); c.tick(27);
    assert(c.result == hp::PENDING); // A coherent list still containing the target cannot confirm.
    status_body(body, request, 20, hp::READY | hp::PERSISTED, hp::PAUSED_STATE, hp::PAUSED, A, 4);
    body[1] = 3; report(c, body, 8, 28); assert(c.result == hp::PENDING);
    size = remaining_host(body, 4);
    assert(publish(c.decoder, body, size, 2, 9, 30)); c.tick(31);
    assert(c.result == hp::PENDING); // The observed target must also be cleared or changed.
    status_body(body, request, 10, hp::READY | hp::PERSISTED, hp::PAUSED_STATE, hp::PAUSED, nullptr, 4);
    body[1] = 3; report(c, body, 10, 32); assert(c.result == hp::PENDING);
    status_body(body, request, 20, hp::READY | hp::PERSISTED, hp::PAUSED_STATE, hp::PAUSED, nullptr, 4);
    body[1] = 1; report(c, body, 11, 34); assert(c.result == hp::PENDING);
    body[1] = 3; report(c, body, 12, 36); assert(c.result == hp::CONFIRMED);
    assert(c.last_opcode() == hp::FORGET && !c.selection(38));
    assert(!hp::command(frame, sizeof(frame), 101, 77, 1, hp::FORGET, 3));
    const uint8_t payload[] = {'x'};
    assert(!hp::command(frame, sizeof(frame), 101, 77, 1, hp::FORGET, 3, A, payload, 1));
    assert(!hp::command(frame, sizeof(frame), 101, 77, 1, static_cast<hp::Opcode>(6), 3, A));
    assert(!hp::command(frame, sizeof(frame), 101, 77, 1, static_cast<hp::Opcode>(6), 3));
    hp::Control superseded(77); seed(superseded);
    status_body(body, 0, 10, hp::READY | hp::PERSISTED, hp::PAUSED_STATE, hp::PAUSED, A);
    report(superseded, body, 3, 10);
    assert(superseded.begin(hp::FORGET, 12, frame, sizeof(frame)));
    assert(superseded.begin(hp::DISCONNECT, 13, frame, sizeof(frame)));
    assert(superseded.last_opcode() == hp::DISCONNECT);
}

int main(int argc, char **argv) {
    assert(argc >= 2);
    if (!strcmp(argv[1], "codec")) codec_and_aliases();
    else if (!strcmp(argv[1], "fragments")) reassembly_and_validation();
    else if (!strcmp(argv[1], "ordering")) ordering_sessions_and_stale();
    else if (!strcmp(argv[1], "completion")) connection_completion_races();
    else if (!strcmp(argv[1], "generations")) generations_waiting_and_reboots();
    else if (!strcmp(argv[1], "operations")) alias_enroll_errors_and_wrap();
    else if (!strcmp(argv[1], "golden-commands")) golden_commands();
    else if (!strcmp(argv[1], "golden-frames")) golden_frames(argc, argv);
    else if (!strcmp(argv[1], "durability")) durability_and_availability();
    else if (!strcmp(argv[1], "supersession")) alias_generation_and_external_supersession();
    else if (!strcmp(argv[1], "handshake")) handshake_retry_migration_and_replay();
    else if (!strcmp(argv[1], "handshake-reboots")) more_than_eight_panel_reboots_and_unrelated_rejections();
    else if (!strcmp(argv[1], "admission-lost")) admission_lost_never_retries_mutation();
    else if (!strcmp(argv[1], "link-history")) local_link_loss_keeps_boot_and_sequence_history();
    else if (!strcmp(argv[1], "enroll-timeout")) native_enrollment_timeout_is_closed_not_successful();
    else if (!strcmp(argv[1], "forget")) forget_requires_paused_confirmation_and_new_inventory();
    else return 2;
    return 0;
}

#include "ble_status.h"

#include <assert.h>
#include <string.h>
#include <array>
#include <iostream>
#include <string>

typedef std::array<uint8_t, ble_status::FRAME_SIZE> Frame;

// Fixed cross-language fixture; CRC independently obtained with crc_hqx(..., 0xffff).
static const Frame GOLDEN = {{0x42, 0x4c, 0x53, 0x31, 0x12, 0x34, 0x56, 0x78,
    0x9a, 0xbc, 0x00, 0x0b, 0x01, 0x02, 0x03, 0x04, 0x00, 0x21, 0x1d}};

// A nibble-table reference, independent of the decoder's bitwise CRC loop.
static void seal(Frame &frame) {
    static const uint16_t table[] = {0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50a5,
        0x60c6, 0x70e7, 0x8108, 0x9129, 0xa14a, 0xb16b, 0xc18c, 0xd1ad, 0xe1ce, 0xf1ef};
    uint16_t crc = 0xffff;
    for (size_t i = 0; i < 17; ++i) {
        crc = static_cast<uint16_t>((crc << 4) ^ table[(crc >> 12) ^ (frame[i] >> 4)]);
        crc = static_cast<uint16_t>((crc << 4) ^ table[(crc >> 12) ^ (frame[i] & 15)]);
    }
    frame[17] = static_cast<uint8_t>(crc >> 8);
    frame[18] = static_cast<uint8_t>(crc);
}

static Frame packet(uint32_t session, uint16_t seq, uint8_t mode = 0,
                    uint8_t flags = 0x0b, uint8_t error = 0) {
    Frame result = GOLDEN;
    for (unsigned i = 0; i < 4; ++i) result[4 + i] = static_cast<uint8_t>(session >> (24 - i * 8));
    result[8] = static_cast<uint8_t>(seq >> 8);
    result[9] = static_cast<uint8_t>(seq);
    result[10] = mode;
    result[11] = flags;
    result[16] = error;
    seal(result);
    return result;
}

static bool send(ble_status::Decoder &decoder, const Frame &frame, uint32_t now = 0) {
    return decoder.accept(frame.data(), frame.size(), now);
}

static void golden() {
    assert(ble_status::crc16(reinterpret_cast<const uint8_t *>("123456789"), 9) == 0x29b1);
    Frame reference = GOLDEN;
    seal(reference);
    assert(reference == GOLDEN);
    ble_status::Decoder decoder;
    assert(!decoder.have_status() && !decoder.fresh(0) && !decoder.confirmed_paused(0));
    assert(send(decoder, GOLDEN, 10));
    assert(decoder.have_status() && decoder.fresh(10));
    assert(decoder.state.session == 0x12345678 && decoder.state.sequence == 0x9abc);
    assert(decoder.state.mode == ble_status::MODE_ENABLED && decoder.state.flags == 0x0b);
    assert(decoder.state.request_seq == 0x01020304 && decoder.state.error == 0);
    assert(!decoder.confirmed_paused(10));
}

static void malformed() {
    ble_status::Decoder decoder;
    assert(send(decoder, GOLDEN));
    assert(!decoder.accept(nullptr, GOLDEN.size(), 100));
    for (size_t len = 0; len < GOLDEN.size(); ++len) assert(!decoder.accept(GOLDEN.data(), len, 100));
    uint8_t oversized[20] = {};
    memcpy(oversized, GOLDEN.data(), GOLDEN.size());
    assert(!decoder.accept(oversized, sizeof(oversized), 100));
    for (size_t i = 0; i < GOLDEN.size(); ++i) {
        Frame corrupted = GOLDEN;
        corrupted[i] ^= 1;
        assert(!send(decoder, corrupted, 100));
    }
    Frame wrong_magic = GOLDEN;
    wrong_magic[3] = '2';
    seal(wrong_magic);
    assert(!send(decoder, wrong_magic, 100));
    assert(decoder.state.session == 0x12345678 && decoder.state.sequence == 0x9abc);
    assert(!decoder.fresh(3000));
}

static void validation() {
    for (unsigned mode = 0; mode < 4; ++mode) {
        for (unsigned flags = 0; flags < 16; ++flags) {
            for (unsigned error = 0; error < 8; ++error) {
                ble_status::Decoder decoder;
                const Frame frame = packet(1, 1, mode, flags, error);
                bool expected = false;
                if (mode == ble_status::MODE_ENABLED) expected = (flags & 1) && error == 0;
                if (mode == ble_status::MODE_PAUSING) expected = !(flags & 1) && error == 0;
                if (mode == ble_status::MODE_PAUSED) expected = flags == 2 && error == 0;
                if (mode == ble_status::MODE_ERROR) expected = error != 0;
                assert(send(decoder, frame) == expected);
                assert(decoder.confirmed_paused(0) == (expected && mode == ble_status::MODE_PAUSED));
            }
        }
    }
    for (unsigned value = 0; value < 256; ++value) {
        ble_status::Decoder decoder;
        if (value > 3) assert(!send(decoder, packet(1, 1, value)));
        if (value > 15) assert(!send(decoder, packet(1, 1, 0, value)));
        if (value > 7) assert(!send(decoder, packet(1, 1, 0, 0x0b, value)));
    }
    ble_status::Decoder decoder;
    assert(send(decoder, packet(1, 1, ble_status::MODE_ERROR, 0x0f, 7)));
    assert(decoder.state.flags == 0x0f && decoder.state.error == 7);
    assert(!decoder.confirmed_paused(0));
}

static void ordering() {
    ble_status::Decoder decoder;
    assert(send(decoder, packet(1, 0xfffe), 0));
    assert(send(decoder, packet(1, 0xffff), 1));
    assert(send(decoder, packet(1, 0), 2));
    assert(!send(decoder, packet(1, 0), 2000));
    assert(!send(decoder, packet(1, 0xffff), 2001));
    assert(!send(decoder, packet(1, 0x8000), 2002));
    assert(decoder.fresh(3001) && !decoder.fresh(3002));
    assert(!send(decoder, packet(1, 0xffff), 4000));
    assert(!decoder.fresh(4000));
    assert(send(decoder, packet(1, 0x7fff), 4001));
    assert(decoder.fresh(4001));
    assert(!send(decoder, packet(1, 0x7ffe), 4002));
}

static void sessions() {
    ble_status::Decoder decoder;
    assert(send(decoder, packet(100, 500)));
    // Malformed incoming boot must not retire the current valid session.
    Frame invalid = packet(101, 0);
    invalid[17] ^= 1;
    assert(!send(decoder, invalid, 1));
    assert(send(decoder, packet(100, 501), 2));
    for (uint32_t session = 101; session <= 108; ++session) {
        assert(send(decoder, packet(session, 0), session));
        for (uint32_t retired = 100; retired < session; ++retired) {
            assert(!send(decoder, packet(retired, 1000), session + 1));
        }
    }
    assert(!send(decoder, packet(107, 5000), 10000));
    assert(!decoder.fresh(10000));
    assert(send(decoder, packet(109, 0), 10001));
    assert(decoder.state.session == 109 && decoder.state.sequence == 0);
    decoder.reset();
    assert(!decoder.have_status() && !decoder.fresh(0));
    assert(decoder.state.session == 0 && decoder.state.request_seq == 0);
    assert(send(decoder, packet(100, 0), 0));
}

static void expiry() {
    ble_status::Decoder decoder;
    const Frame paused = packet(1, 1, ble_status::MODE_PAUSED, ble_status::FLAG_READY);
    assert(send(decoder, paused, 100));
    assert(decoder.confirmed_paused(3099));
    assert(!send(decoder, paused, 3099));
    assert(!decoder.confirmed_paused(3100));
    assert(!decoder.fresh(100));  // Observed expiry stays latched across millis wrap.
    assert(send(decoder, packet(1, 2, ble_status::MODE_PAUSED, ble_status::FLAG_READY), 3200));
    assert(decoder.confirmed_paused(3200));
    decoder.reset();
    const uint32_t start = 0xffffff00U;
    assert(send(decoder, paused, start));
    assert(decoder.confirmed_paused(start + 2999));
    assert(!decoder.confirmed_paused(start + 3000));
}

int main(int argc, char **argv) {
    assert(argc == 2);
    const std::string scenario = argv[1];
    if (scenario == "golden") golden();
    else if (scenario == "malformed") malformed();
    else if (scenario == "validation") validation();
    else if (scenario == "ordering") ordering();
    else if (scenario == "sessions") sessions();
    else if (scenario == "expiry") expiry();
    else { std::cerr << "unknown scenario\n"; return 2; }
    return 0;
}

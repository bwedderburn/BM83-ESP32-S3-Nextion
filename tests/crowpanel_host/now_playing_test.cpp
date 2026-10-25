// Line-driven host probe for Python-encoded protocol/clock scenarios.
#include "now_playing.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace {
int hex_digit(char value) {
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    return -1;
}

void print_hex(const char *value) {
    if (!*value) { std::printf("-"); return; }
    for (size_t i = 0; value[i]; ++i) std::printf("%02x", static_cast<unsigned char>(value[i]));
}
}  // namespace

int main() {
    now_playing::NowPlayingModel model;
    char line[1024];
    while (std::fgets(line, sizeof(line), stdin)) {
        if (line[0] == 'R') {
            model.reset();
            std::puts("R");
            continue;
        }
        char *end = nullptr;
        const uint32_t now = static_cast<uint32_t>(std::strtoull(line + 2, &end, 10));
        if (line[0] == 'P') {
            const now_playing::NowPlayingState &state = model.state;
            std::printf("P %u %u %u %u %u %u %u %u %u %u ",
                        model.fresh(now), model.have_snapshot(), model.position(now), state.play_status,
                        state.eq_index, state.duration_ms, state.position_ms, state.position_age_ms,
                        state.power_on | (state.connected << 1) | (state.aux << 2),
                        static_cast<unsigned>(now_playing::MAX_TEXT_BYTES));
            print_hex(state.title); std::putchar(' ');
            print_hex(state.artist); std::putchar(' ');
            print_hex(state.album); std::putchar('\n');
            continue;
        }
        if (line[0] != 'F' || !end || *end != ' ') return 2;
        ++end;
        const size_t hex_len = std::strcspn(end, "\r\n");
        if (hex_len % 2 || hex_len > 2 * now_playing::FRAME_MAX) return 2;
        uint8_t bytes[now_playing::FRAME_MAX];
        for (size_t i = 0; i < hex_len / 2; ++i) {
            const int a = hex_digit(end[i * 2]), b = hex_digit(end[i * 2 + 1]);
            if (a < 0 || b < 0) return 2;
            bytes[i] = static_cast<uint8_t>((a << 4) | b);
        }
        std::printf("A %u\n", model.accept(bytes, hex_len / 2, now));
    }
    return 0;
}

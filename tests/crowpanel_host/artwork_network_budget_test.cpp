#include "artwork_network_budget.h"

#include <assert.h>
#include <stdint.h>

using artwork_network_budget::handshake_seconds;

int main() {
    // A fresh job gets a larger handshake allowance without extending its
    // total deadline, even when a caller requests an excessive allowance.
    assert(handshake_seconds(1000, 1000) == 12);
    assert(handshake_seconds(1000, 1000, 45000, 1000) == 12);
    assert(handshake_seconds(1000, 1000, 45000, 4) == 4);
    assert(handshake_seconds(1000, 1000, 45000, 0) == 0);

    assert(handshake_seconds(1000, 34000) == 12);
    assert(handshake_seconds(1000, 34001) == 11);
    assert(handshake_seconds(1000, 42000) == 4);
    assert(handshake_seconds(1000, 45000) == 1);
    assert(handshake_seconds(1000, 45001) == 0);
    assert(handshake_seconds(1000, 46000) == 0);
    assert(handshake_seconds(1000, 100000) == 0);
    assert(handshake_seconds(1000, 1000, 0) == 0);
    assert(handshake_seconds(1000, 1000, 999) == 0);
    assert(handshake_seconds(1000, 1000, 1000) == 1);

    // Millis wrapping must retain the actual short elapsed interval.
    const uint32_t start = UINT32_MAX - 1999;
    assert(handshake_seconds(start, 1000) == 12);  // 3000 ms elapsed.
    assert(handshake_seconds(start, 41000) == 2);  // 43000 ms elapsed.
    assert(handshake_seconds(start, 42001) == 0);  // Less than one second left.
    assert(handshake_seconds(start, 43000) == 0);  // Exactly expired.
    assert(handshake_seconds(start, 43001) == 0);

    // For every sampled point in the job, seconds never exceed the available
    // whole-second budget and never exceed the explicit handshake ceiling.
    for (uint32_t elapsed = 0; elapsed <= 46000; elapsed += 137) {
        const unsigned seconds = handshake_seconds(start, start + elapsed);
        assert(seconds <= 12);
        if (elapsed >= 45000) assert(seconds == 0);
        else {
            const uint32_t remaining = 45000 - elapsed;
            assert(seconds * 1000 <= remaining);
            assert((seconds > 0) == (remaining >= 1000));
        }
    }
    return 0;
}

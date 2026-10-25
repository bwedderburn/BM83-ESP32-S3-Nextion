// Keep a verified TLS handshake inside the artwork job's remaining deadline.
// Millisecond subtraction is wrap-safe for these short, bounded jobs.
#pragma once

#include <stdint.h>

namespace artwork_network_budget {

inline unsigned handshake_seconds(uint32_t started_ms, uint32_t now_ms,
                                  uint32_t job_ms = 45000, unsigned max_seconds = 12) {
    const uint32_t elapsed = static_cast<uint32_t>(now_ms - started_ms);
    if (elapsed >= job_ms) return 0;
    const uint32_t remaining_seconds = (job_ms - elapsed) / 1000;
    const unsigned ceiling = max_seconds < 12 ? max_seconds : 12;
    return remaining_seconds < ceiling ? static_cast<unsigned>(remaining_seconds) : ceiling;
}

}  // namespace artwork_network_budget

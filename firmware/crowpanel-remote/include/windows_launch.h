#pragma once

#include <stdint.h>

namespace windows_launch {

void begin();
bool provision(const char *hex_key);
bool configured();
void tick(uint32_t now, bool network_ready);
bool available(uint32_t now);
bool request(uint32_t now);
const char *status(uint32_t now);

}  // namespace windows_launch

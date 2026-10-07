// Host stand-in for the Arduino core: only what
// firmware/crowpanel-remote/src/battery.cpp uses. battery_test.cpp drives
// the clock and the ADC.
#pragma once
#include <stdint.h>

#define INPUT 0x01

extern uint32_t host_now_ms;   // what millis() returns
extern int      host_adc_raw;  // what analogRead() returns

inline uint32_t millis() { return host_now_ms; }
inline void delay(uint32_t ms) { host_now_ms += ms; }
inline void pinMode(int, int) {}
inline void analogReadResolution(int) {}
inline int analogRead(int) { return host_adc_raw; }

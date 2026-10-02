// ESP-NOW link to the BM83 audio unit — Stage 2: remote -> unit tokens.
//
// PROTOCOL (shared with the Stage 3 CircuitPython receiver; keep in sync
// with README.md):
//   token frame  (remote -> audio unit):  "BMR1:<seq>:<token>"
//   state frame  (audio unit -> remote):  "BMS1:<seq>:<key>=<val>[...]"
// ASCII, <= 64 bytes, no NUL on the wire. <seq> is a decimal uint32 the
// receiver uses to drop duplicates (ESP-NOW MAC-layer retries can deliver
// a frame twice). <token> is EXACTLY the Nextion vocabulary (BT_PLAY,
// BT_VOLUP_P, ...) so the audio unit's main.py feeds one dispatch path.
//
// Both ends sit on WiFi channel ESPNOW_CHANNEL in unassociated STA mode.
// The peer MAC in espnow_link.cpp is the audio unit's base MAC (read
// 2026-10-01); ESP-NOW uses the STA MAC, which on ESP32-S3 should equal
// the base MAC — CONFIRM during Stage 3 bring-up before trusting acks.

#pragma once
#include <stddef.h>
#include <stdint.h>

#define ESPNOW_CHANNEL 1

typedef void (*espnow_log_fn)(const char *fmt, ...);

// Bring WiFi up in unassociated STA mode on ESPNOW_CHANNEL and register
// the audio-unit peer. Returns false (and logs why) if any step fails;
// the UI keeps working either way — sends just report "off".
bool espnow_link_init(espnow_log_fn logf);

// Fire-and-forget a token frame at the audio unit. Safe before init or
// after a failed init (drops silently, status stays "off").
void espnow_send_token(const char *token);

// Last completed send: "ok" (acked), "no-ack" (peer silent — expected
// until the Stage 3 receiver exists), "off" (not initialised / failed).
const char *espnow_link_status_str();

// Lifetime counters for the heartbeat line.
void espnow_link_heartbeat(uint32_t *sent, uint32_t *acked);

// Drain one received frame into out (NUL-terminated); true if one was
// pending. Stage 3 state frames will arrive here.
bool espnow_link_poll(char *out, size_t out_len);

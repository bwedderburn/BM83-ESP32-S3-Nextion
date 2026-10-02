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
// Both ends run unassociated STA mode and must share a WiFi channel. The
// unit's channel is not fixed (an unassociated CircuitPython radio is not
// reliably on 1), so the remote DISCOVERS it at boot by probing ch1-13 for
// a hardware ACK, and rescans after repeated no-acks. ESPNOW_CHANNEL is
// only the home channel used while the unit is not found.
// The peer MAC in espnow_link.cpp is the audio unit's WiFi STA MAC, read
// on the unit itself (CircuitPython wifi.radio.mac_address, 2026-10-01).
// The "MAC:" line in the unit's boot_out.txt is a DIFFERENT value — never
// copy the peer address from there.

#pragma once
#include <stddef.h>
#include <stdint.h>

#define ESPNOW_CHANNEL 1

// Largest frame on the wire (protocol limit above). Local buffers are one
// byte larger for the NUL terminator; anything longer is rejected, never
// truncated (PR #151 review).
#define ESPNOW_FRAME_MAX 64

typedef void (*espnow_log_fn)(const char *fmt, ...);

// Bring WiFi up in unassociated STA mode, register the audio-unit peer and
// discover its channel (blocks up to ~2 s at boot). Returns false (and logs
// why) if any step fails; the UI keeps working either way — sends just
// report "off". Not finding the unit is NOT a failure: sends report no-ack
// and a later rescan picks the unit up once it is on.
bool espnow_link_init(espnow_log_fn logf);

// Send a token frame and wait (bounded: up to 4 attempts, ~250 ms worst
// case) for the unit's radio to ACK it. Retries reuse the same <seq>, so
// the receiver drops any repeat that did land. Safe before init or after a
// failed init (drops silently, status stays "off").
void espnow_send_token(const char *token);

// Delivery status of the last token: "ok" (an attempt was ACKed),
// "no-ack" (every attempt failed), "off" (not initialised / failed).
const char *espnow_link_status_str();

// Lifetime counters for the heartbeat line.
void espnow_link_heartbeat(uint32_t *sent, uint32_t *acked);

// Channel the audio unit was found on; 0 while it has not been found.
uint8_t espnow_link_channel();

// Re-run channel discovery now (blocks ~0.3 s, up to ~2.5 s with the unit
// absent). Used after the remote wakes from light sleep, so the first tap
// does not land on a channel the unit has left. No-op before init.
void espnow_link_rescan();

// Extra send attempts beyond the first, lifetime (link-quality signal).
uint32_t espnow_link_retries();

// Drain one received frame into out (NUL-terminated); true if one was
// pending. Stage 3 state frames will arrive here.
bool espnow_link_poll(char *out, size_t out_len);

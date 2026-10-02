// ESP-NOW sender for the BM83 remote — see espnow_link.h for the protocol.
//
// Arduino-ESP32 2.x (espressif32 6.x) callback signatures. Callbacks run
// in the WiFi task, not an ISR. Sends are synchronous: the caller waits
// (bounded) for the send callback, so retries and counters live in task
// context and the callback only signals completion. A FreeRTOS spinlock
// guards the one-slot RX mailbox.

#include "espnow_link.h"

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#include <stdio.h>
#include <string.h>

namespace {

// Audio unit's WiFi STA MAC: the address ESP-NOW unicasts to and acks
// from. Read on the unit (wifi.radio.mac_address) 2026-10-01 and printed
// by its "[REMOTE] ESP-NOW receiver up: own-sta=..." boot line. The "MAC:"
// line in its boot_out.txt (80:92:CB:3F:90:CF) is NOT this address.
const uint8_t PEER_MAC[6] = {0xDC, 0xB4, 0xD9, 0x0C, 0x6E, 0x8C};

// Channel discovery. The unit's radio sits on whatever channel its WiFi
// stack picked (an unassociated CircuitPython STA is not reliably on 1),
// and both ends must share one. A unicast frame is ACKed by the peer's WiFi
// MAC in hardware — no receiver code involved — so probing finds the unit.
// At bench range a probe on a NEIGHBOURING channel is sometimes ACKed too,
// so every channel is scored and the centre of the best-scoring run wins
// (first-ACK-wins locked onto ch1 when the unit was on ch2, 2026-10-01).
// The probe payload is not a token frame; the receiver ignores it.
const char     PROBE_FRAME[]      = "BMP1";
const uint8_t  PROBES_PER_CH      = 3;
const uint32_t ACK_WAIT_MS        = 60;     // send-callback deadline
// Token delivery. With BLE active on the unit, coexistence can swallow a
// frame's whole MAC-retry burst; retry at this layer until ACKed. The
// receiver drops repeats by <seq>, so a retry can never double-fire.
const uint8_t  TOKEN_TRIES        = 4;
const uint32_t TOKEN_RETRY_GAP_MS = 15;
const uint8_t  RESCAN_AFTER_FAILS = 2;      // tokens undelivered in a row
const uint32_t RESCAN_MIN_GAP_MS  = 10000;  // never rescan more often

espnow_log_fn g_log         = nullptr;
bool          g_ready       = false;
uint32_t      g_sent        = 0;  // tokens attempted
uint32_t      g_acked       = 0;  // tokens delivered (some attempt ACKed)
uint32_t      g_retries     = 0;  // extra attempts beyond the first
uint8_t       g_last_status = 2;  // 0 = acked, 1 = no-ack, 2 = off
uint32_t      g_seq         = 0;
uint8_t       g_channel     = 0;  // 0 = peer not found yet
uint8_t       g_fail_streak = 0;
uint32_t      g_last_scan_ms = 0;

volatile bool g_waiting   = false;
volatile bool g_wait_ack  = false;

portMUX_TYPE  g_rx_mux       = portMUX_INITIALIZER_UNLOCKED;
char          g_rx_frame[ESPNOW_FRAME_MAX + 1] = {0};
volatile bool g_rx_pending   = false;

void on_sent(const uint8_t * /*mac*/, esp_now_send_status_t status) {
    g_wait_ack = (status == ESP_NOW_SEND_SUCCESS);
    g_waiting  = false;
}

void on_recv(const uint8_t * /*mac*/, const uint8_t *data, int len) {
    if (len <= 0 || len > ESPNOW_FRAME_MAX) return;  // reject, never truncate
    portENTER_CRITICAL(&g_rx_mux);
    memcpy(g_rx_frame, data, len);
    g_rx_frame[len] = '\0';
    g_rx_pending  = true;  // one-slot mailbox: newest frame wins
    portEXIT_CRITICAL(&g_rx_mux);
}

// One unicast attempt; true if the peer's radio ACKed it in time.
bool send_once(const uint8_t *data, size_t len) {
    g_wait_ack = false;
    g_waiting  = true;
    if (esp_now_send(PEER_MAC, data, len) != ESP_OK) {
        g_waiting = false;
        return false;
    }
    const uint32_t t0 = millis();
    while (g_waiting && (millis() - t0) < ACK_WAIT_MS) delay(1);
    g_waiting = false;
    return g_wait_ack;
}

uint8_t score_channel(uint8_t ch) {
    if (esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE) != ESP_OK) return 0;
    uint8_t acks = 0;
    for (uint8_t i = 0; i < PROBES_PER_CH; i++) {
        if (send_once((const uint8_t *)PROBE_FRAME, sizeof(PROBE_FRAME) - 1)) acks++;
    }
    return acks;
}

// Blocking: ~13 x 3 probes, ~0.3 s with the unit present, up to ~2.5 s
// when it is absent. Called at boot and, rate-limited, after repeated
// undelivered tokens in case the unit's channel moved.
void discover_channel() {
    g_last_scan_ms = millis();
    uint8_t score[14] = {0};
    uint8_t best = 0;
    for (uint8_t ch = 1; ch <= 13; ch++) {
        score[ch] = score_channel(ch);
        if (score[ch] > best) best = score[ch];
    }
    if (best == 0) {
        g_channel = 0;
        if (esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE) != ESP_OK &&
            g_log) {
            g_log("[espnow] could not return to home ch%d", ESPNOW_CHANNEL);
        }
        if (g_log) g_log("[espnow] audio unit not found on ch1-13 (off or out of range?)");
        return;
    }
    // Centre of the longest run of best-scoring channels.
    uint8_t run_start = 0, run_len = 0, best_start = 0, best_len = 0;
    for (uint8_t ch = 1; ch <= 14; ch++) {
        if (ch <= 13 && score[ch] == best) {
            if (run_len == 0) run_start = ch;
            run_len++;
        } else if (run_len > 0) {
            if (run_len > best_len) { best_len = run_len; best_start = run_start; }
            run_len = 0;
        }
    }
    const uint8_t chosen = best_start + (best_len - 1) / 2;
    if (esp_wifi_set_channel(chosen, WIFI_SECOND_CHAN_NONE) != ESP_OK) {
        // Not actually on the unit's channel: report "not found" rather than
        // claim a channel we cannot use; the next rescan retries.
        g_channel = 0;
        if (g_log) g_log("[espnow] found the unit on ch%u but could not switch to it",
                         (unsigned)chosen);
        return;
    }
    g_channel = chosen;
    g_fail_streak = 0;
    if (g_log) {
        char map[14];
        for (uint8_t ch = 1; ch <= 13; ch++) map[ch - 1] = (char)('0' + score[ch]);
        map[13] = '\0';
        g_log("[espnow] audio unit found on ch%u (acks per ch1-13: %s)",
              (unsigned)g_channel, map);
    }
}

}  // namespace

bool espnow_link_init(espnow_log_fn logf) {
    g_log = logf;

    WiFi.mode(WIFI_STA);
    WiFi.disconnect();  // unassociated STA: radio on, no AP
    // Modem power-save makes an idle unassociated STA miss ESP-NOW frames;
    // the remote must hear state frames, and it runs on USB. Not fatal if
    // refused: token TX does not depend on it, only future state-frame RX,
    // so log it and keep the link up (PR #151 review).
    if (esp_wifi_set_ps(WIFI_PS_NONE) != ESP_OK && g_log) {
        g_log("[espnow] power-save-off refused; state-frame RX may be unreliable");
    }

    esp_err_t err = esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
    if (err != ESP_OK) {
        if (g_log) g_log("[espnow] set_channel failed: %d", (int)err);
        return false;
    }
    err = esp_now_init();
    if (err != ESP_OK) {
        if (g_log) g_log("[espnow] init failed: %d", (int)err);
        return false;
    }
    esp_now_register_send_cb(on_sent);
    esp_now_register_recv_cb(on_recv);

    esp_now_peer_info_t peer = {};
    memcpy(peer.peer_addr, PEER_MAC, 6);
    peer.channel = 0;  // follow the radio's current channel (set by discovery)
    peer.ifidx   = WIFI_IF_STA;
    peer.encrypt = false;
    err = esp_now_add_peer(&peer);
    if (err != ESP_OK) {
        if (g_log) g_log("[espnow] add_peer failed: %d", (int)err);
        return false;
    }

    g_ready       = true;
    g_last_status = 1;  // nothing acked yet
    if (g_log) {
        g_log("[espnow] up: peer=%02x:%02x:%02x:%02x:%02x:%02x own-sta=%s",
              PEER_MAC[0], PEER_MAC[1], PEER_MAC[2],
              PEER_MAC[3], PEER_MAC[4], PEER_MAC[5],
              WiFi.macAddress().c_str());
    }
    discover_channel();
    return true;
}

void espnow_send_token(const char *token) {
    if (!g_ready || token == nullptr) return;
    // Undelivered tokens in a row: the unit may have rebooted onto another
    // channel (or been off at boot). Rescan before sending this one.
    if (g_fail_streak >= RESCAN_AFTER_FAILS &&
        (millis() - g_last_scan_ms) >= RESCAN_MIN_GAP_MS) {
        if (g_log) g_log("[espnow] %u tokens undelivered -> rescanning channels",
                         (unsigned)g_fail_streak);
        discover_channel();
    }
    char frame[ESPNOW_FRAME_MAX + 1];
    const int n = snprintf(frame, sizeof(frame), "BMR1:%lu:%s",
                           (unsigned long)++g_seq, token);
    if (n <= 0 || n > ESPNOW_FRAME_MAX) return;  // over the protocol limit: drop
    g_sent++;
    for (uint8_t attempt = 0; attempt < TOKEN_TRIES; attempt++) {
        if (attempt > 0) {
            g_retries++;
            delay(TOKEN_RETRY_GAP_MS);
        }
        if (send_once((const uint8_t *)frame, (size_t)n)) {
            g_acked++;
            g_last_status = 0;
            g_fail_streak = 0;
            return;
        }
    }
    g_last_status = 1;
    if (g_fail_streak < 255) g_fail_streak++;
}

const char *espnow_link_status_str() {
    switch (g_last_status) {
        case 0:  return "ok";
        case 1:  return "no-ack";
        default: return "off";
    }
}

void espnow_link_heartbeat(uint32_t *sent, uint32_t *acked) {
    if (sent)  *sent  = g_sent;
    if (acked) *acked = g_acked;
}

uint8_t espnow_link_channel() { return g_channel; }

uint32_t espnow_link_retries() { return g_retries; }

bool espnow_link_poll(char *out, size_t out_len) {
    if (!g_rx_pending || out == nullptr || out_len == 0) return false;
    portENTER_CRITICAL(&g_rx_mux);
    strncpy(out, g_rx_frame, out_len - 1);
    out[out_len - 1] = '\0';
    g_rx_pending = false;
    portEXIT_CRITICAL(&g_rx_mux);
    return true;
}

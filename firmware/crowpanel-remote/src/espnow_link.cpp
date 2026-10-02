// ESP-NOW sender for the BM83 remote — see espnow_link.h for the protocol.
//
// Arduino-ESP32 2.x (espressif32 6.x) callback signatures. Callbacks run
// in the WiFi task, not an ISR: a FreeRTOS spinlock guards the one-slot
// RX mailbox, and the 32-bit counters are plain volatile (aligned 32-bit
// stores are atomic on Xtensa).

#include "espnow_link.h"

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#include <stdio.h>
#include <string.h>

namespace {

// Audio unit's MAC (base MAC read 2026-10-01; the STA MAC ESP-NOW acks
// from is expected to be identical on ESP32-S3 — confirm in Stage 3).
const uint8_t PEER_MAC[6] = {0x80, 0x92, 0xCB, 0x3F, 0x90, 0xCF};

espnow_log_fn     g_log         = nullptr;
bool              g_ready       = false;
volatile uint32_t g_sent        = 0;
volatile uint32_t g_acked       = 0;
volatile uint8_t  g_last_status = 2;  // 0 = acked, 1 = no-ack, 2 = off
uint32_t          g_seq         = 0;

portMUX_TYPE  g_rx_mux       = portMUX_INITIALIZER_UNLOCKED;
char          g_rx_frame[64] = {0};
volatile bool g_rx_pending   = false;

void on_sent(const uint8_t * /*mac*/, esp_now_send_status_t status) {
    if (status == ESP_NOW_SEND_SUCCESS) {
        g_acked       = g_acked + 1;
        g_last_status = 0;
    } else {
        g_last_status = 1;
    }
}

void on_recv(const uint8_t * /*mac*/, const uint8_t *data, int len) {
    if (len <= 0) return;
    portENTER_CRITICAL(&g_rx_mux);
    const int cap = (int)sizeof(g_rx_frame) - 1;
    const int n   = (len < cap) ? len : cap;
    memcpy(g_rx_frame, data, n);
    g_rx_frame[n] = '\0';
    g_rx_pending  = true;  // one-slot mailbox: newest frame wins
    portEXIT_CRITICAL(&g_rx_mux);
}

}  // namespace

bool espnow_link_init(espnow_log_fn logf) {
    g_log = logf;

    WiFi.mode(WIFI_STA);
    WiFi.disconnect();  // unassociated STA: radio on, no AP
    // Modem power-save makes an idle unassociated STA miss ESP-NOW frames;
    // the remote must hear Stage 3 state frames, and it runs on USB.
    esp_wifi_set_ps(WIFI_PS_NONE);

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
    peer.channel = ESPNOW_CHANNEL;
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
        g_log("[espnow] up: ch%d peer=%02x:%02x:%02x:%02x:%02x:%02x own-sta=%s",
              ESPNOW_CHANNEL, PEER_MAC[0], PEER_MAC[1], PEER_MAC[2],
              PEER_MAC[3], PEER_MAC[4], PEER_MAC[5],
              WiFi.macAddress().c_str());
    }
    return true;
}

void espnow_send_token(const char *token) {
    if (!g_ready || token == nullptr) return;
    char frame[64];
    const int n = snprintf(frame, sizeof(frame), "BMR1:%lu:%s",
                           (unsigned long)++g_seq, token);
    if (n <= 0 || n >= (int)sizeof(frame)) return;  // oversized: drop
    g_sent = g_sent + 1;
    esp_now_send(PEER_MAC, (const uint8_t *)frame, (size_t)n);
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

bool espnow_link_poll(char *out, size_t out_len) {
    if (!g_rx_pending || out == nullptr || out_len == 0) return false;
    portENTER_CRITICAL(&g_rx_mux);
    strncpy(out, g_rx_frame, out_len - 1);
    out[out_len - 1] = '\0';
    g_rx_pending = false;
    portEXIT_CRITICAL(&g_rx_mux);
    return true;
}

// On-panel Wi-Fi enrollment, NVS and one-time physical USB
// transfer to the audio controller. No passwords are sent through ESP-NOW.
#include "network_setup.h"

#include <Arduino.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <driver/uart.h>
#include <lvgl.h>
#include <mbedtls/base64.h>
#include <atomic>

namespace {

constexpr uint32_t EXPORT_WINDOW_MS = 300000;
constexpr uint32_t CONNECT_TIMEOUT_MS = 20000;
constexpr uint32_t RETRY_WAIT_MS = 1500;
constexpr uint32_t PEER_MISSING_MS = 10000;
constexpr uint32_t TRIAL_TIMEOUT_MS = 60000;
constexpr size_t MAX_NETWORKS = 20;
constexpr size_t MAX_PROFILE_JSON = 512;

struct Profile {
    String ssid, password;
    uint8_t bssid[6] = {};
    uint8_t channel = 0;
    bool valid = false;
};

struct AccessPoint {
    String ssid;
    uint8_t bssid[6] = {};
    uint8_t channel = 0;
    int32_t rssi = 0;
    bool open = false, enterprise = false;
};

Preferences g_preferences;
bool g_nvs_ready = false, g_started = false;
Profile g_active, g_pending, g_target;
AccessPoint g_networks[MAX_NETWORKS];
size_t g_network_count = 0;
int g_selected = -1;
bool g_scanning = false, g_scan_was_connected = false;
uint8_t g_scan_home_channel = 1, g_join_home_channel = 1;
bool g_connecting = false, g_applying = false, g_retry_pending = false;
uint32_t g_connect_started = 0, g_retry_at = 0;
bool g_network_enabled = false, g_peer_known = false, g_peer_fresh = false;
bool g_suspended = false, g_resume_network = false;
bool g_rescan_requested = false;
uint32_t g_peer_missing_since = 0;
void (*g_retry_callback)() = nullptr;
bool (*g_export_prepare)() = nullptr;
void (*g_export_resume)() = nullptr;
bool g_export_claimed = false, g_export_secret_tx = false;
bool g_export_uart_draining = false, g_export_release_pending = false;
std::atomic<uint32_t> g_ip_generation(0);
uint32_t g_join_ip_generation = 0;
bool g_export_open = false;
uint32_t g_saved_at = 0;
char g_export_nonce[65] = {}, g_apply_nonce[65] = {};
char g_commit_nonce[65] = {}, g_abort_nonce[65] = {};
char g_apply_result[32] = {};
bool g_completion_pending = false;
bool g_trial = false, g_trial_connected = false;
uint32_t g_trial_started = 0;

network_setup_protocol::LineParser g_parser;
char g_tx[1024] = {};
size_t g_tx_size = 0, g_tx_offset = 0;
lv_obj_t *g_modal = nullptr, *g_list = nullptr, *g_selected_label = nullptr;
lv_obj_t *g_password = nullptr, *g_keyboard = nullptr, *g_status = nullptr;
char g_status_text[160] = "Wi-Fi is not configured.";

void set_status(const char *text) {
    snprintf(g_status_text, sizeof(g_status_text), "%s", text);
    if (g_status) lv_label_set_text(g_status, g_status_text);
}

void bssid_string(const uint8_t *bytes, char out[18]) {
    snprintf(out, 18, "%02X:%02X:%02X:%02X:%02X:%02X", bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], bytes[5]);
}

int hex_digit(char value) {
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    if (value >= 'A' && value <= 'F') return value - 'A' + 10;
    return -1;
}

bool parse_bssid(const char *text, uint8_t out[6]) {
    if (!text || strlen(text) != 17) return false;
    bool any = false;
    for (unsigned i = 0; i < 6; ++i) {
        const int high = hex_digit(text[i * 3]), low = hex_digit(text[i * 3 + 1]);
        if (high < 0 || low < 0 || (i != 5 && text[i * 3 + 2] != ':')) return false;
        out[i] = static_cast<uint8_t>((high << 4) | low);
        any |= out[i] != 0;
    }
    return any && !(out[0] & 1);  // BSSID must be a nonzero unicast address.
}

bool valid_password(const String &password) {
    if (password.length() == 0) return true;  // Open AP; Save checks scan auth.
    if (password.length() < 8 || password.length() > 63) return false;
    for (size_t i = 0; i < password.length(); ++i) {
        if (static_cast<uint8_t>(password[i]) < 32 || static_cast<uint8_t>(password[i]) > 126) return false;
    }
    return true;
}

String profile_json(const Profile &profile) {
    JsonDocument document;
    char bssid[18];
    bssid_string(profile.bssid, bssid);
    document["version"] = 1;
    document["ssid"] = profile.ssid;
    document["password"] = profile.password;
    document["bssid"] = bssid;
    document["channel"] = profile.channel;
    String json;
    serializeJson(document, json);
    return json;
}

bool load_profile(const char *key, Profile &profile) {
    profile = Profile();
    const String json = g_preferences.getString(key, "");
    if (json.length() == 0 || json.length() > MAX_PROFILE_JSON) return false;
    JsonDocument document;
    if (deserializeJson(document, json) || document["version"].as<int>() != 1 ||
        !document["ssid"].is<const char *>() || !document["password"].is<const char *>() ||
        !document["bssid"].is<const char *>() || !document["channel"].is<int>()) return false;
    const JsonString ssid = document["ssid"].as<JsonString>();
    const JsonString password = document["password"].as<JsonString>();
    if (!ssid.size() || ssid.size() > 32 || strlen(ssid.c_str()) != ssid.size() ||
        password.size() > 63 || strlen(password.c_str()) != password.size()) return false;
    const int channel = document["channel"].as<int>();
    if (channel < 1 || channel > 13 || !parse_bssid(document["bssid"], profile.bssid)) return false;
    profile.ssid = ssid.c_str();
    profile.password = password.c_str();
    if (!valid_password(profile.password)) return false;
    profile.channel = static_cast<uint8_t>(channel);
    profile.valid = true;
    return true;
}

bool store_profile(const char *key, const Profile &profile) {
    if (!g_nvs_ready || !profile.valid) return false;
    const String json = profile_json(profile);
    return json.length() <= MAX_PROFILE_JSON && g_preferences.putString(key, json) == json.length();
}

void finish_export_release() {
    if (g_export_uart_draining) {
        // Zero ticks: test the hardware UART without flush or a blocking wait.
        if (uart_wait_tx_done(UART_NUM_0, 0) != ESP_OK) return;
        g_export_uart_draining = false;
    }
    if (!g_export_release_pending || g_export_secret_tx || g_export_uart_draining) return;
    const bool claimed = g_export_claimed;
    g_export_claimed = g_export_release_pending = false;
    if (claimed && g_export_resume) g_export_resume();
}

void release_export_when_safe() {
    g_export_release_pending = true;
    finish_export_release();
}

void queue_line(const char *prefix, const char *nonce, const char *value) {
    if (g_tx_size) return;
    const int size = snprintf(g_tx, sizeof(g_tx), "%s:%s:%s\n", prefix, nonce, value);
    if (size <= 0 || static_cast<size_t>(size) >= sizeof(g_tx)) return;
    g_tx_size = static_cast<size_t>(size);
    g_tx_offset = 0;
}

void queue_error(const char *nonce, const char *code) { queue_line("BMWIFI_ERROR", nonce, code); }

void revoke_export() {
    g_export_open = false;
    g_export_nonce[0] = '\0';
    release_export_when_safe();
}

bool target_connected() {
    return g_target.valid && WiFi.status() == WL_CONNECTED && WiFi.SSID() == g_target.ssid &&
           WiFi.channel() >= 1 && WiFi.channel() <= 13 && WiFi.BSSID() &&
           memcmp(WiFi.BSSID(), g_target.bssid, 6) == 0;
}

void restore_channel(uint8_t channel) {
    if (WiFi.status() != WL_CONNECTED && channel >= 1 && channel <= 13) {
        esp_wifi_set_channel(channel, WIFI_SECOND_CHAN_NONE);
    }
}

void begin_join(const Profile &profile, bool applying) {
    g_target = profile;
    g_applying = applying;
    g_retry_pending = false;
    g_network_enabled = true;
    g_connecting = true;
    g_connect_started = millis();
    if (!g_peer_fresh) g_peer_missing_since = g_connect_started;
    wifi_second_chan_t secondary;
    esp_wifi_get_channel(&g_join_home_channel, &secondary);
    g_join_ip_generation = g_ip_generation.load(std::memory_order_relaxed);
    WiFi.setAutoReconnect(false);
    WiFi.disconnect(false, false);
    // The exact BSSID pins the AP. Channel zero permits router channel changes
    // since enrollment; both peers join this same AP and follow its channel.
    WiFi.begin(profile.ssid.c_str(), profile.password.c_str(), 0, profile.bssid, true);
    set_status(applying ? "Connecting to the selected access point..." : "Connecting to the saved network...");
}

void abort_trial(bool automatic) {
    g_trial = g_trial_connected = g_connecting = g_applying = g_network_enabled = false;
    revoke_export();
    WiFi.setAutoReconnect(false);
    WiFi.disconnect(false, false);
    restore_channel(g_join_home_channel);
    snprintf(g_abort_nonce, sizeof(g_abort_nonce), "%s", g_apply_nonce);
    snprintf(g_apply_result, sizeof(g_apply_result), "%s", automatic ? "FAILED_TRIAL_TIMEOUT" : "ABORTED");
    g_preferences.remove("pending");
    g_pending = Profile();
    if (g_active.valid) begin_join(g_active, false);
    else {
        g_target = Profile();
        g_rescan_requested = true;
    }
    set_status(automatic ? "USB setup timed out. Previous network settings were restored; repeat setup if needed."
                         : "USB setup cancelled. Previous network settings were restored.");
    if (automatic) g_completion_pending = true;
}

void handle_request(const network_setup_protocol::Request &request) {
    const uint32_t now = millis();
    if (request.command == network_setup_protocol::Command::Profile) {
        if (!g_export_open || static_cast<uint32_t>(now - g_saved_at) > EXPORT_WINDOW_MS) {
            revoke_export();
            queue_error(request.nonce, "SAVE_REQUIRED");
            return;
        }
        if (!g_pending.valid) { queue_error(request.nonce, "PENDING_MISSING"); return; }
        if (g_export_nonce[0] && strcmp(g_export_nonce, request.nonce) != 0) {
            queue_error(request.nonce, "NONCE_MISMATCH"); return;
        }
        // Main's log guard cannot suppress native Arduino TLS log_e writes.
        // Claim the worker pause before constructing or queuing any secret.
        if (!g_export_prepare || !g_export_resume) {
            queue_error(request.nonce, "EXPORT_HOOKS_REQUIRED"); return;
        }
        g_export_claimed = true;  // prepare may pause future jobs even if busy.
        if (!g_export_prepare()) {
            queue_line("BMWIFI_WAIT", request.nonce, "ARTWORK_BUSY");
            return;  // Host retries; worker remains paused between requests.
        }
        const String json = profile_json(g_pending);
        unsigned char encoded[4 * ((MAX_PROFILE_JSON + 2) / 3) + 1] = {};
        size_t written = 0;
        if (json.length() > MAX_PROFILE_JSON ||
            mbedtls_base64_encode(encoded, sizeof(encoded), &written,
                                  reinterpret_cast<const unsigned char *>(json.c_str()), json.length()) != 0) {
            queue_error(request.nonce, "PROFILE_ENCODING_FAILED");
            release_export_when_safe();
            return;
        }
        snprintf(g_export_nonce, sizeof(g_export_nonce), "%s", request.nonce);
        queue_line("BMWIFI_PROFILE", request.nonce, reinterpret_cast<const char *>(encoded));
        if (g_tx_size) {
            g_export_secret_tx = true;
            g_export_release_pending = true;
        } else release_export_when_safe();
        memset(encoded, 0, sizeof(encoded));
        return;
    }
    if (request.command == network_setup_protocol::Command::Commit) {
        if (g_commit_nonce[0] && strcmp(request.nonce, g_commit_nonce) == 0) {
            queue_line("BMWIFI_ACK", request.nonce, "COMMITTED"); return;
        }
        if (!g_apply_nonce[0] || strcmp(request.nonce, g_apply_nonce) != 0) {
            queue_error(request.nonce, "NONCE_MISMATCH"); return;
        }
        if (!g_trial || !g_trial_connected || !target_connected()) {
            queue_error(request.nonce, "TRIAL_NOT_CONNECTED"); return;
        }
        if (!store_profile("active", g_target)) {
            queue_error(request.nonce, "COMMIT_STORAGE_FAILED");
            set_status("Could not commit the network profile. Keep USB connected and retry setup.");
            return;
        }
        g_active = g_target;
        g_preferences.remove("pending");
        g_pending = Profile();
        g_trial = g_trial_connected = false;
        snprintf(g_commit_nonce, sizeof(g_commit_nonce), "%s", request.nonce);
        snprintf(g_apply_result, sizeof(g_apply_result), "COMMITTED");
        queue_line("BMWIFI_ACK", request.nonce, "COMMITTED");
        set_status("Connected. Network setup is complete.");
        return;
    }
    if (request.command == network_setup_protocol::Command::Abort) {
        if (g_commit_nonce[0] && strcmp(request.nonce, g_commit_nonce) == 0) {
            queue_error(request.nonce, "ALREADY_COMMITTED"); return;
        }
        if (g_abort_nonce[0] && strcmp(request.nonce, g_abort_nonce) == 0) {
            queue_line("BMWIFI_ACK", request.nonce, "ABORTED"); return;
        }
        if (!g_trial || !g_apply_nonce[0] || strcmp(request.nonce, g_apply_nonce) != 0) {
            queue_error(request.nonce, "NONCE_MISMATCH"); return;
        }
        abort_trial(false);
        queue_line("BMWIFI_ACK", request.nonce, "ABORTED");
        return;
    }
    if (request.command != network_setup_protocol::Command::Apply) return;
    if (g_apply_nonce[0] && strcmp(request.nonce, g_apply_nonce) == 0) {
        queue_line(strcmp(g_apply_result, "APPLYING") == 0 ? "BMWIFI_ACK" : "BMWIFI_STATUS",
                   request.nonce, g_apply_result);
        return;  // Idempotent retry never starts another connection attempt.
    }
    if (!g_export_open || static_cast<uint32_t>(now - g_saved_at) > EXPORT_WINDOW_MS ||
        !g_export_nonce[0]) { queue_error(request.nonce, "SAVE_REQUIRED"); return; }
    if (strcmp(request.nonce, g_export_nonce) != 0) { queue_error(request.nonce, "NONCE_MISMATCH"); return; }
    if (g_connecting || g_scanning || g_retry_pending) { queue_error(request.nonce, "BUSY"); return; }
    snprintf(g_apply_nonce, sizeof(g_apply_nonce), "%s", request.nonce);
    snprintf(g_apply_result, sizeof(g_apply_result), "APPLYING");
    g_trial = true;
    g_trial_connected = false;
    g_trial_started = now;
    revoke_export();  // A later credential export needs another on-panel Save.
    queue_line("BMWIFI_ACK", request.nonce, "APPLYING");
    begin_join(g_pending, true);
}

void poll_serial() {
    // Pause command parsing while a response is being sent. Other Serial0
    // producers must honor network_setup_serial_busy() to prevent interleaving.
    finish_export_release();
    if (g_export_uart_draining) return;
    if (!g_tx_size && g_completion_pending) {
        queue_line("BMWIFI_STATUS", g_apply_nonce, g_apply_result);
        g_completion_pending = false;
    }
    if (!g_tx_size) {
        network_setup_protocol::Request request;
        for (unsigned i = 0; i < 64 && Serial0.available(); ++i) {
            if (g_parser.feed(static_cast<uint8_t>(Serial0.read()), request)) {
                handle_request(request);
                if (g_tx_size) break;
            }
        }
    }
    if (!g_tx_size) return;
    const int available = Serial0.availableForWrite();
    if (available <= 0) return;
    size_t piece = g_tx_size - g_tx_offset;
    if (piece > 64) piece = 64;
    if (piece > static_cast<size_t>(available)) piece = static_cast<size_t>(available);
    g_tx_offset += Serial0.write(reinterpret_cast<const uint8_t *>(g_tx + g_tx_offset), piece);
    if (g_tx_offset == g_tx_size) {
        memset(g_tx, 0, sizeof(g_tx));
        g_tx_size = g_tx_offset = 0;
        if (g_export_secret_tx) {
            g_export_secret_tx = false;
            g_export_uart_draining = true;
            finish_export_release();
        }
    }
}

void close_modal(lv_event_t *) {
    if (g_trial) {
        abort_trial(false);
        snprintf(g_apply_result, sizeof(g_apply_result), "FAILED_CANCELLED");
        g_completion_pending = true;
    } else revoke_export();
    if (g_password) lv_textarea_set_text(g_password, "");
    lv_obj_del(g_modal);
    g_modal = g_list = g_selected_label = g_password = g_keyboard = g_status = nullptr;
}

void select_ap(lv_event_t *event) {
    const size_t index = reinterpret_cast<uintptr_t>(lv_event_get_user_data(event));
    if (index >= g_network_count) return;
    g_selected = static_cast<int>(index);
    char bssid[18], text[128];
    bssid_string(g_networks[index].bssid, bssid);
    snprintf(text, sizeof(text), "%s  |  %s  |  ch %u", g_networks[index].ssid.c_str(), bssid,
             static_cast<unsigned>(g_networks[index].channel));
    lv_label_set_text(g_selected_label, text);
    lv_textarea_set_text(g_password, "");
    lv_obj_clear_flag(g_keyboard, LV_OBJ_FLAG_HIDDEN);
    lv_keyboard_set_textarea(g_keyboard, g_password);
    set_status(g_networks[index].enterprise ? "Enterprise Wi-Fi is not supported." : "Enter the network password, then Save.");
}

void finish_scan(int count) {
    g_network_count = 0;
    g_selected = -1;
    if (g_list) lv_obj_clean(g_list);
    for (int index = 0; index < count && g_network_count < MAX_NETWORKS; ++index) {
        const int channel = WiFi.channel(index);
        if (channel < 1 || channel > 13 || WiFi.SSID(index).length() == 0 || !WiFi.BSSID(index)) continue;
        AccessPoint &ap = g_networks[g_network_count];
        ap.ssid = WiFi.SSID(index);
        memcpy(ap.bssid, WiFi.BSSID(index), 6);
        ap.channel = static_cast<uint8_t>(channel);
        ap.rssi = WiFi.RSSI(index);
        ap.open = WiFi.encryptionType(index) == WIFI_AUTH_OPEN;
        ap.enterprise = WiFi.encryptionType(index) == WIFI_AUTH_WPA2_ENTERPRISE;
        if (g_list) {
            char bssid[18], label[128];
            bssid_string(ap.bssid, bssid);
            snprintf(label, sizeof(label), "%s  ch %u  %ld dBm  %s%s", ap.ssid.c_str(),
                     static_cast<unsigned>(ap.channel), static_cast<long>(ap.rssi), bssid, ap.open ? "  OPEN" : "");
            lv_obj_t *button = lv_list_add_btn(g_list, LV_SYMBOL_WIFI, label);
            lv_obj_add_event_cb(button, select_ap, LV_EVENT_CLICKED, reinterpret_cast<void *>(g_network_count));
        }
        ++g_network_count;
    }
    WiFi.scanDelete();
    g_scanning = false;
    if (!g_scan_was_connected) restore_channel(g_scan_home_channel);
    set_status(g_network_count ? "Select the exact 2.4 GHz access point from the list." : "No usable 2.4 GHz access points found. Try Scan again.");
}

void start_scan(lv_event_t *) {
    if (g_scanning || g_connecting || g_retry_pending || g_trial) { set_status("Wait for the current network operation to finish."); return; }
    revoke_export();
    g_scan_was_connected = WiFi.status() == WL_CONNECTED;
    wifi_second_chan_t secondary;
    esp_wifi_get_channel(&g_scan_home_channel, &secondary);
    const int result = WiFi.scanNetworks(true, false, false, 120);
    if (result == WIFI_SCAN_FAILED) { set_status("Wi-Fi scan could not start."); restore_channel(g_scan_home_channel); return; }
    g_scanning = true;
    set_status("Scanning 2.4 GHz access points...");
    if (result >= 0) finish_scan(result);
}

void save_pending(lv_event_t *) {
    if (g_keyboard) lv_obj_add_flag(g_keyboard, LV_OBJ_FLAG_HIDDEN);
    if (!g_nvs_ready) { set_status("Network storage is unavailable; nothing was changed."); return; }
    if (g_scanning || g_connecting || g_retry_pending || g_trial) { set_status("Wait for the current network operation to finish."); return; }
    if (g_selected < 0 || static_cast<size_t>(g_selected) >= g_network_count) { set_status("Select an access point first."); return; }
    const AccessPoint &ap = g_networks[g_selected];
    if (ap.enterprise) { set_status("Enterprise Wi-Fi is not supported."); return; }
    Profile candidate;
    candidate.ssid = ap.ssid;
    candidate.password = lv_textarea_get_text(g_password);
    memcpy(candidate.bssid, ap.bssid, 6);
    candidate.channel = ap.channel;
    candidate.valid = true;
    if (!valid_password(candidate.password) || (!ap.open && candidate.password.length() == 0) ||
        (ap.open && candidate.password.length() != 0)) {
        set_status(ap.open ? "This is an open network; leave its password empty." : "Use an 8-63 character network password.");
        return;
    }
    if (!store_profile("pending", candidate)) { set_status("Could not save the pending profile; active network is unchanged."); return; }
    g_pending = candidate;
    g_saved_at = millis();
    g_export_open = true;
    g_export_nonce[0] = g_apply_nonce[0] = '\0';
    g_commit_nonce[0] = g_abort_nonce[0] = '\0';
    g_apply_result[0] = '\0';
    g_completion_pending = false;
    lv_textarea_set_text(g_password, "");
    lv_obj_add_flag(g_keyboard, LV_OBJ_FLAG_HIDDEN);
    set_status("Pending profile saved. Complete the one-time USB setup to the audio unit. Wi-Fi has not changed yet.");
}

lv_obj_t *button(lv_obj_t *parent, const char *text, int x, int y, int width, lv_event_cb_t callback) {
    lv_obj_t *object = lv_btn_create(parent);
    lv_obj_set_pos(object, x, y);
    lv_obj_set_size(object, width, 38);
    lv_obj_t *label = lv_label_create(object);
    lv_label_set_text(label, text);
    lv_obj_center(label);
    lv_obj_add_event_cb(object, callback, LV_EVENT_CLICKED, nullptr);
    return object;
}

void keyboard_event(lv_event_t *event) {
    if (lv_event_get_code(event) == LV_EVENT_READY || lv_event_get_code(event) == LV_EVENT_CANCEL) {
        lv_obj_add_flag(g_keyboard, LV_OBJ_FLAG_HIDDEN);
    }
}

void password_focus(lv_event_t *) {
    lv_obj_clear_flag(g_keyboard, LV_OBJ_FLAG_HIDDEN);
    lv_keyboard_set_textarea(g_keyboard, g_password);
}

void retry_both(lv_event_t *) {
    if (!g_active.valid || !g_retry_callback) {
        set_status("Complete the one-time USB network setup before using Retry both.");
        return;
    }
    if (g_connecting || g_scanning || g_retry_pending || g_trial) { set_status("A network operation is already in progress."); return; }
    revoke_export();
    WiFi.setAutoReconnect(false);
    WiFi.disconnect(false, false);
    g_network_enabled = false;
    g_retry_callback();  // Explicit user gesture; root sends only NET_RETRY.
    g_retry_pending = true;
    g_retry_at = millis() + RETRY_WAIT_MS;
    set_status("Retry requested for both devices. Waiting for the audio unit...");
}

}  // namespace

void network_setup_begin() {
    if (g_started) return;
    g_started = true;
    g_nvs_ready = g_preferences.begin("bm83net", false);
    WiFi.persistent(false);  // Preferences is the sole application credential store.
    WiFi.setAutoReconnect(false);
    WiFi.onEvent([](WiFiEvent_t event, WiFiEventInfo_t) {
        if (event == ARDUINO_EVENT_WIFI_STA_GOT_IP) g_ip_generation.fetch_add(1, std::memory_order_relaxed);
    });
    if (!g_nvs_ready) { set_status("Network storage is unavailable; ESP-NOW controls remain usable."); return; }
    load_profile("pending", g_pending);  // Never auto-join a pending profile.
    if (load_profile("active", g_active)) begin_join(g_active, false);
    else set_status("Wi-Fi is not configured. Select Scan to set it up.");
}

void network_setup_tick() {
    if (!g_started || g_suspended) return;
    poll_serial();
    const uint32_t now = millis();
    if (g_export_open && static_cast<uint32_t>(now - g_saved_at) > EXPORT_WINDOW_MS) revoke_export();
    if (g_scanning) {
        const int result = WiFi.scanComplete();
        if (result != WIFI_SCAN_RUNNING) finish_scan(result < 0 ? 0 : result);
    }
    if (g_retry_pending && static_cast<int32_t>(now - g_retry_at) >= 0) begin_join(g_active, false);
    if (g_trial && static_cast<uint32_t>(now - g_trial_started) >= TRIAL_TIMEOUT_MS) abort_trial(true);
    if (g_connecting) {
        if (g_ip_generation.load(std::memory_order_relaxed) != g_join_ip_generation && target_connected()) {
            g_connecting = false;
            g_target.channel = static_cast<uint8_t>(WiFi.channel());
            if (g_applying) {
                g_trial_connected = true;
                set_status("Connected for a trial. Waiting for USB verification of the audio-unit link...");
                snprintf(g_apply_result, sizeof(g_apply_result), "CONNECTED");
                g_completion_pending = true;
            } else {
                if (g_active.channel != g_target.channel) {
                    g_active.channel = g_target.channel;
                    store_profile("active", g_active);  // Nonsecret channel hint only.
                }
                set_status("Connected to the saved network.");
            }
            if (g_network_enabled) WiFi.setAutoReconnect(true);
            g_applying = false;
        } else if (static_cast<uint32_t>(now - g_connect_started) >= CONNECT_TIMEOUT_MS) {
            const bool was_applying = g_applying;
            g_connecting = g_applying = false;
            g_network_enabled = false;
            WiFi.setAutoReconnect(false);
            WiFi.disconnect(false, false);
            restore_channel(g_join_home_channel);
            g_rescan_requested = true;
            if (was_applying) {
                set_status("Could not connect. Check the selected access point and password, then Save again.");
                snprintf(g_apply_result, sizeof(g_apply_result), "FAILED_CONNECTION");
                g_completion_pending = true;
            } else set_status("Saved network unavailable. Using cached art and local controls. Use Retry both to reconnect.");
        }
    }
    if (g_network_enabled && !g_connecting && !g_scanning && g_peer_known && !g_peer_fresh &&
        static_cast<uint32_t>(now - g_peer_missing_since) >= PEER_MISSING_MS) {
        // Controls take priority over a unilateral AP connection. Do not keep
        // reconnecting on a channel the audio peer may no longer be using.
        g_network_enabled = false;
        WiFi.setAutoReconnect(false);
        WiFi.disconnect(false, false);
        g_rescan_requested = true;
        if (g_trial) {
            g_trial_connected = false;
            snprintf(g_apply_result, sizeof(g_apply_result), "FAILED_PEER_LINK");
            g_completion_pending = true;
        }
        set_status("Wi-Fi paused to restore the audio-unit link. Use Retry both after controls reconnect.");
    }
}

void network_setup_show(lv_obj_t *parent) {
    if (g_modal || g_suspended) return;
    g_selected = -1;
    g_modal = lv_obj_create(parent);
    lv_obj_set_size(g_modal, 800, 480);
    lv_obj_center(g_modal);
    lv_obj_clear_flag(g_modal, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_pad_all(g_modal, 12, 0);
    lv_obj_t *heading = lv_label_create(g_modal);
    lv_label_set_text(heading, "Wi-Fi setup - password stays on this panel and one-time USB");
    lv_obj_set_pos(heading, 0, 0);
    button(g_modal, "Scan", 0, 30, 110, start_scan);
    button(g_modal, "Retry both", 120, 30, 140, retry_both);
    button(g_modal, "Save", 540, 30, 100, save_pending);
    button(g_modal, "Cancel", 650, 30, 100, close_modal);
    g_selected_label = lv_label_create(g_modal);
    lv_obj_set_pos(g_selected_label, 270, 40);
    lv_obj_set_width(g_selected_label, 260);
    lv_label_set_long_mode(g_selected_label, LV_LABEL_LONG_DOT);
    lv_label_set_text(g_selected_label, "Select a 2.4 GHz access point");
    g_list = lv_list_create(g_modal);
    lv_obj_set_pos(g_list, 0, 76);
    lv_obj_set_size(g_list, 750, 150);
    g_password = lv_textarea_create(g_modal);
    lv_obj_set_pos(g_password, 0, 232);
    lv_obj_set_size(g_password, 750, 42);
    lv_textarea_set_one_line(g_password, true);
    lv_textarea_set_password_mode(g_password, true);
    lv_textarea_set_password_show_time(g_password, 0);
    lv_textarea_set_max_length(g_password, 63);
    lv_textarea_set_placeholder_text(g_password, "Network password");
    lv_obj_add_event_cb(g_password, password_focus, LV_EVENT_FOCUSED, nullptr);
    g_status = lv_label_create(g_modal);
    lv_obj_set_pos(g_status, 0, 284);
    lv_obj_set_width(g_status, 750);
    lv_label_set_long_mode(g_status, LV_LABEL_LONG_WRAP);
    lv_label_set_text(g_status, g_status_text);
    g_keyboard = lv_keyboard_create(g_modal);
    lv_obj_set_size(g_keyboard, 750, 172);
    lv_obj_align(g_keyboard, LV_ALIGN_BOTTOM_MID, 0, 0);
    lv_keyboard_set_textarea(g_keyboard, g_password);
    lv_obj_add_event_cb(g_keyboard, keyboard_event, LV_EVENT_ALL, nullptr);
    lv_obj_add_flag(g_keyboard, LV_OBJ_FLAG_HIDDEN);
}

bool network_setup_ready() { return !g_suspended && g_network_enabled && !g_connecting && target_connected(); }
bool network_setup_serial_busy() { return g_tx_size != 0 || g_export_claimed || g_export_uart_draining; }
bool network_setup_radio_busy() {
    return !g_suspended && (g_connecting || g_scanning || g_retry_pending);
}

void network_setup_peer_fresh(bool fresh) {
    if (g_suspended) return;
    if (!g_peer_known || (g_peer_fresh && !fresh)) g_peer_missing_since = millis();
    g_peer_known = true;
    g_peer_fresh = fresh;
}

bool network_setup_take_rescan_request() {
    if (g_suspended) return false;
    const bool requested = g_rescan_requested;
    g_rescan_requested = false;
    return requested;
}

void network_setup_set_retry_callback(void (*callback)()) { g_retry_callback = callback; }

void network_setup_set_export_hooks(bool (*prepare)(), void (*resume)()) {
    if (g_export_claimed || g_export_secret_tx || g_export_uart_draining) return;
    g_export_prepare = prepare;
    g_export_resume = resume;
}

bool network_setup_prepare_sleep() {
    if (g_suspended) return true;
    if (g_trial || g_connecting || g_scanning || g_retry_pending || network_setup_serial_busy() ||
        g_completion_pending || g_export_open || g_modal) return false;
    // Only an already enabled committed network is resumed automatically.
    // An initially failed/offline profile must retain its control-first policy.
    g_resume_network = g_active.valid && g_network_enabled;
    revoke_export();
    g_suspended = true;
    g_network_enabled = false;
    g_rescan_requested = false;
    WiFi.setAutoReconnect(false);
    WiFi.disconnect(false, false);
    return true;
}

void network_setup_resume_after_sleep() {
    if (!g_suspended) return;
    const bool rejoin = g_resume_network && g_active.valid;
    g_resume_network = false;
    g_suspended = false;
    g_peer_known = g_peer_fresh = false;
    g_peer_missing_since = millis();
    // Caller has already rebuilt STA/ESP-NOW after its WiFi.mode(WIFI_OFF).
    if (rejoin) begin_join(g_active, false);
    else {
        g_network_enabled = false;
        g_rescan_requested = true;
        set_status("Awake in local control mode. Use Retry both to reconnect Wi-Fi.");
    }
}

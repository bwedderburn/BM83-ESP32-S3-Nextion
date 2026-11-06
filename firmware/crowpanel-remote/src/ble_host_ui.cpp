#include "ble_host_ui.h"
#include "ble_host_policy.h"
#include "metadata_fonts.h"
#include "windows_launch.h"
#include <Arduino.h>
#include <esp_system.h>
#include <stdio.h>

namespace {
namespace hp = ble_host_policy;
hp::Control g_control;
espnow_log_fn g_log = nullptr;
lv_obj_t *g_modal = nullptr, *g_status = nullptr, *g_hosts = nullptr;
lv_obj_t *g_hint = nullptr;
lv_obj_t *g_disconnect = nullptr, *g_connect = nullptr, *g_enroll = nullptr, *g_rename = nullptr;
lv_obj_t *g_open_windows = nullptr, *g_launch_status = nullptr;
lv_obj_t *g_alias_modal = nullptr, *g_alias_text = nullptr, *g_alias_error = nullptr;
bool g_refreshing = false;
char g_options[440] = {};

const char *ALIAS_LOWER_KEYS[] = {
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", LV_SYMBOL_BACKSPACE, "\n",
    "q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "-", "_", "\n",
    "a", "s", "d", "f", "g", "h", "j", "k", "l", ".", "@", ":", "\n",
    "z", "x", "c", "v", "b", "n", "m", "/", "'", "\"", "?", "\n",
    "!", "#", "$", "%", "&", "*", "(", ")", "+", "=", "\n",
    "ABC", ",", ";", "[", LV_SYMBOL_LEFT, "Space", LV_SYMBOL_RIGHT, "]", "\\", ""
};

const char *ALIAS_UPPER_KEYS[] = {
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", LV_SYMBOL_BACKSPACE, "\n",
    "Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P", "-", "_", "\n",
    "A", "S", "D", "F", "G", "H", "J", "K", "L", ".", "@", ":", "\n",
    "Z", "X", "C", "V", "B", "N", "M", "/", "'", "\"", "?", "\n",
    "<", ">", "{", "}", "^", "|", "~", "`", "(", ")", "\n",
    "abc", ",", ";", "[", LV_SYMBOL_LEFT, "Space", LV_SYMBOL_RIGHT, "]", "\\", ""
};

void alias_keymap(lv_obj_t *keyboard, const char **keys) {
    lv_btnmatrix_set_map(keyboard, keys);
    lv_btnmatrix_set_btn_ctrl_all(keyboard, LV_BTNMATRIX_CTRL_CLICK_TRIG | LV_BTNMATRIX_CTRL_NO_REPEAT);
    uint16_t index = 0;
    for (const char * const *key = keys; **key; ++key) {
        if (!strcmp(*key, "\n")) continue;
        if (!strcmp(*key, "Space")) lv_btnmatrix_set_btn_width(keyboard, index, 4);
        else if (!strcmp(*key, "ABC") || !strcmp(*key, "abc") || !strcmp(*key, LV_SYMBOL_BACKSPACE))
            lv_btnmatrix_set_btn_width(keyboard, index, 2);
        ++index;
    }
}

void alias_key_pressed(lv_event_t *event) {
    lv_obj_t *keyboard = lv_event_get_target(event);
    const char *key = lv_btnmatrix_get_btn_text(keyboard, lv_btnmatrix_get_selected_btn(keyboard));
    if (!key || !g_alias_text) return;
    if (!strcmp(key, "ABC")) alias_keymap(keyboard, ALIAS_UPPER_KEYS);
    else if (!strcmp(key, "abc")) alias_keymap(keyboard, ALIAS_LOWER_KEYS);
    else if (!strcmp(key, LV_SYMBOL_LEFT)) lv_textarea_cursor_left(g_alias_text);
    else if (!strcmp(key, LV_SYMBOL_RIGHT)) lv_textarea_cursor_right(g_alias_text);
    else if (!strcmp(key, LV_SYMBOL_BACKSPACE)) lv_textarea_del_char(g_alias_text);
    else lv_textarea_add_text(g_alias_text, !strcmp(key, "Space") ? " " : key);
}

void text(lv_obj_t *label, const char *value) {
    if (label && strcmp(lv_label_get_text(label), value)) lv_label_set_text(label, value);
}
void enabled(lv_obj_t *object, bool value) {
    if (!object) return;
    if (value) lv_obj_clear_state(object, LV_STATE_DISABLED);
    else lv_obj_add_state(object, LV_STATE_DISABLED);
}
lv_obj_t *label(lv_obj_t *parent, const char *value, int x, int y, int width, const lv_font_t *font) {
    lv_obj_t *object = lv_label_create(parent); lv_obj_set_pos(object, x, y); lv_obj_set_width(object, width);
    lv_obj_set_style_text_font(object, font, 0); lv_obj_set_style_text_color(object, lv_color_hex(0xE8EAED), 0);
    lv_label_set_long_mode(object, LV_LABEL_LONG_WRAP); lv_label_set_text(object, value); return object;
}
lv_obj_t *button(lv_obj_t *parent, const char *value, int x, int y, int width, lv_event_cb_t callback) {
    lv_obj_t *object = lv_btn_create(parent); lv_obj_set_pos(object, x, y); lv_obj_set_size(object, width, 46);
    lv_obj_set_style_radius(object, 8, 0); lv_obj_set_style_bg_color(object, lv_color_hex(0x17689E), 0);
    lv_obj_t *caption = lv_label_create(object); lv_label_set_text(caption, value);
    lv_obj_set_style_text_font(caption, &lv_font_montserrat_16, 0); lv_obj_center(caption);
    lv_obj_add_event_cb(object, callback, LV_EVENT_CLICKED, nullptr); return object;
}
void peer_name(const uint8_t *id, uint32_t now, char *out, size_t capacity) {
    const hp::Peer *peer = g_control.decoder.find(id, now);
    if (peer && peer->alias[0]) snprintf(out, capacity, "%s", peer->alias);
    else if (id && !hp::id_none(id)) snprintf(out, capacity, "Saved host %02x%02x%02x%02x", id[4], id[5], id[6], id[7]);
    else snprintf(out, capacity, "No host selected");
}

void status_text(uint32_t now, char *out, size_t capacity) {
    const hp::Decoder &decoder = g_control.decoder;
    if (!decoder.fresh_status(now)) { snprintf(out, capacity, "Controller host status unavailable"); return; }
    const hp::Status &state = decoder.status;
    if (!decoder.supported(now) || state.state == hp::UNSUPPORTED) {
        snprintf(out, capacity, "Host switching needs updated controller firmware"); return;
    }
    if (!g_control.admitted(now)) { snprintf(out, capacity, "Loading saved volume hosts..."); return; }
    if (g_control.result == hp::REJECTED) {
        snprintf(out, capacity, "Request rejected (code %u). Refresh the host selection.", state.request_error); return;
    }
    if (g_control.result == hp::ENROLLMENT_ENDED && state.state == hp::PAUSED_STATE &&
        state.requested_mode == hp::PAUSED && state.applied_mode == hp::PAUSED &&
        !(state.flags & (hp::CONNECTED_FLAG | hp::ADVERTISING)) &&
        ((!state.error_domain && !state.error_code) || (state.error_domain == 1 && state.error_code == 6))) {
        snprintf(out, capacity, "Pairing window ended without a connected host."); return;
    }
    if (state.state == hp::ERROR_STATE || state.error_domain || state.error_code || g_control.result == hp::FAILED) {
        snprintf(out, capacity, "Host operation failed (domain %u, code %ld, reason %lu)",
                 state.error_domain, static_cast<long>(state.error_code), static_cast<unsigned long>(state.reason)); return;
    }
    if (g_control.result == hp::TIMED_OUT) { snprintf(out, capacity, "Request unconfirmed. Check the selected host."); return; }
    if (g_control.result == hp::RESTARTED) { snprintf(out, capacity, "Controller restarted. Select the host again."); return; }
    if (g_control.result == hp::SUPERSEDED) { snprintf(out, capacity, "Another request replaced this operation."); return; }
    if (g_control.result == hp::NOT_SENT) { snprintf(out, capacity, "Request was not sent. Controller radio unavailable."); return; }
    char name[64]; peer_name(state.target, now, name, sizeof(name));
    if (state.state == hp::ENROLLING) {
        snprintf(out, capacity, "Pair a new volume host — %u seconds remaining", state.enrollment_remaining); return;
    }
    if (g_control.result == hp::PENDING || state.state == hp::SWITCHING || !(state.flags & hp::READY)) {
        snprintf(out, capacity, "Waiting for the controller to confirm the request..."); return;
    }
    if (state.requested_mode == hp::PAUSED && state.applied_mode == hp::PAUSED &&
        state.state == hp::PAUSED_STATE && (state.flags & hp::PERSISTED) &&
        !(state.flags & (hp::CONNECTED_FLAG | hp::ADVERTISING))) {
        snprintf(out, capacity, "Disconnected. Saved pairings are kept."); return;
    }
    const uint16_t ready = hp::CONNECTED_FLAG | hp::ENCRYPTED | hp::BONDED | hp::HID_READY | hp::PERSISTED | hp::FILTER_READY;
    if (state.requested_mode == hp::AUTO && state.applied_mode == hp::AUTO &&
        state.state == hp::CONNECTED && (state.flags & ready) == ready &&
        !hp::id_none(state.target) && hp::same_id(state.target, state.connected)) {
        snprintf(out, capacity, "Volume control connected to %s", name); return;
    }
    if (state.state == hp::WAITING) { snprintf(out, capacity, "Waiting for %s to connect", name); return; }
    snprintf(out, capacity, "Volume control is not ready");
}

bool send_request(hp::Opcode op, const char *alias = nullptr) {
    uint8_t frame[56];
    const size_t length = g_control.begin(op, millis(), frame, sizeof(frame), alias, 60);
    if (!length) return false;
    // This boolean means an attempt only; the model requires the matching
    // operation and observed native state, persistence and actual HID CCC.
    if (!espnow_send_host_request(frame, length)) g_control.not_sent();
    if (g_log) g_log("[host] request op=%u attempted; waiting for observed state", static_cast<unsigned>(op));
    return true;
}
void close_alias(lv_event_t *) {
    if (g_alias_modal) lv_obj_del(g_alias_modal);
    g_alias_modal = g_alias_text = g_alias_error = nullptr;
}
void close_modal(lv_event_t *) {
    if (g_modal) lv_obj_del(g_modal);
    g_modal = g_status = g_hosts = g_hint = g_disconnect = g_connect = g_enroll = g_rename = nullptr;
    g_open_windows = g_launch_status = nullptr;
    g_alias_modal = g_alias_text = g_alias_error = nullptr;
    g_options[0] = 0;
    // Closing a page does not issue a policy command or cancel native work.
}
void choose(lv_event_t *) {
    if (g_refreshing || !g_hosts) return;
    const uint16_t selected = lv_dropdown_get_selected(g_hosts);
    if (!selected) g_control.clear_selection();
    else g_control.choose(selected - 1, millis());
}
void disconnect(lv_event_t *) { send_request(hp::DISCONNECT); }
void connect(lv_event_t *) { if (g_control.can_connect(millis())) send_request(hp::SELECT); }
void open_windows(lv_event_t *) {
    const uint32_t now = millis();
    windows_launch::request(now);
    enabled(g_open_windows, windows_launch::available(now));
    text(g_launch_status, windows_launch::status(now));
}
void enroll(lv_event_t *) {
    const uint32_t now = millis();
    if (g_control.decoder.coherent_list(now) && g_control.decoder.list.count < hp::MAX_PEERS && !g_control.holding()) send_request(hp::ENROLL);
}
void save_alias(lv_event_t *) {
    if (!g_alias_text) return;
    if (!g_control.can_alias(millis())) { text(g_alias_error, "Host status changed. Close and select the host again."); return; }
    const char *value = lv_textarea_get_text(g_alias_text);
    if (!hp::valid_alias(reinterpret_cast<const uint8_t *>(value), strlen(value))) {
        text(g_alias_error, "Use a shorter name without control characters."); return;
    }
    if (send_request(hp::ALIAS, value)) close_alias(nullptr);
}
void rename(lv_event_t *) {
    const hp::Peer *peer = g_control.selection(millis());
    if (!peer || !g_control.can_alias(millis()) || g_alias_modal) return;
    g_alias_modal = lv_obj_create(g_modal); lv_obj_set_size(g_alias_modal, 748, 402); lv_obj_center(g_alias_modal);
    lv_obj_clear_flag(g_alias_modal, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(g_alias_modal, lv_color_hex(0x101B28), 0);
    lv_obj_set_style_pad_all(g_alias_modal, 0, 0);
    label(g_alias_modal, "Name this saved host", 16, 10, 450, &lv_font_montserrat_18);
    button(g_alias_modal, "Cancel", 508, 4, 100, close_alias); button(g_alias_modal, "Save", 620, 4, 100, save_alias);
    g_alias_text = lv_textarea_create(g_alias_modal); lv_obj_set_pos(g_alias_text, 16, 60); lv_obj_set_size(g_alias_text, 704, 48);
    lv_textarea_set_one_line(g_alias_text, true); lv_textarea_set_max_length(g_alias_text, hp::MAX_ALIAS);
    lv_textarea_set_text(g_alias_text, peer->alias); lv_obj_set_style_text_font(g_alias_text, metadata_fonts::album(), 0);
    g_alias_error = label(g_alias_modal, "Choose your own short name. Empty clears the name.", 16, 116, 704, &lv_font_montserrat_14);
    lv_obj_t *keyboard = lv_btnmatrix_create(g_alias_modal);
    lv_obj_set_pos(keyboard, 12, 142); lv_obj_set_size(keyboard, 724, 248);
    lv_obj_set_style_pad_all(keyboard, 4, 0);
    lv_obj_set_style_pad_gap(keyboard, 4, 0);
    lv_obj_set_style_text_font(keyboard, &lv_font_montserrat_16, LV_PART_ITEMS);
    alias_keymap(keyboard, ALIAS_LOWER_KEYS);
    lv_obj_add_event_cb(keyboard, alias_key_pressed, LV_EVENT_VALUE_CHANGED, nullptr);
}
void refresh(uint32_t now) {
    if (!g_modal) return;
    char message[192]; status_text(now, message, sizeof(message)); text(g_status, message);
    const bool coherent = g_control.admitted(now) && g_control.decoder.coherent_list(now);
    const hp::Peer *selected = g_control.selection(now);
    char options[440] = "Select a saved host...";
    uint16_t selection = 0;
    size_t used = strlen(options);
    if (coherent) {
        for (size_t index = 0; index < g_control.decoder.list.count; ++index) {
            const hp::Peer &peer = g_control.decoder.list.peers[index]; char name[64]; peer_name(peer.id, now, name, sizeof(name));
            const bool current = (g_control.decoder.status.flags & hp::CONNECTED_FLAG) && hp::same_id(peer.id, g_control.decoder.status.connected);
            const int written = snprintf(options + used, sizeof(options) - used, "\n%s%s%s", name,
                                         current ? " (current)" : "", peer.flags & hp::RESUMABLE ? "" : " (unavailable)");
            if (written < 0 || static_cast<size_t>(written) >= sizeof(options) - used) break;
            used += written;
            if (selected && hp::same_id(selected->id, peer.id)) selection = index + 1;
        }
    }
    g_refreshing = true;
    if (strcmp(g_options, options)) { snprintf(g_options, sizeof(g_options), "%s", options); lv_dropdown_set_options(g_hosts, options); }
    if (lv_dropdown_get_selected(g_hosts) != selection) lv_dropdown_set_selected(g_hosts, selection);
    g_refreshing = false;
    enabled(g_hosts, coherent && !g_control.holding());
    enabled(g_disconnect, g_control.can_manage(now));
    enabled(g_connect, g_control.can_connect(now));
    enabled(g_rename, g_control.can_alias(now));
    enabled(g_enroll, coherent && !g_control.holding() && g_control.decoder.list.count < hp::MAX_PEERS);
    text(g_hint, !coherent ? "Waiting for a fresh saved-host list."
              : g_control.decoder.list.count == hp::MAX_PEERS ? "All saved host slots are in use. Existing pairings stay saved."
              : "Controls the BLE volume connection. Saved pairings are kept.\nSelect a saved host and press Connect, or open a 60-second pairing window.");
    enabled(g_open_windows, windows_launch::available(now));
    text(g_launch_status, windows_launch::status(now));
}
}  // namespace

void ble_host_ui_init(espnow_log_fn log) {
    g_log = log; const uint32_t session = esp_random(); g_control.set_client_session(session ? session : 1);
}
bool ble_host_ui_accept(const uint8_t *frame, size_t length, uint32_t now) {
    const bool changed = g_control.decoder.accept(frame, length, now); g_control.tick(now); return changed;
}
void ble_host_ui_tick(uint32_t now) {
    g_control.tick(now);
    uint8_t frame[32];
    const size_t length = g_control.handshake_request(now, frame, sizeof(frame));
    if (length) espnow_send_host_request(frame, length);  // Read-only admission, never AUTO or ENROLL.
    refresh(millis());
}
void ble_host_ui_invalidate_link() { g_control.invalidate_link(); }
bool ble_host_ui_holding() { return g_control.holding(); }
bool ble_host_ui_supported(uint32_t now) { return g_control.decoder.supported(now); }
void ble_host_ui_summary(uint32_t now, char *out, size_t capacity) { status_text(now, out, capacity); }

void ble_host_ui_show(lv_obj_t *screen) {
    if (g_modal) return;
    g_modal = lv_obj_create(screen); lv_obj_set_size(g_modal, 760, 420); lv_obj_center(g_modal);
    lv_obj_clear_flag(g_modal, LV_OBJ_FLAG_SCROLLABLE); lv_obj_set_style_pad_all(g_modal, 0, 0);
    lv_obj_set_style_bg_color(g_modal, lv_color_hex(0x101B28), 0); lv_obj_set_style_radius(g_modal, 12, 0);
    label(g_modal, "Volume hosts", 20, 14, 500, &lv_font_montserrat_18);
    button(g_modal, "Close", 640, 6, 100, close_modal);
    g_status = label(g_modal, "Waiting for controller host status", 20, 70, 720, &lv_font_montserrat_16);
    g_hosts = lv_dropdown_create(g_modal); lv_obj_set_pos(g_hosts, 20, 148); lv_obj_set_size(g_hosts, 460, 46);
    lv_obj_set_style_text_font(g_hosts, metadata_fonts::album(), 0);
    lv_obj_add_event_cb(g_hosts, choose, LV_EVENT_VALUE_CHANGED, nullptr);
    g_connect = button(g_modal, "Connect", 500, 148, 220, connect);
    g_disconnect = button(g_modal, "Disconnect", 20, 210, 220, disconnect);
    g_enroll = button(g_modal, "Pair new host", 260, 210, 220, enroll);
    g_rename = button(g_modal, "Rename", 500, 210, 220, rename);
    g_hint = label(g_modal, "Waiting for a fresh saved-host list.", 20, 282, 700, &lv_font_montserrat_14);
    label(g_modal, "Host names are your labels; other hosts keep Bluetooth on.", 20, 324, 700, &lv_font_montserrat_14);
    g_open_windows = button(g_modal, "Open Windows app", 20, 352, 220, open_windows);
    g_launch_status = label(g_modal, "", 260, 361, 460, &lv_font_montserrat_14);
    g_options[0] = 0; refresh(millis());
}

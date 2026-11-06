#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

struct _lv_obj_t;

// Call begin after ESP-NOW bring-up; tick/show run only from the LVGL task.
void network_setup_begin();
void network_setup_tick();
void network_setup_show(_lv_obj_t *parent);
bool network_setup_ready();
// Pass only freshness from the validated BMS2/BLS2 decoders, not radio ACKs.
void network_setup_peer_fresh(bool playback_fresh, bool status_fresh, bool newly_received);
// Arm progressing-receipt confirmation only after an actual passive channel hop.
void network_setup_note_idle_channel_change();
bool network_setup_take_rescan_request();
void network_setup_set_retry_callback(void (*callback)());
// Credential export must quiesce the artwork/TLS worker first. prepare may
// return false while its current operation finishes; resume follows UART drain.
void network_setup_set_export_hooks(bool (*prepare)(), void (*resume)());
// A true prepare suspends network work and disconnects Wi-Fi without changing
// NVS. If a later sleep prerequisite fails, call resume to cancel preparation.
bool network_setup_prepare_sleep();
void network_setup_resume_after_sleep();

// Suppress other Serial0 log writes while this is true, so the bounded USB
// response cannot be interleaved with a heartbeat. The response may contain
// credentials only after a recent on-panel Save; never log or persist it.
bool network_setup_serial_busy();
// Channel changes are forbidden while the station is scanning or joining.
bool network_setup_radio_busy();
// Committed, automatically paused/missing peer only; excludes trial/export/sleep.
bool network_setup_idle_discovery_allowed();

namespace network_setup_protocol {

enum class Command : uint8_t { None, Profile, Apply, Commit, Abort, WindowsKey, WindowsInfo };
struct Request {
    Command command;
    char nonce[65];
    Request() : command(Command::None) { nonce[0] = '\0'; }
};

inline bool valid_nonce(const char *nonce) {
    if (!nonce) return false;
    const size_t len = strlen(nonce);
    if (len < 8 || len > 64) return false;
    for (size_t i = 0; i < len; ++i) {
        const char c = nonce[i];
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F'))) return false;
    }
    return true;
}

inline bool parse_line(const char *line, Request &request) {
    request = Request();
    const char *nonce = nullptr;
    Command command = Command::None;
    if (line && strcmp(line, "BMWIN_INFO") == 0) {
        request.command = Command::WindowsInfo;
        return true;
    } else if (line && strncmp(line, "BMWIN_KEY:", 10) == 0) {
        nonce = line + 10;
        if (strlen(nonce) != 64) return false;
        command = Command::WindowsKey;
    } else if (line && strncmp(line, "BMWIFI_PROFILE:", 15) == 0) {
        nonce = line + 15;
        command = Command::Profile;
    } else if (line && strncmp(line, "BMWIFI_APPLY:", 13) == 0) {
        nonce = line + 13;
        command = Command::Apply;
    } else if (line && strncmp(line, "BMWIFI_COMMIT:", 14) == 0) {
        nonce = line + 14;
        command = Command::Commit;
    } else if (line && strncmp(line, "BMWIFI_ABORT:", 13) == 0) {
        nonce = line + 13;
        command = Command::Abort;
    }
    if (!valid_nonce(nonce)) return false;
    request.command = command;
    memcpy(request.nonce, nonce, strlen(nonce) + 1);
    return true;
}

class LineParser {
public:
    LineParser() : used_(0), dropping_(false), saw_cr_(false) { line_[0] = '\0'; }
    bool feed(uint8_t byte, Request &request) {
        if (byte == '\n') {
            line_[used_] = '\0';
            const bool valid = !dropping_ && parse_line(line_, request);
            memset(line_, 0, used_);
            used_ = 0;
            dropping_ = false;
            saw_cr_ = false;
            line_[0] = '\0';
            return valid;
        }
        if (byte == '\r') {
            if (saw_cr_) dropping_ = true;
            saw_cr_ = true;
            return false;
        }
        if (dropping_) return false;
        if (saw_cr_ || byte < 32 || byte > 126 || used_ >= sizeof(line_) - 1) {
            dropping_ = true;
            return false;
        }
        line_[used_++] = static_cast<char>(byte);
        return false;
    }
private:
    char line_[96];
    size_t used_;
    bool dropping_, saw_cr_;
};

}  // namespace network_setup_protocol

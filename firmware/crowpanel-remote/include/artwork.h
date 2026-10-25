// Native CrowPanel artwork worker; all LVGL rendering stays on the UI thread.
#pragma once
#include <stddef.h>
#include <stdint.h>

enum class ArtworkStatus : uint8_t {
    Ready, NoMatch, Offline, ClockUnavailable, TrustUnavailable, NetworkError,
    InvalidImage, StorageError
};

struct ArtworkConfig {
    // Supply a maintained root CA PEM set OR ESP-IDF-format certificate bundle.
    // The selected pointer must remain valid for the entire worker lifetime.
    const char *ca_pem = nullptr;
    const uint8_t *ca_bundle = nullptr;
    // Maintained exact archive.org trust anchor for this SDK's legacy cross-chain
    // limitation. Normal hostname, issuer and peer-date checks still apply.
    const char *archive_ca_pem = nullptr;
    const char *ntp_server = "pool.ntp.org";
};

struct ArtworkResult {
    uint32_t request_id = 0;
    ArtworkStatus status = ArtworkStatus::NoMatch;
    uint16_t *rgb565 = nullptr;  // PSRAM, native-endian RGB565, owned by caller.
    uint16_t width = 0, height = 0;
    bool from_cache = false;
    bool sd_ready = false;
    char release_group[37] = {};
};

// Starts one worker. No WiFi mode/credentials are changed. Mounts SD in that
// worker with SCK12/MISO13/MOSI11/CS10 and formatting explicitly disabled.
// Offline positive cache reads work without valid time or a supplied CA set.
bool artwork_begin(const ArtworkConfig &config = ArtworkConfig());

// Latest job wins. Returns its ID; identical metadata reuses the current ID.
// Call with empty strings to cancel artwork for AUX/off/disconnected states.
uint32_t artwork_request(const char *title, const char *artist, const char *album);

// UI thread only. Transfers one current result and buffer ownership to caller.
// No LVGL API is called by the worker. Discarded/obsolete results are freed.
bool artwork_poll(ArtworkResult &out);
void artwork_release(uint16_t *pixels);

// Suspend new claims and cancel queued/in-flight jobs. True only after all
// worker TLS/SD activity has ended. Does not touch a UI-owned image buffer.
// Call repeatedly before light sleep, and resume if sleep is cancelled/wakes.
bool artwork_prepare_sleep();
void artwork_resume();

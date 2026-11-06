#include "windows_launch.h"

#include <Arduino.h>
#include <Preferences.h>
#include <WiFi.h>
#include <esp_system.h>
#include <lwip/sockets.h>
#include <mbedtls/md.h>
#include <mbedtls/platform_util.h>

namespace windows_launch {
namespace {

constexpr uint16_t PORT = 45837;
constexpr uint32_t POLL_INTERVAL_MS = 100;
constexpr uint32_t BIND_RETRY_MS = 2000;
constexpr uint32_t RECEIVER_FRESH_MS = 4000;
constexpr uint32_t EVENT_TTL_MS = 10000;
constexpr size_t ID_SIZE = 16;
constexpr size_t TAG_SIZE = 32;
constexpr size_t NONCE_OFFSET = 5;
constexpr size_t EVENT_OFFSET = NONCE_OFFSET + ID_SIZE;
constexpr size_t TAG_OFFSET = EVENT_OFFSET + ID_SIZE;
constexpr size_t FRAME_SIZE = TAG_OFFSET + TAG_SIZE;
constexpr uint8_t POLL = 1, RESPONSE = 2;

enum class Result { Idle, Pending, Opened, Unconfirmed };

int socket_fd = -1;
Preferences preferences;
IPAddress bound_ip;
uint8_t key[TAG_SIZE] = {};
uint8_t last_nonce[ID_SIZE] = {};
uint8_t event_id[ID_SIZE] = {};
bool key_ready = false, nvs_ready = false;
bool have_receiver = false;
uint32_t last_poll = 0, last_bind = 0, receiver_at = 0, requested_at = 0;
Result result = Result::Idle;

bool equal(const uint8_t *left, const uint8_t *right, size_t size) {
    volatile uint8_t difference = 0;
    for (size_t index = 0; index < size; ++index) difference |= left[index] ^ right[index];
    return difference == 0;
}

bool tag(const uint8_t *frame, uint8_t *out) {
    const auto *sha256 = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    return sha256 && mbedtls_md_hmac(sha256, key, sizeof(key), frame, TAG_OFFSET, out) == 0;
}

void clear_event(Result next) {
    memset(event_id, 0, sizeof(event_id));
    result = next;
}

void unbind(uint32_t now) {
    close(socket_fd);
    socket_fd = -1;
    bound_ip = IPAddress();
    have_receiver = false;
    last_bind = now - BIND_RETRY_MS;
}

bool bind_receiver(IPAddress ip) {
    const int fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (fd < 0) return false;
    sockaddr_in address = {};
    address.sin_family = AF_INET;
    address.sin_port = htons(PORT);
    address.sin_addr.s_addr = static_cast<uint32_t>(ip);
    if (fcntl(fd, F_SETFL, O_NONBLOCK) < 0 ||
        bind(fd, reinterpret_cast<sockaddr *>(&address), sizeof(address)) < 0) {
        close(fd);
        return false;
    }
    socket_fd = fd;
    bound_ip = ip;
    return true;
}

int nibble(char digit) {
    if (digit >= '0' && digit <= '9') return digit - '0';
    if (digit >= 'a' && digit <= 'f') return digit - 'a' + 10;
    return -1;
}

void handle_poll(uint32_t now) {
    // Read one extra byte to reject an otherwise valid prefix with trailing data.
    uint8_t frame[FRAME_SIZE + 1];
    sockaddr_in sender = {};
    socklen_t sender_size = sizeof(sender);
    auto *address = reinterpret_cast<sockaddr *>(&sender);
    if (recvfrom(socket_fd, frame, sizeof(frame), 0, address, &sender_size) != FRAME_SIZE) return;
    if (memcmp(frame, "BWL1", 4) || frame[4] != POLL) return;
    uint8_t expected[TAG_SIZE];
    if (!tag(frame, expected) || !equal(frame + TAG_OFFSET, expected, TAG_SIZE)) return;
    if (equal(frame + NONCE_OFFSET, last_nonce, ID_SIZE)) return;
    memcpy(last_nonce, frame + NONCE_OFFSET, ID_SIZE);
    receiver_at = now;
    have_receiver = true;

    // A successful Windows launch is acknowledged by the exact pending event.
    // Duplicate/replayed polls cannot create an event or acknowledge a new one.
    if (result == Result::Pending && equal(frame + EVENT_OFFSET, event_id, ID_SIZE)) {
        clear_event(Result::Opened);
    }
    frame[4] = RESPONSE;
    memcpy(frame + EVENT_OFFSET, event_id, sizeof(event_id));
    if (!tag(frame, frame + TAG_OFFSET)) return;
    sendto(socket_fd, frame, FRAME_SIZE, 0, address, sender_size);
}

}  // namespace

void begin() {
    nvs_ready = preferences.begin("bm83win", false);
    key_ready = nvs_ready && preferences.getBytesLength("key") == sizeof(key) &&
                preferences.getBytes("key", key, sizeof(key)) == sizeof(key);
    last_bind = millis() - BIND_RETRY_MS;
}

bool provision(const char *hex_key) {
    if (!nvs_ready || !hex_key || strlen(hex_key) != 2 * sizeof(key)) return false;
    uint8_t next[TAG_SIZE];
    uint8_t nonzero = 0;
    bool valid = true;
    for (size_t index = 0; index < sizeof(next); ++index) {
        const int high = nibble(hex_key[2 * index]);
        const int low = nibble(hex_key[2 * index + 1]);
        if (high < 0 || low < 0) { valid = false; break; }
        next[index] = static_cast<uint8_t>((high << 4) | low);
        nonzero |= next[index];
    }
    const bool stored = valid && nonzero && preferences.putBytes("key", next, sizeof(next)) == sizeof(next);
    if (stored) {
        memcpy(key, next, sizeof(key));
        memset(last_nonce, 0, sizeof(last_nonce));
        have_receiver = false;
        clear_event(Result::Idle);
        key_ready = true;
    }
    mbedtls_platform_zeroize(next, sizeof(next));
    return stored;
}

bool configured() { return key_ready; }

void tick(uint32_t now, bool network_ready) {
    if (result == Result::Pending && now - requested_at >= EVENT_TTL_MS) clear_event(Result::Unconfirmed);
    const IPAddress ip = network_ready && key_ready ? WiFi.localIP() : IPAddress();
    if (bound_ip != IPAddress() && bound_ip != ip) unbind(now);
    if (ip == IPAddress()) return;
    if (bound_ip == IPAddress() && now - last_bind >= BIND_RETRY_MS) {
        last_bind = now;
        if (!bind_receiver(ip)) return;
    }
    if (bound_ip == IPAddress() || now - last_poll < POLL_INTERVAL_MS) return;
    last_poll = now;
    handle_poll(now);
}

bool available(uint32_t now) {
    return have_receiver && now - receiver_at < RECEIVER_FRESH_MS && result != Result::Pending;
}

bool request(uint32_t now) {
    if (!available(now)) return false;
    const uint8_t empty[ID_SIZE] = {};
    do { esp_fill_random(event_id, sizeof(event_id)); } while (equal(event_id, empty, ID_SIZE));
    requested_at = now;
    result = Result::Pending;
    return true;
}

const char *status(uint32_t now) {
    if (!key_ready) return "Windows app launch requires one-time USB setup.";
    if (result == Result::Pending) return "Waiting for Windows to open BM83 Volume Remote...";
    if (result == Result::Opened) return "BM83 Volume Remote opened on Windows.";
    if (result == Result::Unconfirmed) return "Windows app launch was not confirmed. Check the PC.";
    if (!available(now)) return "Windows launcher is offline or the user is signed out.";
    return "Windows is ready to open BM83 Volume Remote.";
}

}  // namespace windows_launch

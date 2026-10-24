// Native CrowPanel artwork worker; see ../lib/artwork_trust/README.md for trust provenance.
#include "artwork.h"
#include "matching.h"
#include "tls_time.h"

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <SD.h>
#include <SPI.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_heap_caps.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>
#include <mbedtls/sha256.h>
#include <time.h>
#include <vector>
#include <lvgl.h>
#include <src/extra/libs/sjpg/tjpgd.h>

#if !LV_USE_SJPG
#error "Artwork worker needs LV_USE_SJPG=1 in its isolated LVGL config"
#endif
#if JD_FORMAT != 0
#error "Artwork RGB565 conversion expects LVGL TJpgDec JD_FORMAT=0 (RGB888)"
#endif

namespace {
constexpr size_t TEXT_MAX = 96, JSON_MAX = 48 * 1024, JPEG_MAX = 128 * 1024;
constexpr size_t JSON_HEAP_MAX = 96 * 1024, CACHE_BYTES = 8 * 1024 * 1024;
constexpr size_t CACHE_ENTRIES = 64, DIRECTORY_SCAN_MAX = 256, SEARCH_LIMIT = 8;
constexpr uint16_t IMAGE_EDGE_MAX = 256;
constexpr uint32_t JOB_MS = 45000, HTTP_GAP_MS = 1100, NEGATIVE_SECONDS = 86400;
const char CACHE_DIR[] = "/bm83-artwork";
const char USER_AGENT[] =
    "BM83-CrowPanel/0.1 (https://github.com/bwedderburn/BM83-ESP32-S3-Nextion)";
const char META_MAGIC_V1[8] = {'B','M','A','R','T','0','0','1'};
// Same on-card layout and keys; v2 marks misses from the revised matcher.
const char META_MAGIC[8] = {'B','M','A','R','T','0','0','2'};

struct Job {
    uint32_t id;
    char title[TEXT_MAX + 1], artist[TEXT_MAX + 1], album[TEXT_MAX + 1];
};
struct Meta {
    char magic[8];
    uint64_t used, negative_until;
    uint8_t negative;
    char group[37];
};
struct Entry { String hash; Meta meta; size_t bytes; };
QueueHandle_t jobs = nullptr;
portMUX_TYPE result_mux = portMUX_INITIALIZER_UNLOCKED;
uint32_t current_id = 0;
bool has_result = false, have_job = false;
bool suspended = false, worker_busy = false;
ArtworkResult pending;
Job last_job = {};
ArtworkConfig configuration;
char ntp_server[64];
SPIClass card_spi(FSPI);
bool sd_ready = false, spi_started = false, ntp_started = false;
uint32_t last_mount_try = 0, last_http = 0;
bool have_http = false;
void clean_incomplete_cache();

bool current(uint32_t id) {
    portENTER_CRITICAL(&result_mux);
    const bool yes = id == current_id && !suspended;
    portEXIT_CRITICAL(&result_mux);
    return yes;
}
bool active(const Job &job, uint32_t started) {
    return current(job.id) && static_cast<uint32_t>(millis() - started) < JOB_MS;
}
bool clock_ready() {
    const time_t now = time(nullptr);
    return now >= 1704067200LL && now < 4102444800LL;
}
uint64_t epoch() { return clock_ready() ? static_cast<uint64_t>(time(nullptr)) : 0; }
class TimeCheckedClient : public WiFiClientSecure {
public:
    int connect(const char *host, uint16_t port, int32_t timeout) override {
        _timeout = timeout;
        return checked_connect(host, port);
    }
    int connect(const char *host, uint16_t port) override {
        _timeout = 4000;
        return checked_connect(host, port);
    }
    // HTTPClient uses the hostname overload. An IP-only connection cannot
    // establish the intended service hostname, so refuse that path entirely.
    int connect(IPAddress, uint16_t) override { return 0; }
    int connect(IPAddress, uint16_t, int32_t) override { return 0; }
private:
    int checked_connect(const char *host, uint16_t port) {
        if (!clock_ready() || !host || !*host || port != 443) return 0;
        // Qualified call avoids re-entering our overloads. Base TLS verifies
        // the trusted issuer chain and DNS hostname; this SDK omits date checks.
        if (!WiFiClientSecure::connect(host, port)) return 0;
        const time_t now = time(nullptr);
        struct tm utc;
        if (!clock_ready() || !gmtime_r(&now, &utc)) { stop(); return 0; }
        const artwork_tls_time::Date current = {
            utc.tm_year + 1900, utc.tm_mon + 1, utc.tm_mday,
            utc.tm_hour, utc.tm_min, utc.tm_sec
        };
        const mbedtls_x509_crt *certificate = getPeerCertificate();
        if (!certificate) { stop(); return 0; }
        unsigned depth = 0;
        for (; certificate; certificate = certificate->next) {
            if (++depth > 16) { stop(); return 0; }
            const auto &from = certificate->valid_from;
            const auto &until = certificate->valid_to;
            if (!artwork_tls_time::certificate_valid_now(
                    {from.year, from.mon, from.day, from.hour, from.min, from.sec},
                    {until.year, until.mon, until.day, until.hour, until.min, until.sec}, current)) {
                log_w("[artwork-tls] host=%s error=certificate-date", host);
                stop();
                return 0;
            }
        }
        // No HTTP request or metadata has been written before this success.
        return 1;
    }
};
void publish(ArtworkResult result) {
    uint16_t *old = nullptr;
    portENTER_CRITICAL(&result_mux);
    if (result.request_id == current_id && !suspended) {
        if (has_result) old = pending.rgb565;
        pending = result;
        has_result = true;
    } else old = result.rgb565;
    portEXIT_CRITICAL(&result_mux);
    artwork_release(old);
}
void mount_card() {
    if (sd_ready) return;
    if (spi_started && static_cast<uint32_t>(millis() - last_mount_try) < 60000) return;
    last_mount_try = millis();
    if (!spi_started) {
        card_spi.begin(12, 13, 11, 10);
        spi_started = true;
    }
    // Explicit false: a failed mount must never erase or format the user's card.
    sd_ready = SD.begin(10, card_spi, 4000000, "/sd", 5, false);
    if (sd_ready && !SD.exists(CACHE_DIR)) sd_ready = SD.mkdir(CACHE_DIR);
    if (sd_ready) {
        File folder = SD.open(CACHE_DIR);
        sd_ready = folder && folder.isDirectory();
        folder.close();
        if (sd_ready) clean_incomplete_cache();
    }
}
String path_for(const String &hash, const char *suffix) {
    return String(CACHE_DIR) + "/aw-" + hash + suffix;
}
bool cache_hash(const Job &job, String &hash) {
    const std::string artist = artwork_matching::normalized_key(job.artist);
    const std::string album = artwork_matching::normalized_key(job.album, true);
    const std::string title = artwork_matching::normalized_key(job.title, true);
    if (artist.empty() || (album.empty() && title.empty())) return false;
    const std::string key = artist + "\x1f" + (album.empty() ? "track:" + title : "album:" + album);
    uint8_t digest[32];
    if (mbedtls_sha256_ret(reinterpret_cast<const uint8_t *>(key.data()), key.size(), digest, 0) != 0) return false;
    static const char HEX_DIGITS[] = "0123456789abcdef";
    char output[65];
    for (size_t i = 0; i < 32; ++i) {
        output[i * 2] = HEX_DIGITS[digest[i] >> 4];
        output[i * 2 + 1] = HEX_DIGITS[digest[i] & 15];
    }
    output[64] = 0;
    hash = output;
    return true;
}
bool managed_name(const String &name, const char *suffix, String &hash) {
    const int slash = name.lastIndexOf('/');
    const String leaf = slash < 0 ? name : name.substring(slash + 1);
    if (leaf.length() != 3 + 64 + strlen(suffix) || !leaf.startsWith("aw-") || !leaf.endsWith(suffix)) return false;
    hash = leaf.substring(3, 67);
    for (size_t i = 0; i < 64; ++i)
        if (!((hash[i] >= '0' && hash[i] <= '9') || (hash[i] >= 'a' && hash[i] <= 'f'))) return false;
    return true;
}
bool read_meta(const String &hash, Meta &meta) {
    File file = SD.open(path_for(hash, ".meta"), FILE_READ);
    return file && file.size() == sizeof(meta) &&
           file.read(reinterpret_cast<uint8_t *>(&meta), sizeof(meta)) == sizeof(meta) &&
           (memcmp(meta.magic, META_MAGIC, sizeof(META_MAGIC)) == 0 ||
            memcmp(meta.magic, META_MAGIC_V1, sizeof(META_MAGIC_V1)) == 0) && meta.negative <= 1 &&
           meta.group[36] == '\0' &&
           (meta.negative || artwork_matching::valid_mbid(meta.group));
}
void clean_incomplete_cache() {
    // The aw-<SHA256> namespace belongs exclusively to this cache. Leave all
    // other names/directories untouched, including inside our cache folder.
    File folder = SD.open(CACHE_DIR);
    size_t scanned = 0;
    while (File file = folder.openNextFile()) {
        if (++scanned > DIRECTORY_SCAN_MAX) break;
        const String name = file.name();
        const bool directory = file.isDirectory();
        file.close();
        if (directory) continue;
        String hash;
        if (managed_name(name, ".jpg.part", hash)) SD.remove(path_for(hash, ".jpg.part"));
        else if (managed_name(name, ".meta.part", hash)) SD.remove(path_for(hash, ".meta.part"));
        else if (managed_name(name, ".jpg", hash)) {
            Meta meta;
            if (!read_meta(hash, meta) || meta.negative) SD.remove(path_for(hash, ".jpg"));
        }
    }
}
bool replace_file(const String &temporary, const String &destination) {
    // FAT rename need not overwrite an existing file. Both paths are private,
    // derived solely from our fixed prefix and SHA256 key, never source text.
    if (SD.exists(destination) && !SD.remove(destination)) return false;
    return SD.rename(temporary, destination);
}
bool write_meta(const String &hash, const Meta &meta) {
    const String temporary = path_for(hash, ".meta.part");
    File file = SD.open(temporary, FILE_WRITE);
    if (!file) return false;
    const bool okay = file.write(reinterpret_cast<const uint8_t *>(&meta), sizeof(meta)) == sizeof(meta);
    file.flush();
    file.close();
    if (!okay) { SD.remove(temporary); return false; }
    return replace_file(temporary, path_for(hash, ".meta"));
}
void remove_entry(const String &hash) {
    // Only called after validating this exact entry's metadata magic.
    SD.remove(path_for(hash, ".jpg"));
    SD.remove(path_for(hash, ".meta"));
}
bool cache_room(const String &protected_hash, size_t incoming) {
    File folder = SD.open(CACHE_DIR);
    if (!folder || !folder.isDirectory()) return false;
    std::vector<Entry> entries;
    entries.reserve(CACHE_ENTRIES + 1);
    size_t total = 0, scanned = 0;
    while (File file = folder.openNextFile()) {
        if (++scanned > DIRECTORY_SCAN_MAX) return false;  // Preserve unexpected contents.
        String hash;
        const bool candidate = !file.isDirectory() && managed_name(file.name(), ".meta", hash);
        file.close();
        Meta meta;
        if (!candidate || !read_meta(hash, meta) || hash == protected_hash) continue;
        File image = SD.open(path_for(hash, ".jpg"), FILE_READ);
        const size_t size = image ? image.size() : 0;
        image.close();
        if (size > JPEG_MAX) { remove_entry(hash); continue; }
        entries.push_back({hash, meta, size});
        total += size;
        if (entries.size() > CACHE_ENTRIES + 1) return false;
    }
    folder.close();
    while (entries.size() + 1 > CACHE_ENTRIES || total + incoming > CACHE_BYTES) {
        if (entries.empty()) return false;
        size_t oldest = 0;
        for (size_t i = 1; i < entries.size(); ++i)
            if (entries[i].meta.used < entries[oldest].meta.used) oldest = i;
        remove_entry(entries[oldest].hash);
        total -= entries[oldest].bytes;
        entries.erase(entries.begin() + oldest);
    }
    return true;
}
bool store_cache(const String &hash, const char *group, const uint8_t *jpeg, size_t size, bool negative) {
    if (!sd_ready || (!negative && (!jpeg || size == 0 || size > JPEG_MAX)) || !cache_room(hash, size)) return false;
    Meta meta = {};
    memcpy(meta.magic, META_MAGIC, sizeof(META_MAGIC));
    meta.used = epoch();
    meta.negative = negative;
    meta.negative_until = negative && meta.used ? meta.used + NEGATIVE_SECONDS : 0;
    if (group) strncpy(meta.group, group, 36);
    if (!negative) {
        const String temporary = path_for(hash, ".jpg.part");
        File file = SD.open(temporary, FILE_WRITE);
        if (!file) return false;
        const bool okay = file.write(jpeg, size) == size;
        file.flush();
        file.close();
        if (!okay) { SD.remove(temporary); return false; }
        if (!replace_file(temporary, path_for(hash, ".jpg"))) return false;
    } else {
        // This hash belongs to our managed entry; no other card data is touched.
        Meta existing;
        if (read_meta(hash, existing)) SD.remove(path_for(hash, ".jpg"));
    }
    return write_meta(hash, meta);
}
struct JpegSource {
    const uint8_t *data;
    size_t length, offset;
    uint16_t *pixels;
    uint16_t width, height;
    const Job *job;
    uint32_t started;
};
size_t jpeg_input(JDEC *decoder, uint8_t *buffer, size_t count) {
    auto &source = *static_cast<JpegSource *>(decoder->device);
    if (!active(*source.job, source.started)) return 0;
    const size_t remaining = source.length - source.offset;
    if (count > remaining) count = remaining;
    if (buffer) memcpy(buffer, source.data + source.offset, count);
    source.offset += count;
    return count;
}
int jpeg_output(JDEC *decoder, void *data, JRECT *rect) {
    auto &source = *static_cast<JpegSource *>(decoder->device);
    if (!active(*source.job, source.started) || rect->right >= source.width || rect->bottom >= source.height) return 0;
    const auto *rgb = static_cast<const uint8_t *>(data);  // LVGL TJpgDec uses JD_FORMAT=0.
    for (uint16_t y = rect->top; y <= rect->bottom; ++y) {
        for (uint16_t x = rect->left; x <= rect->right; ++x) {
            const uint16_t pixel = ((rgb[0] & 0xF8) << 8) | ((rgb[1] & 0xFC) << 3) | (rgb[2] >> 3);
            source.pixels[static_cast<size_t>(y) * source.width + x] = pixel;
            rgb += 3;
        }
    }
    return 1;
}
bool decode_jpeg(const Job &job, uint32_t started, const uint8_t *data, size_t length, ArtworkResult &result) {
    if (length < 4 || length > JPEG_MAX || data[0] != 0xFF || data[1] != 0xD8) return false;
    void *work = heap_caps_malloc(4096, MALLOC_CAP_8BIT);
    if (!work) return false;
    JpegSource source = {data, length, 0, nullptr, 0, 0, &job, started};
    JDEC decoder;
    JRESULT status = jd_prepare(&decoder, jpeg_input, work, 4096, &source);
    if (status == JDR_OK && decoder.width > 0 && decoder.height > 0 &&
        decoder.width <= IMAGE_EDGE_MAX && decoder.height <= IMAGE_EDGE_MAX) {
        source.width = decoder.width;
        source.height = decoder.height;
        source.pixels = static_cast<uint16_t *>(heap_caps_malloc(
            static_cast<size_t>(source.width) * source.height * 2, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
        if (source.pixels) status = jd_decomp(&decoder, jpeg_output, 0);
        else status = JDR_MEM1;
    } else status = JDR_FMT1;
    heap_caps_free(work);
    if (status != JDR_OK) { artwork_release(source.pixels); return false; }
    result.rgb565 = source.pixels;
    result.width = source.width;
    result.height = source.height;
    return true;
}
bool cached(const Job &job, uint32_t started, const String &hash, ArtworkResult &result) {
    if (!sd_ready) return false;
    Meta meta;
    if (!read_meta(hash, meta)) return false;
    if (meta.negative) {
        // Legacy entries still belong to this cache for cleanup/eviction,
        // but an old matcher's miss must not hide newly supported artwork.
        if (memcmp(meta.magic, META_MAGIC, sizeof(META_MAGIC)) != 0) return false;
        if (!epoch() || epoch() >= meta.negative_until) return false;
        result.status = ArtworkStatus::NoMatch;
        result.from_cache = true;
        return true;
    }
    File file = SD.open(path_for(hash, ".jpg"), FILE_READ);
    if (!file || file.size() == 0 || file.size() > JPEG_MAX) return false;
    const size_t size = file.size();
    auto *jpeg = static_cast<uint8_t *>(heap_caps_malloc(size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!jpeg) return false;
    const bool okay = file.read(jpeg, size) == size;
    file.close();
    const bool decoded = okay && decode_jpeg(job, started, jpeg, size, result);
    heap_caps_free(jpeg);
    if (!decoded) return false;
    result.status = ArtworkStatus::Ready;
    result.from_cache = true;
    memcpy(result.release_group, meta.group, sizeof(meta.group));
    if (epoch()) { meta.used = epoch(); write_meta(hash, meta); }
    return true;
}
String request_host(const String &url) {
    const int slash = url.indexOf('/', 8);
    String host = slash < 0 ? url.substring(8) : url.substring(8, slash);
    host.toLowerCase();
    return host;
}
bool archive_host(const String &host) {
    return host == "archive.org" || host.endsWith(".archive.org");
}
bool allowed_url(String &url) {
    // CAA currently documents HTTP redirect URLs; upgrade before any request.
    if (url.startsWith("http://")) url = "https://" + url.substring(7);
    if (!url.startsWith("https://") || url.length() > 1536) return false;
    for (size_t i = 0; i < url.length(); ++i) if (static_cast<uint8_t>(url[i]) < 33 || url[i] == '\\') return false;
    const String host = request_host(url);
    if (host.indexOf('@') >= 0 || host.indexOf(':') >= 0 || host.indexOf('%') >= 0 ||
        host.indexOf('?') >= 0 || host.indexOf('#') >= 0) return false;
    return host == "musicbrainz.org" || host == "coverartarchive.org" || archive_host(host);
}
class BodySink : public Stream {
public:
    BodySink(uint8_t *buffer, size_t capacity, const Job &job, uint32_t started)
        : buffer_(buffer), capacity_(capacity), job_(job), started_(started) {}
    size_t write(uint8_t value) override { return write(&value, 1); }
    size_t write(const uint8_t *data, size_t length) override {
        if (!active(job_, started_) || length > capacity_ - used_) { failed = true; return 0; }
        memcpy(buffer_ + used_, data, length);
        used_ += length;
        return length;
    }
    int available() override { return 0; }
    int read() override { return -1; }
    int peek() override { return -1; }
    void flush() override {}
    size_t size() const { return used_; }
    bool failed = false;
private:
    uint8_t *buffer_;
    size_t capacity_, used_ = 0;
    const Job &job_;
    uint32_t started_;
};
int fetch(const Job &job, uint32_t started, String url, uint8_t *buffer,
          size_t capacity, size_t &length, bool json) {
    length = 0;
    for (unsigned redirects = 0; redirects <= 3; ++redirects) {
        if (!allowed_url(url) || !active(job, started) || WiFi.status() != WL_CONNECTED) return -1;
        while (have_http && static_cast<uint32_t>(millis() - last_http) < HTTP_GAP_MS) {
            if (!active(job, started)) return -1;
            vTaskDelay(pdMS_TO_TICKS(20));
        }
        TimeCheckedClient client;
        const String host = request_host(url);  // Already passed the strict allowlist.
        // archive.org sends a redundant cross-signed G2 -> legacy Class2 tail.
        // The old compressed-bundle callback cannot terminate that chain at
        // its trusted G2 anchor. Ordinary PEM trust lets mbedTLS build the
        // shorter valid path; the anchor is from the same Mozilla root set.
        // CDN subdomains can use different issuers; retain their full bundle.
        if (host == "archive.org" && configuration.archive_ca_pem) client.setCACert(configuration.archive_ca_pem);
        else if (configuration.ca_bundle) client.setCACertBundle(configuration.ca_bundle);
        else if (configuration.ca_pem) client.setCACert(configuration.ca_pem);
        else return -1;
        client.setHandshakeTimeout(4);
        client.setTimeout(6);
        HTTPClient http;
        http.setConnectTimeout(4000);
        http.setTimeout(6000);
        http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
        http.setUserAgent(USER_AGENT);
        const char *headers[] = {"Location", "Content-Type"};
        http.collectHeaders(headers, 2);
        if (!http.begin(client, url)) return -1;
        last_http = millis();
        have_http = true;
        const int code = http.GET();
        // Bound diagnostics to provider hostname/stage/status only. URLs and
        // query strings contain track text and must not enter this log.
        log_i("[artwork-fetch] stage=%s host=%s http=%d redirect=%u",
              json ? "metadata" : "image", host.c_str(), code, redirects);
        if (code == 301 || code == 302 || code == 303 || code == 307 || code == 308) {
            String next = http.header("Location");
            if (next.startsWith("/")) {
                const int slash = url.indexOf('/', 8);
                next = (slash < 0 ? url : url.substring(0, slash)) + next;
            }
            http.end();
            if (redirects == 3 || !allowed_url(next)) return -1;
            url = next;
            continue;
        }
        if (code != 200) { http.end(); return code; }
        const int size = http.getSize();
        String type = http.header("Content-Type");
        type.toLowerCase();
        const bool type_ok = json ? type.startsWith("application/json")
                                  : type.startsWith("image/jpeg");
        if (!type_ok || (size >= 0 && static_cast<size_t>(size) > capacity)) { http.end(); return -2; }
        BodySink sink(buffer, capacity, job, started);
        const int copied = http.writeToStream(&sink);  // Handles chunked responses.
        http.end();
        if (copied < 0 || sink.failed || !active(job, started)) return -1;
        length = sink.size();
        return 200;
    }
    return -1;
}
class JsonBudget : public ArduinoJson::Allocator {
public:
    void *allocate(size_t size) override {
        if (size > JSON_HEAP_MAX - used_) return nullptr;
        auto *memory = static_cast<Allocation *>(heap_caps_malloc(size + sizeof(Allocation),
            MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
        if (!memory) return nullptr;
        memory->size = size;
        used_ += size;
        return memory + 1;
    }
    void deallocate(void *pointer) override {
        if (!pointer) return;
        auto *memory = static_cast<Allocation *>(pointer) - 1;
        used_ -= memory->size;
        heap_caps_free(memory);
    }
    void *reallocate(void *pointer, size_t size) override {
        if (!pointer) return allocate(size);
        if (!size) { deallocate(pointer); return nullptr; }
        auto *old = static_cast<Allocation *>(pointer) - 1;
        if (size > JSON_HEAP_MAX - (used_ - old->size)) return nullptr;
        const size_t previous = old->size;
        auto *memory = static_cast<Allocation *>(heap_caps_realloc(old, size + sizeof(Allocation),
            MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
        if (!memory) return nullptr;
        memory->size = size;
        used_ = used_ - previous + size;
        return memory + 1;
    }
private:
    struct alignas(8) Allocation { size_t size; };
    size_t used_ = 0;
};
const char *text(JsonVariantConst value) {
    if (!value.is<const char *>()) return nullptr;
    const JsonString string = value.as<JsonString>();
    const char *data = string.c_str();
    return data && strlen(data) == string.size() ? data : nullptr;
}
unsigned score(JsonVariantConst value) {
    if (value.is<unsigned>()) {
        const unsigned number = value.as<unsigned>();
        return number <= 100 ? number : 0;
    }
    const char *digits = text(value);
    if (!digits || !*digits || strlen(digits) > 3) return 0;
    unsigned result = 0;
    for (; *digits; ++digits) {
        if (*digits < '0' || *digits > '9') return 0;
        result = result * 10 + (*digits - '0');
    }
    return result <= 100 ? result : 0;
}
const char *credited_artist(JsonArrayConst credit) {
    if (credit.size() != 1) return nullptr;
    const char *name = text(credit[0]["name"]);
    return name ? name : text(credit[0]["artist"]["name"]);
}
bool compilation(JsonVariantConst group) {
    for (JsonVariantConst item : group["secondary-types"].as<JsonArrayConst>()) {
        const char *type = text(item);
        if (type && strcmp(type, "Compilation") == 0) return true;
    }
    return false;
}
bool nonstudio_group(JsonVariantConst group) {
    for (JsonVariantConst item : group["secondary-types"].as<JsonArrayConst>()) {
        const char *type = text(item);
        if (type && (strcmp(type, "Live") == 0 || strcmp(type, "Remix") == 0 || strcmp(type, "DJ-mix") == 0)) return true;
    }
    return false;
}
String url_encode(const String &input) {
    static const char HEX_DIGITS[] = "0123456789ABCDEF";
    String output;
    output.reserve(input.length() * 3);
    for (size_t i = 0; i < input.length(); ++i) {
        const uint8_t c = input[i];
        if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
            (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' || c == '~') output += static_cast<char>(c);
        else { output += '%'; output += HEX_DIGITS[c >> 4]; output += HEX_DIGITS[c & 15]; }
    }
    return output;
}
String quote(const char *input) {
    String output = "\"";
    for (; *input; ++input) {
        if (*input == '"' || *input == '\\') output += '\\';
        output += *input;
    }
    return output + '"';
}
ArtworkStatus resolve_search(const Job &job, uint32_t started, const String &search,
                             char group[37], bool &zero_results) {
    zero_results = false;
    const bool album = job.album[0] != 0;
    const artwork_matching::Query query = {job.artist, job.album, job.title};
    const String url = String("https://musicbrainz.org/ws/2/") + (album ? "release-group/" : "recording/") +
                       "?fmt=json&limit=8&query=" + url_encode(search);
    auto *body = static_cast<uint8_t *>(heap_caps_malloc(JSON_MAX + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!body) return ArtworkStatus::NetworkError;
    size_t length;
    const int code = fetch(job, started, url, body, JSON_MAX, length, true);
    if (code != 200) { heap_caps_free(body); return ArtworkStatus::NetworkError; }
    body[length] = 0;
    JsonBudget allocator;
    JsonDocument document(&allocator);
    const DeserializationError error = deserializeJson(document, body, length, DeserializationOption::NestingLimit(12));
    heap_caps_free(body);
    if (error || document.overflowed()) return ArtworkStatus::NetworkError;
    if (!document["count"].is<unsigned>() ||
        !document[album ? "release-groups" : "recordings"].is<JsonArray>())
        return ArtworkStatus::NetworkError;
    if (document["count"].as<unsigned>() > SEARCH_LIMIT)
        return ArtworkStatus::NoMatch;  // Truncated search cannot establish uniqueness.
    if (document[album ? "release-groups" : "recordings"].as<JsonArrayConst>().size() !=
        document["count"].as<unsigned>()) return ArtworkStatus::NetworkError;
    // Only an HTTP200, valid and complete empty result permits one fallback.
    // Selection failures, ambiguity, truncation and HTTP/parse errors do not.
    zero_results = document["count"].as<unsigned>() == 0;
    artwork_matching::Candidate candidates[artwork_matching::MAX_CANDIDATES];
    size_t count = 0;
    for (JsonVariantConst item : document[album ? "release-groups" : "recordings"].as<JsonArrayConst>()) {
        const unsigned rank = score(item["score"]);
        if (album) {
            if (count == artwork_matching::MAX_CANDIDATES) return ArtworkStatus::NoMatch;
            JsonArrayConst credits = item["artist-credit"].as<JsonArrayConst>();
            candidates[count++] = {credited_artist(credits), text(item["title"]), nullptr, text(item["id"]),
                                    rank, static_cast<unsigned>(credits.size()), compilation(item)};
        } else {
            // Recording search embeds releases. Require their artist credit and
            // release-group identity too; absent fields keep the placeholder.
            JsonArrayConst recording_credit = item["artist-credit"].as<JsonArrayConst>();
            const char *recording_artist = credited_artist(recording_credit);
            const char *disambiguation = text(item["disambiguation"]);
            if (disambiguation && *disambiguation) continue;
            if (!recording_artist || artwork_matching::normalized_key(recording_artist) !=
                                     artwork_matching::normalized_key(job.artist)) continue;
            for (JsonVariantConst release : item["releases"].as<JsonArrayConst>()) {
                if (count == artwork_matching::MAX_CANDIDATES) return ArtworkStatus::NoMatch;
                JsonArrayConst credit = release["artist-credit"].as<JsonArrayConst>();
                JsonVariantConst release_group = release["release-group"];
                if (nonstudio_group(release_group)) continue;
                candidates[count++] = {credited_artist(credit), text(release["title"]), text(item["title"]),
                                        text(release_group["id"]), rank,
                                        static_cast<unsigned>(credit.size()), compilation(release_group)};
            }
        }
    }
    const auto selection = album ? artwork_matching::select_album(query, candidates, count)
                                 : artwork_matching::select_recording(query, candidates, count);
    if (selection.outcome != artwork_matching::Outcome::Matched) return ArtworkStatus::NoMatch;
    strncpy(group, candidates[selection.index].art_id, 36);
    group[36] = 0;
    return ArtworkStatus::Ready;
}
ArtworkStatus resolve(const Job &job, uint32_t started, char group[37]) {
    const bool album = job.album[0] != 0;
    const artwork_matching::Query query = {job.artist, job.album, job.title};
    const std::string target = artwork_matching::normalized_key(album ? job.album : job.title, true);
    if (target.empty()) return ArtworkStatus::NoMatch;
    const String strict = (album ? "releasegroup:" + quote(target.c_str()) : "recording:" + quote(target.c_str())) +
                          " AND artist:" + quote(job.artist);
    bool zero_results = false;
    const ArtworkStatus status = resolve_search(job, started, strict, group, zero_results);
    if (status != ArtworkStatus::NoMatch || !zero_results || !album) return status;
    std::string fallback;
    if (!artwork_matching::album_fallback_query(query, fallback)) return status;
    log_i("[artwork-fetch] metadata-fallback=album-punctuation");
    // Same count/score/artist/identity/unique-group validation and HTTP rate
    // limit as the strict search. There is no third search or recursive retry.
    return resolve_search(job, started, String(fallback.c_str()), group, zero_results);
}
ArtworkResult process(const Job &job) {
    ArtworkResult result;
    result.request_id = job.id;
    const uint32_t started = millis();
    mount_card();
    result.sd_ready = sd_ready;
    String hash;
    if (!cache_hash(job, hash)) return result;
    if (cached(job, started, hash, result)) return result;
    if (WiFi.status() != WL_CONNECTED) { result.status = ArtworkStatus::Offline; return result; }
    if (!configuration.ca_pem && !configuration.ca_bundle) {
        result.status = ArtworkStatus::TrustUnavailable;
        return result;
    }
    if (!ntp_started) {
        configTime(0, 0, ntp_server);
        ntp_started = true;
    }
    if (!clock_ready()) { result.status = ArtworkStatus::ClockUnavailable; return result; }
    result.status = resolve(job, started, result.release_group);
    if (!active(job, started)) { result.status = ArtworkStatus::NetworkError; return result; }
    if (result.status == ArtworkStatus::NoMatch) {
        store_cache(hash, nullptr, nullptr, 0, true);
        return result;
    }
    if (result.status != ArtworkStatus::Ready) return result;
    auto *jpeg = static_cast<uint8_t *>(heap_caps_malloc(JPEG_MAX, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!jpeg) { result.status = ArtworkStatus::InvalidImage; return result; }
    size_t length;
    const String url = String("https://coverartarchive.org/release-group/") + result.release_group + "/front-250";
    const int code = fetch(job, started, url, jpeg, JPEG_MAX, length, false);
    if (code == 404) {
        result.status = ArtworkStatus::NoMatch;
        store_cache(hash, nullptr, nullptr, 0, true);
    } else if (code == 200 && decode_jpeg(job, started, jpeg, length, result)) {
        result.status = ArtworkStatus::Ready;
        if (active(job, started)) store_cache(hash, result.release_group, jpeg, length, false);
    } else result.status = code == 200 ? ArtworkStatus::InvalidImage : ArtworkStatus::NetworkError;
    heap_caps_free(jpeg);
    return result;
}
void worker(void *) {
    Job job = {};
    bool retry = false;
    uint32_t retry_at = 0;
    for (;;) {
        const bool received = xQueueReceive(jobs, &job, pdMS_TO_TICKS(500)) == pdTRUE;
        if (!received && (!retry || !current(job.id) ||
            static_cast<int32_t>(millis() - retry_at) < 0)) continue;
        portENTER_CRITICAL(&result_mux);
        if (suspended || job.id != current_id) {
            portEXIT_CRITICAL(&result_mux);
            retry = false;
            continue;
        }
        worker_busy = true;
        portEXIT_CRITICAL(&result_mux);
        ArtworkResult result = process(job);
        portENTER_CRITICAL(&result_mux);
        worker_busy = false;
        portEXIT_CRITICAL(&result_mux);
        retry = result.status == ArtworkStatus::Offline || result.status == ArtworkStatus::ClockUnavailable ||
                result.status == ArtworkStatus::NetworkError;
        // A saved AP may still be joining when the first metadata arrives.
        // Poll local readiness promptly; actual HTTP failures keep backoff.
        retry_at = millis() + ((result.status == ArtworkStatus::Offline ||
                               result.status == ArtworkStatus::ClockUnavailable) ? 5000 : 60000);
        publish(result);
    }
}
bool copy_text(char *out, const char *input) {
    if (!input) { out[0] = 0; return true; }
    const size_t length = strnlen(input, TEXT_MAX + 1);
    if (length > TEXT_MAX) { out[0] = 0; return false; }
    memcpy(out, input, length + 1);
    return true;
}
}  // namespace

bool artwork_begin(const ArtworkConfig &config) {
    if (jobs) return true;
    configuration = config;
    const char *server = config.ntp_server ? config.ntp_server : "pool.ntp.org";
    if (strlen(server) >= sizeof(ntp_server)) return false;
    strcpy(ntp_server, server);
    jobs = xQueueCreate(1, sizeof(Job));
    if (!jobs) return false;
    if (xTaskCreate(worker, "artwork", 12288, nullptr, 1, nullptr) != pdPASS) {
        vQueueDelete(jobs);
        jobs = nullptr;
        return false;
    }
    return true;
}
uint32_t artwork_request(const char *title, const char *artist, const char *album) {
    if (!jobs) return 0;
    Job job = {};
    const bool valid = copy_text(job.title, title) && copy_text(job.artist, artist) && copy_text(job.album, album);
    if (!valid) memset(&job, 0, sizeof(job));
    uint16_t *obsolete = nullptr;
    bool enqueue;
    portENTER_CRITICAL(&result_mux);
    if (have_job && strcmp(last_job.title, job.title) == 0 &&
        strcmp(last_job.artist, job.artist) == 0 && strcmp(last_job.album, job.album) == 0) {
        const uint32_t id = current_id;
        portEXIT_CRITICAL(&result_mux);
        return id;
    }
    if (++current_id == 0) ++current_id;
    job.id = current_id;
    last_job = job;
    have_job = true;
    enqueue = !suspended;
    if (has_result) { obsolete = pending.rgb565; has_result = false; pending.rgb565 = nullptr; }
    portEXIT_CRITICAL(&result_mux);
    artwork_release(obsolete);
    if (enqueue) xQueueOverwrite(jobs, &job);
    return job.id;
}
bool artwork_poll(ArtworkResult &out) {
    bool got = false;
    bool received = false;
    ArtworkResult result;
    portENTER_CRITICAL(&result_mux);
    if (has_result) {
        result = pending;
        pending.rgb565 = nullptr;
        has_result = false;
        received = true;
        got = result.request_id == current_id && !suspended;
    }
    portEXIT_CRITICAL(&result_mux);
    if (got) out = result;
    else if (received) artwork_release(result.rgb565);
    return got;
}
void artwork_release(uint16_t *pixels) { heap_caps_free(pixels); }

bool artwork_prepare_sleep() {
    if (!jobs) return true;
    uint16_t *obsolete = nullptr;
    portENTER_CRITICAL(&result_mux);
    suspended = true;
    const bool idle = !worker_busy;
    if (has_result) {
        obsolete = pending.rgb565;
        pending.rgb565 = nullptr;
        has_result = false;
    }
    portEXIT_CRITICAL(&result_mux);
    // A worker that already dequeued a job checks suspended under the same
    // lock before claiming it. No future job can begin while this is set.
    xQueueReset(jobs);
    artwork_release(obsolete);
    return idle;
}

void artwork_resume() {
    if (!jobs) return;
    portENTER_CRITICAL(&result_mux);
    suspended = false;
    if (++current_id == 0) ++current_id;  // Retire any pre-sleep retry job.
    have_job = false;  // Identical metadata must create a fresh request now.
    portEXIT_CRITICAL(&result_mux);
}

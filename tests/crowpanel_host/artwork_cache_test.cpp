#include "artwork.h"
#include "matching.h"

#include <algorithm>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <map>
#include <string>
#include <vector>

using String = std::string;
using Bytes = std::vector<uint8_t>;

// The generated includes contain the actual production types, constants,
// path builder and reader. Only SD, time, allocation and JPEG decoding are
// substituted; this test concerns cache compatibility rather than codecs.
#include "artwork_cache_types.inc"

static const int FILE_READ = 0, MALLOC_CAP_SPIRAM = 0, MALLOC_CAP_8BIT = 0;
static const char HASH[] = "bd14ed114fffe365b2baf8225d8d33c4db106065f4d70bcc5c591157fdc0b3ca9";
static const char GROUP[] = "7d901f1e-090c-437f-8e70-fdade71ba1bb";
static const Bytes JPEG = {0xff, 0xd8, 0xff, 0xd9};
static std::map<String, Bytes> files;
static std::map<String, size_t> read_limits;
static std::vector<String> opened;
static unsigned decoded = 0, allocations = 0, releases = 0;
static bool allocation_fails = false, decode_fails = false, sd_ready = true;
static uint64_t now = 100;

struct File {
    Bytes bytes;
    size_t offset = 0, limit = static_cast<size_t>(-1);
    bool exists = false;
    explicit operator bool() const { return exists; }
    size_t size() const { return bytes.size(); }
    size_t read(uint8_t *out, size_t length) {
        length = std::min(length, std::min(limit, bytes.size() - offset));
        if (length) std::memcpy(out, bytes.data() + offset, length);
        offset += length;
        return length;
    }
    void close() {}
};
struct SDClass {
    File open(const String &path, int) {
        opened.push_back(path);
        File file;
        const auto found = files.find(path);
        if (found != files.end()) {
            file.bytes = found->second;
            file.exists = true;
        }
        if (read_limits.count(path)) file.limit = read_limits[path];
        return file;
    }
} SD;

uint64_t epoch() { return now; }
void *heap_caps_malloc(size_t size, int) {
    if (allocation_fails) return nullptr;
    ++allocations;
    return std::malloc(size);
}
void heap_caps_free(void *memory) {
    if (memory) ++releases;
    std::free(memory);
}
bool decode_jpeg(const Job &, uint32_t, const uint8_t *data, size_t size, ArtworkResult &result) {
    ++decoded;
    if (decode_fails || size != JPEG.size() || std::memcmp(data, JPEG.data(), size)) return false;
    result.width = result.height = 1;
    return true;
}
bool write_meta(const String &hash, const Meta &meta) {
    const auto *bytes = reinterpret_cast<const uint8_t *>(&meta);
    files[path_for(hash, ".meta")] = Bytes(bytes, bytes + sizeof(meta));
    return true;
}

#include "artwork_cache_runtime.inc"

static Meta seed(unsigned version, bool negative) {
    files.clear();
    read_limits.clear();
    opened.clear();
    now = 100;
    decoded = allocations = releases = 0;
    allocation_fails = decode_fails = false;
    sd_ready = true;
    Meta meta = {};
    // These are historical on-card bytes, independently of today's magic.
    const char prefix[] = "BMART00";
    std::memcpy(meta.magic, prefix, 7);
    meta.magic[7] = static_cast<char>('0' + version);
    meta.used = 50;
    meta.negative_until = 500;
    meta.negative = negative;
    if (!negative) std::strcpy(meta.group, GROUP);
    write_meta(HASH, meta);
    if (!negative) files[path_for(HASH, ".jpg")] = JPEG;
    files["/holiday-photo.jpg"] = {9, 8, 7};
    files["/bm83-artwork/holiday-photo.jpg"] = {6, 5, 4};
    files["/bm83-artwork/notes.txt"] = {3, 2, 1};
    return meta;
}

static bool load(ArtworkResult &result) {
    const Job job = {};
    const bool hit = cached(job, 0, HASH, result);
    assert(allocations == releases);
    return hit;
}

static void negative_migration() {
    for (unsigned version : {1U, 2U, 3U, 4U, 5U}) {
        seed(version, true);
        const auto before = files;
        Meta meta;
        ArtworkResult result;
        assert(read_meta(HASH, meta));  // Still managed for cleanup/eviction.
        assert(!load(result));          // An old miss must try the alias-aware matcher.
        assert(files == before && decoded == 0);
    }
    seed(6, true);
    ArtworkResult result;
    const auto before = files;
    now = 499;
    assert(load(result) && result.from_cache && result.status == ArtworkStatus::NoMatch);
    assert(files == before && decoded == 0);
    now = 500;
    assert(!load(result));  // Exact expiry is no longer a hit.
    now = 0;
    assert(!load(result));  // Unsynchronized time must not hide fresh artwork.
}

static void positive_migration() {
    const String meta_path = String("/bm83-artwork/aw-") + HASH + ".meta";
    const String image_path = String("/bm83-artwork/aw-") + HASH + ".jpg";
    for (unsigned version : {1U, 2U, 3U, 4U, 5U, 6U}) {
        seed(version, false);
        const auto before = files;
        now = 0;  // Positive covers must remain usable without network time.
        ArtworkResult result;
        assert(load(result));
        assert(result.from_cache && result.status == ArtworkStatus::Ready);
        assert(std::strcmp(result.release_group, GROUP) == 0);
        assert(result.width == 1 && result.height == 1 && decoded == 1);
        assert(files == before);
        assert(opened.size() == 2 && opened[0] == meta_path && opened[1] == image_path);

        now = 101;
        assert(load(result));
        Meta updated;
        assert(read_meta(HASH, updated));
        assert(updated.used == 101 && updated.magic[7] == static_cast<char>('0' + version));
        assert(std::strcmp(updated.group, GROUP) == 0 && !updated.negative);
        // Only access time may rewrite the existing metadata file. Its key,
        // image and every unrelated file, including inside CACHE_DIR, survive.
        auto unchanged = files;
        unchanged[meta_path] = before.at(meta_path);
        assert(unchanged == before);
    }
}

static void damaged_metadata() {
    for (size_t size : {sizeof(Meta) - 1, sizeof(Meta) + 1}) {
        seed(5, false);
        files[path_for(HASH, ".meta")].resize(size);
        const auto before = files;
        Meta meta;
        ArtworkResult result;
        assert(!read_meta(HASH, meta) && !load(result));
        assert(files == before && decoded == 0);
    }
    seed(5, false);
    read_limits[path_for(HASH, ".meta")] = sizeof(Meta) - 1;
    ArtworkResult result;
    assert(!load(result) && decoded == 0);

    for (unsigned damage = 0; damage < 5; ++damage) {
        Meta meta = seed(5, false);
        if (damage == 0) meta.magic[7] = '7';
        if (damage == 1) meta.negative = 2;
        if (damage == 2) meta.group[0] = 'z';
        if (damage == 3) meta.group[36] = 'x';
        if (damage == 4) std::memset(meta.group, '0', 36);
        write_meta(HASH, meta);
        const auto before = files;
        assert(!read_meta(HASH, meta) && !load(result));
        assert(files == before && decoded == 0);
    }
    Meta meta = seed(5, false);
    std::strcpy(meta.group, "00000000-0000-0000-0000-000000000000");
    write_meta(HASH, meta);
    assert(!read_meta(HASH, meta) && !load(result));
}

static void damaged_images_and_io() {
    ArtworkResult result;
    for (size_t size : {size_t(0), JPEG_MAX + 1}) {
        seed(5, false);
        files[path_for(HASH, ".jpg")].resize(size);
        const auto before = files;
        assert(!load(result) && files == before && decoded == 0);
    }
    seed(5, false);
    files.erase(path_for(HASH, ".jpg"));
    assert(!load(result) && decoded == 0);
    seed(5, false);
    read_limits[path_for(HASH, ".jpg")] = JPEG.size() - 1;
    assert(!load(result) && decoded == 0);
    seed(5, false);
    allocation_fails = true;
    assert(!load(result) && decoded == 0);
    seed(5, false);
    decode_fails = true;
    assert(!load(result) && decoded == 1);
    seed(5, false);
    sd_ready = false;
    assert(!load(result) && opened.empty());
}

int main() {
    static_assert(sizeof(Meta) == 64, "Existing on-card metadata layout changed");
    assert(std::memcmp(META_MAGIC, "BMART006", sizeof(META_MAGIC)) == 0);
    negative_migration();
    positive_migration();
    damaged_metadata();
    damaged_images_and_io();
    std::cout << "PASS: cache migration, offline covers, identity and damaged-record rejection\n";
}

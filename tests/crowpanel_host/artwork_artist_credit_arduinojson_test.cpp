// Optional real-library check, invoked by tools/check_artist_credit.py with
// the already installed, version-checked ArduinoJson dependency. No hardware.
#include <ArduinoJson.h>
#include "artist_aliases.h"

#include <cassert>
#include <fstream>
#include <iostream>
#include <sstream>

#include "artwork_artist_credit.inc"

static const char REQUESTED[] = "Jakub Zytecki";
static const char OWNER[] = "1cbd7faf-938f-4c10-aeb1-426e83d38407";

static JsonArray credits(JsonDocument &doc) {
    return doc["release-groups"][0]["artist-credit"].as<JsonArray>();
}
static JsonObject artist(JsonDocument &doc) { return credits(doc)[0]["artist"].as<JsonObject>(); }
static void reset(JsonDocument &doc, const std::string &payload) {
    doc.clear();
    assert(!deserializeJson(doc, payload));
}
static const char *choose(JsonDocument &doc) { return credited_artist(credits(doc), REQUESTED); }

int main(int argc, char **argv) {
    assert(argc == 2);
    std::ifstream input(argv[1]);
    assert(input);
    std::ostringstream buffer; buffer << input.rdbuf();
    const std::string payload = buffer.str();
    JsonDocument doc;
    reset(doc, payload);
    assert(choose(doc) && strcmp(choose(doc), REQUESTED) == 0);
    JsonVariant group = doc["release-groups"][0];
    const artwork_matching::Candidate candidate = {choose(doc), text(group["title"]), nullptr,
        text(group["id"]), group["score"].as<unsigned>(), static_cast<unsigned>(credits(doc).size()),
        false, text(group["primary-type"])};
    assert(artwork_matching::select_album({REQUESTED, "Nothing Lasts, Nothing's Lost", ""},
        &candidate, 1).outcome == artwork_matching::Outcome::Matched);

    artist(doc)["aliases"][0]["type"] = 42;
    assert(!choose(doc));
    artist(doc)["aliases"][0]["type"] = "Unknown type";
    assert(!choose(doc));
    artist(doc)["aliases"][0]["type"] = nullptr;
    assert(choose(doc));
    artist(doc)["aliases"][0]["type"] = "Search hint";
    artist(doc)["aliases"][0]["name"] = std::string("Jakub Zytecki\0tail", 18);
    assert(!choose(doc));
    artist(doc)["aliases"][0]["name"] = "\xC0\xAF";
    assert(!choose(doc));

    reset(doc, payload);
    artist(doc)["id"] = "invalid";
    assert(!choose(doc));
    artist(doc)["name"] = REQUESTED;  // Canonical alternative to a different credit.
    assert(!choose(doc));
    artist(doc)["id"] = OWNER;
    assert(choose(doc));
    artist(doc)["id"] = nullptr;
    credits(doc)[0]["name"] = REQUESTED;  // Legacy exact credit needs no MBID.
    assert(choose(doc));

    reset(doc, payload);
    JsonArray list = artist(doc)["aliases"].to<JsonArray>();
    list.clear();
    for (size_t i = 0; i <= artist_aliases::MAX_ALIASES; ++i) {
        JsonObject alias = list.add<JsonObject>();
        alias["name"] = REQUESTED;
        alias["type"] = "Search hint";
    }
    assert(!choose(doc));
    reset(doc, payload);
    artist(doc)["aliases"][1] = 42;  // Malformed sibling after an otherwise valid match.
    assert(!choose(doc));
    reset(doc, payload);
    credits(doc).add(credits(doc)[0]);
    assert(!choose(doc));

    std::cout << "ArduinoJson " << ARDUINOJSON_VERSION
              << ": exact provider fixture, const views and malformed type/owner/list guards passed\n";
}

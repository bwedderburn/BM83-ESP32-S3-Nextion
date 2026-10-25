#include "artist_aliases.h"
#include "artist_json_stubs.h"

#include <assert.h>
#include <stdlib.h>
#include <iostream>

// Compiled unchanged from artwork.cpp by the Python runner.
#include "artwork_artist_credit.inc"

static const char REQUESTED[] = "Jakub Zytecki";
static const char CANONICAL[] = "Jakub Żytecki";
static const char OWNER[] = "1cbd7faf-938f-4c10-aeb1-426e83d38407";

static JsonNode valid_credit() {
    return JsonNode::list({JsonNode::obj({
        {"name", JsonNode::str(CANONICAL)},
        {"artist", JsonNode::obj({
            {"name", JsonNode::str(CANONICAL)}, {"id", JsonNode::str(OWNER)},
            {"aliases", JsonNode::list({JsonNode::obj({
                {"name", JsonNode::str(REQUESTED)}, {"type", JsonNode::str("Search hint")}
            })})}
        })}
    })});
}

static JsonNode &artist(JsonNode &credit) { return credit.array[0].object["artist"]; }
static JsonNode &aliases(JsonNode &credit) { return artist(credit).object["aliases"]; }
static const char *choose(const JsonNode &credit, const char *requested = REQUESTED) {
    return credited_artist(JsonArrayConst(&credit), requested);
}

static void direct_and_single_credit_rules() {
    JsonNode credit = valid_credit();
    assert(choose(credit) && strcmp(choose(credit), REQUESTED) == 0);
    credit.array.push_back(credit.array[0]);
    assert(!choose(credit));
    assert(!choose(JsonNode::list({})));
    assert(!choose(JsonNode::list({JsonNode::number()})));

    credit = valid_credit();
    credit.array[0].object["name"] = JsonNode::str(REQUESTED);
    aliases(credit) = JsonNode::number();
    artist(credit).object.erase("id");
    assert(choose(credit));  // Existing direct credit does not need aliases/ID.
    credit.array[0].object["name"] = JsonNode::str("Different display credit");
    assert(!choose(credit, CANONICAL));  // Alternative canonical needs an owner.
    artist(credit).object["id"] = JsonNode::number();
    assert(!choose(credit, CANONICAL));
    artist(credit).object["id"] = JsonNode::str("invalid");
    assert(!choose(credit, CANONICAL));
    artist(credit).object["id"] = JsonNode::str("00000000-0000-0000-0000-000000000000");
    assert(!choose(credit, CANONICAL));
    artist(credit).object["id"] = JsonNode::str(OWNER);
    assert(choose(credit, CANONICAL));  // Valid same-artist canonical alternative.
    artist(credit).object.erase("id");
    credit.array[0].object.erase("name");
    assert(choose(credit, CANONICAL));  // Legacy fallback when credit is absent.
}

static void alias_schema_fails_closed() {
    JsonNode credit = valid_credit();
    artist(credit).object.erase("id");
    assert(!choose(credit));
    credit = valid_credit(); artist(credit).object["id"] = JsonNode::number();
    assert(!choose(credit));
    credit = valid_credit(); artist(credit).object["id"] = JsonNode::str("invalid");
    assert(!choose(credit));

    const JsonNode invalid_containers[] = {JsonNode(), JsonNode::number(), JsonNode::obj({}), JsonNode::list({})};
    for (const auto &node : invalid_containers) {
        credit = valid_credit(); aliases(credit) = node; assert(!choose(credit));
    }
    credit = valid_credit();
    for (size_t i = 1; i <= artist_aliases::MAX_ALIASES; ++i)
        aliases(credit).array.push_back(aliases(credit).array[0]);
    assert(!choose(credit));
    credit = valid_credit(); aliases(credit).array.push_back(JsonNode::number());
    assert(!choose(credit));  // Validate a malformed sibling after the match.
    credit = valid_credit(); aliases(credit).array[0].object.erase("name");
    assert(!choose(credit));
    credit = valid_credit(); aliases(credit).array[0].object["name"] = JsonNode::number();
    assert(!choose(credit));
    credit = valid_credit(); aliases(credit).array[0].object["name"] = JsonNode::str("Jakub Zytecki Tribute");
    assert(!choose(credit));
}

static void json_strings_are_complete_and_typed() {
    JsonNode credit = valid_credit();
    auto &entry = aliases(credit).array[0].object;
    entry["type"] = JsonNode();
    assert(choose(credit));  // MusicBrainz supports untyped/null aliases.
    entry.erase("type");
    assert(choose(credit));
    entry["type"] = JsonNode::number();
    assert(!choose(credit));
    entry["type"] = JsonNode::str("Artist name ");
    assert(!choose(credit));
    entry["type"] = JsonNode::str(std::string("Search hint\0tail", 16));
    assert(!choose(credit));
    entry["type"] = JsonNode::str("Search hint");
    entry["name"] = JsonNode::str(std::string("Jakub Zytecki\0tail", 18));
    assert(!choose(credit));
    entry["name"] = JsonNode::str("\xC0\xAF");
    assert(!choose(credit));
    entry["name"] = JsonNode::str(std::string(artwork_matching::MAX_INPUT_BYTES + 1, 'x'));
    assert(!choose(credit));
}

static void captured_provider_fixture(int argc, char **argv) {
    assert(argc == 11);
    JsonNode credit = valid_credit();
    credit.array[0].object["name"] = JsonNode::str(argv[1]);
    artist(credit).object["name"] = JsonNode::str(argv[2]);
    artist(credit).object["id"] = JsonNode::str(argv[3]);
    aliases(credit).array[0].object["name"] = JsonNode::str(argv[4]);
    aliases(credit).array[0].object["type"] = argv[5][0] ? JsonNode::str(argv[5]) : JsonNode();
    const char *name = choose(credit);
    assert(name && strcmp(name, REQUESTED) == 0);
    const artwork_matching::Candidate candidate = {name, argv[6], nullptr, argv[7],
        static_cast<unsigned>(atoi(argv[8])), static_cast<unsigned>(atoi(argv[9])), false, argv[10]};
    assert(artwork_matching::select_album({REQUESTED, "Nothing Lasts, Nothing's Lost", ""},
        &candidate, 1).outcome == artwork_matching::Outcome::Matched);
}

int main(int argc, char **argv) {
    direct_and_single_credit_rules();
    alias_schema_fails_closed();
    json_strings_are_complete_and_typed();
    captured_provider_fixture(argc, argv);
    std::cout << "production credit adapter: captured response and malformed JSON guards passed\n";
}

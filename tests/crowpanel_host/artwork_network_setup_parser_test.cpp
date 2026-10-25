// Host-only USB command parsing checks. No Wi-Fi, credentials or hardware.
#include "network_setup.h"

#include <cassert>
#include <cstdio>
#include <string>

using network_setup_protocol::Command;
using network_setup_protocol::LineParser;
using network_setup_protocol::Request;

static size_t feed(LineParser &parser, const std::string &bytes, Request &request) {
    size_t accepted = 0;
    for (unsigned char byte : bytes) if (parser.feed(byte, request)) ++accepted;
    return accepted;
}

int main() {
    Request request;
    assert(network_setup_protocol::parse_line("BMWIFI_PROFILE:0123AbCd", request));
    assert(request.command == Command::Profile && std::string(request.nonce) == "0123AbCd");
    assert(network_setup_protocol::parse_line("BMWIFI_APPLY:deadBEEF01234567", request));
    assert(request.command == Command::Apply);
    assert(network_setup_protocol::parse_line("BMWIFI_COMMIT:deadBEEF01234567", request));
    assert(request.command == Command::Commit);
    assert(network_setup_protocol::parse_line("BMWIFI_ABORT:deadBEEF01234567", request));
    assert(request.command == Command::Abort);
    const std::string longest = "BMWIFI_PROFILE:" + std::string(64, 'f');
    assert(network_setup_protocol::parse_line(longest.c_str(), request));
    const char *bad[] = {nullptr, "", "BMWIFI_PROFILE:", "BMWIFI_PROFILE:1234567", "BMWIFI_APPLY:1234567g",
                         "BMWIFI_PROFILE:12345678:extra", "BMWIFI_PROFILE:12345678 ", "BMWIFI_PROFILE: 12345678",
                         "bmwifi_profile:12345678", "BMWIFI_APPLYX:12345678", "BMWIFI_OTHER:12345678",
                         "BMWIFI_COMMIT:1234567g", "BMWIFI_ABORT:12345678:extra"};
    for (const char *line : bad) {
        assert(!network_setup_protocol::parse_line(line, request));
        assert(request.command == Command::None && request.nonce[0] == '\0');
    }
    assert(!network_setup_protocol::parse_line((longest + "f").c_str(), request));

    LineParser parser;
    assert(feed(parser, "BMWIFI_PRO", request) == 0);
    assert(feed(parser, "FILE:12345678", request) == 0);
    assert(feed(parser, "\r\n", request) == 1 && request.command == Command::Profile);
    assert(feed(parser, "BMWIFI_APPLY:87654321\n", request) == 1 && request.command == Command::Apply);
    assert(feed(parser, "BMWIFI_PROFILE:12345678BMWIFI_APPLY:12345678\n", request) == 0);
    assert(feed(parser, std::string(200, 'x') + "BMWIFI_PROFILE:12345678\n", request) == 0);
    assert(feed(parser, "BMWIFI_PROFILE:12345678\n", request) == 1);  // Recovery after overflow.
    assert(feed(parser, std::string("BMWIFI_PROFILE:1234\0", 20) + "5678\n", request) == 0);
    assert(feed(parser, "BMWIFI_PROFILE:1234\x80" "5678\n", request) == 0);
    assert(feed(parser, "BMWIFI_PROFILE:1234\r5678\n", request) == 0);
    assert(feed(parser, "BMWIFI_PROFILE:12345678\r\r\n", request) == 0);
    assert(feed(parser, longest + "\n", request) == 1);
    assert(feed(parser, "\n\nBMWIFI_APPLY:12345678\n", request) == 1);
    assert(feed(parser, "BMWIFI_COMMIT:12345678\nBMWIFI_ABORT:12345678\n", request) == 2);
    std::puts("network setup parser scenarios passed");
    return 0;
}

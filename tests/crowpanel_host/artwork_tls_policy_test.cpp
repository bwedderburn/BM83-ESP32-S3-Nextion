#include "artwork_tls_policy.h"

#include <assert.h>
#include <stddef.h>
#include <string>

using artwork_tls_policy::use_archive_pem_retry;

int main() {
    const char *accepted[] = {"archive.org", "ia801907.us.archive.org", "dn721608.ca.archive.org",
                              "a.archive.org", "cdn-1.us.archive.org"};
    for (size_t i = 0; i < sizeof(accepted) / sizeof(accepted[0]); ++i) {
        assert(use_archive_pem_retry(accepted[i], -1, -0x3000, false, true));
        assert(!use_archive_pem_retry(accepted[i], -1, -0x3000, true, true));
        assert(!use_archive_pem_retry(accepted[i], -1, -0x3000, false, false));
    }

    const char *rejected[] = {nullptr, "", "musicbrainz.org", "coverartarchive.org", "api.deezer.com",
                              "cdn-images.dzcdn.net", "evilarchive.org", "archive.org.evil",
                              "a.archive.org.evil", "archive.org.evil.net", "a..archive.org",
                              ".archive.org", "-a.archive.org", "a-.archive.org", "a.archive.org.",
                              "user@a.archive.org", "a.archive.org:443", "https://archive.org",
                              "a%2e.archive.org", "a/archive.org", "ARCHIVE.ORG", "a.ARCHIVE.org",
                              "a.archive.org\n"};
    for (size_t i = 0; i < sizeof(rejected) / sizeof(rejected[0]); ++i)
        assert(!use_archive_pem_retry(rejected[i], -1, -0x3000, false, true));

    const std::string long_label = std::string(64, 'a') + ".archive.org";
    assert(!use_archive_pem_retry(long_label.c_str(), -1, -0x3000, false, true));

    const int wrong_errors[] = {0, -1, -0x2700, -0x6800, -0x7280, -0x3001, 0x3000};
    for (size_t i = 0; i < sizeof(wrong_errors) / sizeof(wrong_errors[0]); ++i)
        assert(!use_archive_pem_retry("ia801907.us.archive.org", -1, wrong_errors[i], false, true));

    const int completed_http[] = {0, 200, 301, 302, 307, 400, 403, 404, 429, 500, 503};
    for (size_t i = 0; i < sizeof(completed_http) / sizeof(completed_http[0]); ++i)
        assert(!use_archive_pem_retry("ia801907.us.archive.org", completed_http[i], -0x3000, false, true));

    // Various negative HTTPClient connection errors are eligible only when
    // the independent TLS result is precisely the verifier incompatibility.
    assert(use_archive_pem_retry("ia801907.us.archive.org", -2, -0x3000, false, true));
    assert(use_archive_pem_retry("ia801907.us.archive.org", -11, -0x3000, false, true));
    return 0;
}

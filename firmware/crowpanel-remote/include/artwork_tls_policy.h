// A single ordinary-PEM verification retry for the archive.org cross-chain
// incompatibility in the pinned SDK's compressed trust-bundle verifier.
// The caller must first pass the URL through the artwork fetch allowlist.
#pragma once

#include <stddef.h>
#include <string.h>

namespace artwork_tls_policy {

inline bool archive_hostname(const char *host) {
    if (!host) return false;
    size_t length = 0;
    while (length <= 253 && host[length]) ++length;
    if (!length || length > 253) return false;
    // request_host already lowercases its accepted URL. Still reject malformed
    // names, credentials, ports and lookalike suffixes at this policy boundary.
    size_t label_size = 0;
    for (size_t i = 0; i < length; ++i) {
        const char ch = host[i];
        if (ch == '.') {
            if (!label_size || host[i - 1] == '-') return false;
            label_size = 0;
        } else {
            if (!((ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '-') ||
                (!label_size && ch == '-') || ++label_size > 63) return false;
        }
    }
    if (!label_size || host[length - 1] == '-') return false;
    const char domain[] = "archive.org";
    const size_t domain_size = sizeof(domain) - 1;
    return strcmp(host, domain) == 0 ||
           (length > domain_size + 1 && host[length - domain_size - 1] == '.' &&
            strcmp(host + length - domain_size, domain) == 0);
}

inline bool use_archive_pem_retry(const char *host, int http_status, int tls_error,
                                  bool already_pem, bool have_anchor) {
    // An explicit X.509 fatal-verification error is required. HTTP failures,
    // generic timeouts and the application's date-check rejection cannot
    // activate this compatibility path or weaken their existing behavior.
    return !already_pem && have_anchor && http_status < 0 && tls_error == -0x3000 && archive_hostname(host);
}

}  // namespace artwork_tls_policy

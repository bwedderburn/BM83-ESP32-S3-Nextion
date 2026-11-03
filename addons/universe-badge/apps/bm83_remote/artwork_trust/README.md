# App-owned artwork certificate verification

`verified_fetch.py` reuses the badge's frozen `fetch.AsyncFetch` HTTP parser but
replaces its `_connect` method. It never calls the upstream unauthenticated
connection method. Every connection requires `tls.CERT_REQUIRED`, the requested
hostname as SNI, the app's explicit public CA store and a plausible UTC clock
(2026–2099). There is no certificate-disabled, HTTP, reduced-root or date-check
fallback. The adapter does not change global TLS contexts or system trust.

The one app-owned TLS context is populated once after all 118 DER certificates
have loaded successfully. Each load uses the physical badge's positional DER
API, which appends to the same context. Requests reuse that context and retain
nonblocking connect/handshake operation. Request cancellation closes the socket;
leaving the app drops its cached context. The complete store parses only once
per app session, rather than during each frame or each image request.

A stock/reset badge can have a 2021 RTC. New network artwork waits until the app
can recover UTC using the firmware's existing `ntptime.settime`, leaving its
server and one-second timeout unchanged. Only the same authenticated-idle
background gate may attempt this. There are at most three attempts: immediately,
then after 5 seconds, then after another 30 seconds. A failed or unavailable
clock sync leaves a visible clock message and sends no HTTPS request. Settings'
local retry rearms the counter without doing I/O in the input handler. A valid
clock and cached artwork do not invoke NTP. NTP is ordinary network time, not a
new trust anchor or an authenticated time service. DNS inside NTP/fetch remains
indivisible; this does not make the whole operation nonblocking.

## Exact public roots and reproduction

`cacert.pem` and `godaddy-root-g2.pem` are copied byte for byte from this project's
`firmware/crowpanel-remote/lib/artwork_trust/ca`. `provenance.json` records the
source paths, SHA256 hashes and the retained Mozilla snapshot date
2026-10-20. The 118-root Mozilla store already contains the GoDaddy G2 anchor;
the smaller PEM adds no root to this app's trust set.

These source PEM files and the DER store derived from them are MPL-2.0 data.
The full license is `LICENSE-MPL-2.0.txt`. The original public source is
https://curl.se/ca/cacert.pem and its extraction documentation is
https://curl.se/docs/caextract.html. The source PEMs are retained here to provide
the corresponding source alongside the derived store. Root updates must be
reviewed and reproduced explicitly; no trust store is downloaded at runtime.

From the repository root, run `python3 tests/build_badge_artwork_ca_store.py`
to reproduce the store using only the host Python standard library. The script checks both exact source
hashes, the 118 unique DER certificates and inclusion of G2 before writing the
store. Its format is `BMCA1`, a two-byte big-endian certificate count, followed
by a two-byte big-endian length and exact DER bytes for each certificate. The
runtime loader bounds each certificate to 8 KiB, requires exactly 118 entries
and rejects truncation or a trailer. It never mistakes concatenated DER for a
single native CA load. The generated file is 127,346 bytes; its SHA256 is
`f92335a8257776a862cfdb4e675441db344c29d67cc05462dbf1381f7b38a4fb`.

## Upstream code notice and physical release gates

The small `_connect` adaptation comes from Pimoroni's `fetch.py` at commit
`ee84772fb7f7d5424e9593029caba815c6f89c80`, SHA256
`11bb4cb6163b2cee44e86e2cbe7a1e67bc051c591d7e11d88f092bfaf323f974`:
https://github.com/pimoroni/tufty2350/blob/ee84772fb7f7d5424e9593029caba815c6f89c80/modules/common/fetch.py
Copyright 2026 Pimoroni Ltd; its complete MIT notice is
`LICENSE-Pimoroni-MIT.txt`. The physical badge's frozen parser remains the
runtime implementation; the referenced source is not a claim that every
firmware byte equals that Git commit.

On the connected badge's 1.29 preview firmware, native, certificate-required
smoke checks established: two different roots appended to one context validate
both MusicBrainz and Archive.org; an unrelated root fails signature checking;
a wrong hostname fails hostname checking; and a deliberately future RTC fails
certificate expiry checking. The full 118-root store loaded in 95 ms, and the
existing NTP setter recovered UTC in 122 ms with timeout 1 unchanged. Those are
component checks. The final integrated app still requires its separately
controlled install, real artwork/control tests and uninterrupted 30-minute
stability acceptance. Host fakes do not replace those physical checks.

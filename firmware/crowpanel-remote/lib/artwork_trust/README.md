# Artwork trust roots and third-party notices

The generated include/artwork_ca_bundle.h contains public Mozilla root-store
data converted to the compressed certificate format used by ESP-IDF 4.4.7.
The array is artwork_trust::kMozillaCaBundle; its pointer has static lifetime.
The application passes it explicitly to WiFiClientSecure::setCACertBundle.
The same header also contains artwork_trust::kArchiveRootG2Pem, extracted
from this exact Mozilla store for ordinary PEM verification of the exact
archive.org host. Allowed archive CDN subdomains use the full bundle first;
one narrowly gated retry can use that same existing G2 PEM when the pinned
SDK reports the observed fatal X.509 cross-chain error. Other hosts use the
bundle.

This snapshot is dated 2026-10-20 and contains 118 unique roots / 54,752 bytes.
Bundle SHA256: 8ca330673e7ecd07610eecfaffd23aba8b9ceca10a381d3878f268348edf5aec.
Original generation/source checks are retained in ca/provenance.json.
integration-provenance.json records the shipped header and the bounded
archive compatibility anchor; the bundle's DER subject/key data is unchanged.

## Public root-store source and MPL 2.0

curl identifies its converted Mozilla PEM store as MPL 2.0:
https://curl.se/docs/caextract.html

The source PEM and publisher hash are included as ca/cacert.pem and
ca/cacert.pem.sha256. The source and generated trust-anchor data remain under
MPL 2.0; the complete license is LICENSE-MPL-2.0.txt. Source is available in this
repository at firmware/crowpanel-remote/lib/artwork_trust/ca and at:

- https://curl.se/ca/cacert.pem
- https://curl.se/ca/cacert.pem.sha256
- https://raw.githubusercontent.com/mozilla-firefox/firefox/refs/heads/release/security/nss/lib/ckfw/builtins/certdata.txt

The project must maintain this explicit trust store as Mozilla adds/removes
roots. Its source/version is not inferred from the SDK's old built-in bundle.

## Generator and regeneration

ca/gen_crt_bundle-v4.4.7.py is the unmodified official Espressif generator:
https://raw.githubusercontent.com/espressif/esp-idf/v4.4.7/components/mbedtls/esp_crt_bundle/gen_crt_bundle.py

Copyright 2018-2019 Espressif Systems (Shanghai) PTE LTD.
Its Apache-2.0 notice is retained in the script; the complete license is
LICENSE-Apache-2.0.txt.

ca/prepare_header.py validates every DER subject/SPKI against the PEM, checks
sorting, unique subjects, count, publisher hash and exact bundle EOF, then emits
the static header. It also extracts and verifies the self-signed GoDaddy G2
root by its published SHA256 fingerprint, and emits ca/godaddy-root-g2.pem
and the static PEM constant. It adds the shipped SPDX/source notice comments.

To reproduce the retained snapshot from the repository root, with Python and
cryptography available:

    cd firmware/crowpanel-remote/lib/artwork_trust/ca
    python gen_crt_bundle-v4.4.7.py --input cacert.pem
    python prepare_header.py
    cp artwork_ca_bundle.h ../../../include/artwork_ca_bundle.h

The generated raw bundle and temporary header need not be committed. A root
refresh must update the PEM/published hash, date comments and provenance after
reviewing the upstream source; do not silently replace the store at runtime.

## archive.org chain compatibility

The observed archive.org TLS 1.2 chain includes a GoDaddy G2 cross-certificate
and an extra legacy GoDaddy Class2 root. The maintained Mozilla snapshot trusts
the self-signed G2 anchor and omits Class2. Arduino-ESP32 2.0.17's compressed
bundle callback fails at that unnecessary legacy tail instead of building the
shorter path to G2. The exact archive.org branch therefore supplies the existing G2
anchor through setCACert on a fresh client, rather than through the bundle.
It does not add Class2 or a server leaf certificate to the trust set.

The G2 certificate's DER SHA256 is
45140b3247eb9cc8c5b4f0d7b53091f73292089e6e5a63e2749dd3aca9198eda.
Its source is the retained Mozilla PEM; GoDaddy independently publishes that
fingerprint and certificate in its primary repository:

- https://certs.godaddy.com/repository/
- https://certs.godaddy.com/repository/gdroot-g2.crt.pem

The 1,367-byte PEM avoids parsing the complete 200 KB root store in the SDK's
internal-memory TLS allocator. Chain signatures, the requested hostname and
the application's peer-certificate dates remain checked. A changed archive
issuer can require a reviewed root-store/anchor update; there is no insecure
retry. The generator fails if G2 is absent from the maintained Mozilla store.
Archive CDN subdomains can use another issuer: the observed
dn721608.ca.archive.org chain uses Let's Encrypt and validates with the
maintained full bundle. Each allowed CDN request therefore starts with the
full bundle. A request is retried once on a fresh client with the existing G2
PEM only when its HTTP operation returns a negative status and the TLS error
is `MBEDTLS_ERR_X509_FATAL_ERROR` (`-0x3000`, decimal `-12288`). The hostname
must have passed the artwork URL allowlist and the exact `archive.org` or
dot-delimited subdomain policy. The exact archive.org host continues to use
G2 PEM on its first attempt. A request already using PEM cannot retry again;
a redirect begins the ordinary trust selection for its new host. The existing
redirect and whole-job bounds still apply. HTTP status failures, generic
timeouts and application date-check failures do not select this retry.

On 2026-10-25, the Weightless / Animals as Leaders artwork redirected to
`ia801907.us.archive.org`. That server presented
`*.us.archive.org -> GoDaddy Secure CA G2 -> cross-signed Root G2 -> legacy Class2`,
reproducing the parent host's redundant tail. The cross-signed G2 certificate's
public key matches the retained self-signed G2 anchor exactly (SPKI SHA256
`2a8f2d8af0eb123898f74c866ac3fa669054e23c17bc7a95bd0234192dc635d0`).
Read-only Mac TLS 1.2 checks verified this CDN with both the maintained bundle
and the existing G2 PEM; an incorrect hostname and an unrelated issuer were
rejected with the G2 PEM. The returned cover was a baseline 250x250 JPEG.
These host checks establish the public chain and negative cases; they do not
replace hardware validation of the SDK compatibility path.

Both attempts retain normal issuer/signature, requested-hostname and every
peer-certificate date check. No root is added, the Mozilla bundle and shipped
header remain unchanged, and legacy Class2 is not trusted. A different CDN
issuer continues to use the full bundle; a failed G2 retry fails closed.
Source details are retained in ca/archive-root-provenance.json.
The optional `python ca/verify_archive_host.py` host check makes public TLS 1.2
handshakes only: the archive hostname must verify with G2, an unrelated issuer
and an incorrect hostname must fail. It sends no HTTP payload or credentials.
This checks the public chain independently; ESP32 operation still needs its
own hardware verification.

## Other artwork dependencies

ArduinoJson is pinned to 7.4.3, which fixes the maintainer's 2026-03-02
numeric-string buffer-overrun advisory. Its original MIT copyright/permission
notice is retained in LICENSE-ArduinoJson-MIT.txt.

- https://arduinojson.org/news/2026/03/02/security-update/
- https://github.com/bblanchon/ArduinoJson/tree/v7.4.3

The existing LVGL 8.3.11 dependency supplies ChaN's TJpgDec R0.03 JPEG decoder.
Its original copyright, warranty and redistribution notice is retained in
NOTICE-TJpgDec.txt; the code is not copied into this project.

- https://github.com/lvgl/lvgl/blob/v8.3.11/src/extra/libs/sjpg/tjpgd.c

## TLS validity enforcement

The exact Arduino-ESP32 2.0.17 SDK has CONFIG_MBEDTLS_HAVE_TIME_DATE disabled.
TimeCheckedClient therefore checks gmtime_r UTC against every peer certificate's
valid_from/valid_to after trusted issuer/hostname verification and before its
connect override can return success to HTTPClient. Missing chains, invalid
time, out-of-validity certificates and excessive chain depth fail closed.
There is no insecure TLS fallback. NTP time and an explicit root-store pointer
are required for network fetches; positive SD-cache reads remain usable offline.

SD cache files are stored only in /bm83-artwork's aw-<SHA256> namespace.
SD.begin explicitly disables formatting; unrelated card contents are preserved.

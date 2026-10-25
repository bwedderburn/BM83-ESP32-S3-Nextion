#!/usr/bin/env python3
"""Validate an IDF 4.4.x bundle against cacert.pem and emit its static header."""
from pathlib import Path
import hashlib
import struct

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

HERE = Path(__file__).resolve().parent
pem = (HERE / "cacert.pem").read_bytes()
assert hashlib.sha256(pem).hexdigest() == (HERE / "cacert.pem.sha256").read_text().split()[0]
certificates = x509.load_pem_x509_certificates(pem)
# GoDaddy's published self-signed G2 root, already trusted by this Mozilla
# snapshot. Do not substitute the obsolete Class2 root sent by archive.org.
archive_fingerprint = "45140b3247eb9cc8c5b4f0d7b53091f73292089e6e5a63e2749dd3aca9198eda"
archive_roots = [certificate for certificate in certificates
                 if certificate.fingerprint(hashes.SHA256()).hex() == archive_fingerprint]
assert len(archive_roots) == 1, "Archive G2 root missing from maintained Mozilla store"
archive_root = archive_roots[0]
archive_root.verify_directly_issued_by(archive_root)
archive_pem = archive_root.public_bytes(serialization.Encoding.PEM)
bundle = (HERE / "x509_crt_bundle").read_bytes()
count = struct.unpack_from(">H", bundle)[0]
records = []
offset = 2
for _ in range(count):
    subject_size, key_size = struct.unpack_from(">HH", bundle, offset)
    offset += 4
    assert subject_size > 0 and key_size > 0
    subject = bundle[offset : offset + subject_size]
    offset += subject_size
    key = bundle[offset : offset + key_size]
    offset += key_size
    serialization.load_der_public_key(key)
    records.append((subject, key))
assert offset == len(bundle)
assert records == sorted(records, key=lambda item: item[0])
expected = sorted(
    (
        (
            certificate.subject.public_bytes(),
            certificate.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ),
        )
        for certificate in certificates
    ),
    key=lambda item: item[0],
)
assert records == expected
assert len(set(subject for subject, _ in records)) == count
digest = hashlib.sha256(bundle).hexdigest()
header = """// SPDX-License-Identifier: MPL-2.0\n// Public Mozilla root-store source and notices: ../lib/artwork_trust/README.md\n// Generated public Mozilla trust anchors; regenerate from ca/provenance.json commands.
// Mozilla snapshot: 2026-10-20; format: ESP-IDF 4.4.x compressed certificate bundle.
// Source: https://curl.se/ca/cacert.pem
// Binary SHA-256: %s
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace artwork_trust {
// Static storage is required: WiFiClientSecure keeps this pointer for later TLS handshakes.
alignas(4) static const uint8_t kMozillaCaBundle[] = {
""" % digest
header += "".join(
    "    " + ", ".join("0x%02x" % byte for byte in bundle[index : index + 16]) + ",\n"
    for index in range(0, len(bundle), 16)
)
header += "};\nstatic const size_t kMozillaCaBundleSize = sizeof(kMozillaCaBundle);\n"
header += "// Same Mozilla trust set; ordinary PEM permits the trusted shorter archive.org chain.\n"
header += "// GoDaddy published DER SHA256: " + archive_fingerprint + "\n"
header += 'static const char kArchiveRootG2Pem[] = R"BM83_CA(' + archive_pem.decode("ascii") + ')BM83_CA";\n'
header += "} // namespace artwork_trust\n"
(HERE / "artwork_ca_bundle.h").write_text(header)
(HERE / "godaddy-root-g2.pem").write_bytes(archive_pem)
print("Validated %d unique roots, %d bytes, SHA256 %s" % (count, len(bundle), digest))

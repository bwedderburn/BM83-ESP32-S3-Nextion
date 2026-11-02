"""Reproduce the badge's DER store from this project's exact retained public PEMs.

Host-only, Python standard library; no downloads, devices or trust-store edits.
"""

import base64
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
APP = next(path for path in (
    ROOT / "addons/universe-badge/apps/bm83_remote",
    ROOT / "badge/apps/bm83_remote",
) if path.is_dir())
DIRECTORY = APP / "artwork_trust"
SOURCES = {
    "cacert.pem": "796f1389bfea13c0ed78f663b765baaff54a508e5483786bd6ece73c5e3e3cbe",
    "godaddy-root-g2.pem": "500329abac100a953a7396b54b36be57d333022f17401bc948248ea179cf1784",
}


def build():
    groups = []
    for name, expected in SOURCES.items():
        data = (DIRECTORY / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("Retained CA source changed: " + name)
        matches = re.findall(
            rb"-----BEGIN CERTIFICATE-----\s*([A-Za-z0-9+/=\s]+?)"
            rb"\s*-----END CERTIFICATE-----", data)
        certs = [base64.b64decode(re.sub(rb"\s", b"", value), validate=True)
                 for value in matches]
        if not certs or any(not 64 <= len(cert) <= 8192 for cert in certs):
            raise ValueError("Invalid retained PEM certificates")
        groups.append(certs)
    certs, g2 = groups
    if len(certs) != 118 or len(set(certs)) != 118 or len(g2) != 1 or g2[0] not in certs:
        raise ValueError("Expected exact Mozilla118 roots including existing G2")
    store = b"BMCA1" + len(certs).to_bytes(2, "big")
    store += b"".join(len(cert).to_bytes(2, "big") + cert for cert in certs)
    (DIRECTORY / "roots.der-store").write_bytes(store)
    provenance = json.loads((DIRECTORY / "provenance.json").read_text())
    provenance["der_store"] = {
        "path": "roots.der-store", "format": "BMCA1; uint16be count; repeated uint16be DER length + exact DER; no trailer",
        "certificates": len(certs), "bytes": len(store),
        "sha256": hashlib.sha256(store).hexdigest(),
        "godaddy_g2_already_included": True,
        "added_roots": 0,
    }
    (DIRECTORY / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")


if __name__ == "__main__":
    build()

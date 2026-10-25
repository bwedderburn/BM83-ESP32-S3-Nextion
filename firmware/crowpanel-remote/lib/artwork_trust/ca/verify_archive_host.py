#!/usr/bin/env python3
"""Optional public TLS 1.2 anchor checks; sends no HTTP payload or credentials."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import socket
import ssl

ROOT = Path(__file__).resolve().parent / "godaddy-root-g2.pem"


def check(case):
    host, hostname, expected = case
    context = ssl.create_default_context(cafile=str(ROOT))
    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
    try:
        with socket.create_connection((host, 443), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname=hostname) as connection:
                result = {"host": host, "hostname": hostname, "verified": True,
                          "protocol": connection.version()}
    except ssl.SSLCertVerificationError as error:
        result = {"host": host, "hostname": hostname, "verified": False,
                  "verification_error": error.verify_message}
    assert result["verified"] == expected, result
    return result


if __name__ == "__main__":
    cases = [("archive.org", "archive.org", True),
             ("musicbrainz.org", "musicbrainz.org", False),
             ("archive.org", "wrong.invalid", False)]
    with ThreadPoolExecutor(max_workers=len(cases)) as workers:
        print(json.dumps(list(workers.map(check, cases)), indent=2))

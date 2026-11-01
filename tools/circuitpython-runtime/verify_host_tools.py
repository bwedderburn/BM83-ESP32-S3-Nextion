#!/usr/bin/env python3
"""Exercise pinned host crypto tools with synthetic files, never a device.

All commands are fixed offline transformations in a private temporary directory.
Keys are disposable test material. Output contains no key bytes or file paths.
"""

import argparse
from importlib import metadata
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


MODULES = ("esp_idf_nvs_partition_gen", "espsecure", "esptool")
VERSIONS = ("cryptography", "esptool", "esp-idf-nvs-partition-gen", "cffi")


class VerificationError(Exception):
    """A failed offline check, identified without logging subprocess contents."""

    def __init__(self, check, returncode=None):
        super().__init__(check)
        self.check = check
        self.returncode = returncode


def run_tool(check, module, arguments, directory, expect_failure=False):
    """Run a fixed module without a shell; never accept a device operation."""
    permitted = {
        "esp_idf_nvs_partition_gen": ("generate", "encrypt", "decrypt"),
        "espsecure": ("generate-signing-key", "sign-data", "verify-signature",
                      "encrypt-flash-data", "decrypt-flash-data"),
        "esptool": ("--chip",),
    }
    if module not in MODULES or not arguments or arguments[0] not in permitted[module]:
        raise VerificationError(check)
    if module == "esptool" and (len(arguments) != 4
                                or arguments[:3] != ["--chip", "esp32s3", "image-info"]):
        raise VerificationError(check)
    if "--port" in arguments or any("write-flash" in value for value in arguments):
        raise VerificationError(check)
    try:
        result = subprocess.run([sys.executable, "-m", module, *arguments],
                                cwd=directory, capture_output=True, timeout=60,
                                check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise VerificationError(check) from None
    if (result.returncode == 0) == expect_failure:
        raise VerificationError(check, result.returncode)


def require_same(check, first, second):
    try:
        a, b = first.read_bytes(), second.read_bytes()
    except OSError:
        raise VerificationError(check) from None
    if not a or a != b:
        raise VerificationError(check)
    return hashlib.sha256(a).hexdigest()


def nvs_case(directory):
    csv = directory / "fixture.csv"
    csv.write_text("key,type,encoding,value\nexample,namespace,,\n"
                   "message,data,string,synthetic NVS data\ncount,data,u32,42\n",
                   encoding="utf-8")
    key = directory / "nvs-key.bin"
    key.write_bytes(bytes(range(64)))
    for output in ("plain.bin", "repeat.bin"):
        run_tool("nvs_generate", "esp_idf_nvs_partition_gen",
                 ["generate", "fixture.csv", output, "0x6000"], directory)
    digest = require_same("nvs_repeat_generation", directory / "plain.bin",
                          directory / "repeat.bin")
    run_tool("nvs_encrypt", "esp_idf_nvs_partition_gen",
             ["encrypt", "fixture.csv", "encrypted.bin", "0x6000", "--inputkey", "nvs-key.bin"], directory)
    run_tool("nvs_decrypt", "esp_idf_nvs_partition_gen",
             ["decrypt", "encrypted.bin", "nvs-key.bin", "restored.bin"], directory)
    require_same("nvs_roundtrip", directory / "plain.bin", directory / "restored.bin")
    return {"name": "nvs_generate_encrypt_decrypt", "passed": True,
            "repeat_sha256": digest}


def flash_case(directory, xts):
    name = "aes_xts" if xts else "legacy_esp32_aes_ecb"
    key = name + "-key.bin"
    (directory / key).write_bytes(bytes(range(64 if xts else 32)))
    extra = ["--aes-xts"] if xts else []
    for output in (name + ".bin", name + "-repeat.bin"):
        run_tool(name + "_encrypt", "espsecure",
                 ["encrypt-flash-data", "--keyfile", key, "--output", output,
                  "--address", "0x10000", *extra, "data.bin"], directory)
    digest = require_same(name + "_repeat_encryption", directory / (name + ".bin"),
                          directory / (name + "-repeat.bin"))
    restored = name + "-restored.bin"
    run_tool(name + "_decrypt", "espsecure",
             ["decrypt-flash-data", "--keyfile", key, "--output", restored,
              "--address", "0x10000", *extra, name + ".bin"], directory)
    require_same(name + "_roundtrip", directory / "data.bin", directory / restored)
    return {"name": name + "_encrypt_decrypt", "passed": True,
            "repeat_sha256": digest}


def signature_case(directory, scheme):
    key, signed, corrupt = scheme + ".pem", scheme + "-signed.bin", scheme + "-corrupt.bin"
    run_tool(scheme + "_keygen", "espsecure",
             ["generate-signing-key", "--version", "2", "--scheme", scheme, key], directory)
    # A following option terminates espsecure's variadic keyfile argument.
    run_tool(scheme + "_sign", "espsecure",
             ["sign-data", "--version", "2", "--keyfile", key,
              "--output", signed, "data.bin"], directory)
    run_tool(scheme + "_verify", "espsecure",
             ["verify-signature", "--version", "2", "--keyfile", key, signed], directory)
    try:
        payload = bytearray((directory / signed).read_bytes())
    except OSError:
        raise VerificationError(scheme + "_signed_output") from None
    if not payload:
        raise VerificationError(scheme + "_signed_output")
    payload[0] ^= 1
    (directory / corrupt).write_bytes(payload)
    run_tool(scheme + "_reject_tamper", "espsecure",
             ["verify-signature", "--version", "2", "--keyfile", key, corrupt],
             directory, expect_failure=True)
    return {"name": scheme + "_sign_verify_reject_tamper", "passed": True}


def verify(image=None):
    versions = {name: metadata.version(name) for name in VERSIONS}
    if int(versions["cryptography"].split(".")[0]) < 50:
        raise VerificationError("cryptography_security_floor")
    from cryptography.hazmat.backends.openssl.backend import backend
    openssl_version = backend.openssl_version_text()
    with tempfile.TemporaryDirectory(prefix="bm83-host-crypto-") as temporary:
        directory = Path(temporary)
        # Complete sectors avoid random padding and exercise repeated ECB keys.
        (directory / "data.bin").write_bytes(bytes(range(256)) * 16)
        checks = [nvs_case(directory), flash_case(directory, True), flash_case(directory, False),
                  signature_case(directory, "ecdsa256"), signature_case(directory, "rsa3072")]
        if image is not None:
            image = Path(image).resolve()
            if not image.is_file():
                raise VerificationError("image_regular_file")
            run_tool("image_info", "esptool", ["--chip", "esp32s3", "image-info", str(image)], directory)
            checks.append({"name": "image_info", "passed": True})
    return {"schema_version": 1, "ok": True, "versions": versions, "checks": checks,
            "openssl_version": openssl_version, "hardware_access": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, help="Optional existing local ESP32-S3 application image; inspection only")
    args = parser.parse_args(argv)
    try:
        report = verify(args.image)
    except VerificationError as error:
        report = {"schema_version": 1, "ok": False, "failed_check": error.check,
                  "returncode": error.returncode, "hardware_access": False}
    except (metadata.PackageNotFoundError, ValueError, ImportError, OSError):
        report = {"schema_version": 1, "ok": False, "failed_check": "host_dependencies",
                  "hardware_access": False}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

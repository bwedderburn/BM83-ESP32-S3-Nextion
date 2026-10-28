"""BMW1 authenticated datagrams; also runs under CPython for contract tests."""

import binascii
import hashlib
import json

TOKENS = ("STATUS", "BT_PREV", "BT_PLAY", "BT_NEXT", "BT_MUTE",
          "BT_VOLUP_P", "BT_VOLUP_R", "BT_VOLDN_P", "BT_VOLDN_R",
          "BT_POWER", "BT_PAIR", "BT_EQ", "BT_EBIND", "NET_RETRY",
          "BLE_PAUSE", "BLE_ENABLE")


def hex_text(value, size):
    return (isinstance(value, str) and len(value) == size
            and all(c in "0123456789abcdef" for c in value))


def uint(value, maximum=0xffffffff):
    return type(value) is int and 0 <= value <= maximum


def key_bytes(value):
    if not hex_text(value, 64):
        raise ValueError("BM83_KEY must be 64 lowercase hex characters")
    return binascii.unhexlify(value)


def _json_text(value):
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if type(value) is int:
        return str(value)
    if isinstance(value, str):
        out = ['"']
        for char in value:
            code = ord(char)
            if char == '"':
                out.append('\\"')
            elif char == "\\":
                out.append("\\\\")
            elif code == 8:
                out.append("\\b")
            elif code == 9:
                out.append("\\t")
            elif code == 10:
                out.append("\\n")
            elif code == 12:
                out.append("\\f")
            elif code == 13:
                out.append("\\r")
            elif code < 32:
                out.append("\\u%04x" % code)
            else:
                out.append(char)
        out.append('"')
        return "".join(out)
    if isinstance(value, list):
        return "[" + ",".join(_json_text(item) for item in value) + "]"
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("BMW1 JSON keys must be strings")
        return "{" + ",".join(_json_text(key) + ":" + _json_text(item)
                              for key, item in value.items()) + "}"
    raise ValueError("Unsupported BMW1 JSON value")


def mac(key, payload):
    if len(key) != 32:
        raise ValueError("BMW1 needs a 32-byte key")
    block = key + bytes(32)
    inner = bytes(b ^ 0x36 for b in block)
    outer = bytes(b ^ 0x5c for b in block)
    return binascii.hexlify(hashlib.sha256(
        outer + hashlib.sha256(inner + payload).digest()).digest()[:16])


def encode(key, message, maximum=256):
    payload = _json_text(message).encode("utf-8")
    wire = b"BMW1." + mac(key, payload) + b"." + payload
    if type(maximum) is not int or maximum < 40 or maximum > 1200:
        raise ValueError("Invalid BMW1 datagram limit")
    if len(wire) > maximum:
        raise ValueError("BMW1 datagram exceeds %d bytes" % maximum)
    return wire


def decode(key, wire):
    if (len(wire) > 1200 or len(wire) < 40 or wire[:5] != b"BMW1."
            or wire[37:38] != b"."):
        return None
    expected = mac(key, wire[38:])
    difference = 0
    for index in range(32):
        difference |= expected[index] ^ wire[index + 5]
    if difference:
        return None
    try:
        value = json.loads(wire[38:].decode("utf-8"))
    except (ValueError, UnicodeError):
        return None
    if not isinstance(value, dict) or type(value.get("v")) is not int or value["v"] != 1:
        return None
    return value


def configuration(secrets):
    host = getattr(secrets, "BM83_HOST", "")
    parts = host.split(".") if isinstance(host, str) else []
    if (len(parts) != 4 or any(not p or not p.isdigit() or len(p) > 3
                             or not 0 <= int(p) <= 255 for p in parts)):
        raise ValueError("Set BM83_HOST to the unit's IPv4 address")
    port = getattr(secrets, "BM83_PORT", 8767)
    if not uint(port, 65535) or port == 0:
        raise ValueError("BM83_PORT must be 1..65535")
    return host, port, key_bytes(getattr(secrets, "BM83_KEY", ""))

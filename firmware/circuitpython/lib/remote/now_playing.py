"""Bounded, atomic BMS2 Now Playing snapshots for the CrowPanel.

Frames are at most 64 bytes: ``BMS2``, big-endian boot session (u32),
snapshot sequence (u16), fragment index/count (u8 each), payload length
(u16), CRC16-CCITT-FALSE (u16), then up to 48 payload bytes. A snapshot
contains flags/status/EQ, duration/position/sample-age (u32 milliseconds),
three text byte lengths, and bounded UTF-8 title/artist/album strings.
Flag bits 0/1/2 are power/connected/AUX; bit 3 permits interpolation only
after genuine source position advances. Playback status stays source-reported.

The receiver commits only complete, validated snapshots. Periodic full
snapshots repair packet loss without blocking the audio controller for ACKs.
"""

from .metadata_text import normalize_metadata_text

UNKNOWN = 0xFFFFFFFF
MAX_TEXT_BYTES = 96
FRAME_MAX = 64
HEADER_SIZE = 16
FRAGMENT_SIZE = FRAME_MAX - HEADER_SIZE
PAYLOAD_FIXED = 18
MAX_PAYLOAD = PAYLOAD_FIXED + 3 * MAX_TEXT_BYTES
FLAG_POWER = 1
FLAG_CONNECTED = 2
FLAG_AUX = 4
FLAG_CLOCK_ADVANCING = 8


def crc16(data):
    """Return CRC16-CCITT-FALSE (poly 0x1021, initial value 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _text_bytes(value):
    text = normalize_metadata_text(value)
    try:
        raw = text.encode("utf-8")[:MAX_TEXT_BYTES]
    except UnicodeError:
        return b""
    # The byte limit may split a multi-byte character. Keep a valid prefix.
    while raw:
        try:
            raw.decode("utf-8")
            break
        except UnicodeError:
            raw = raw[:-1]
    return raw


def _time_ms(value):
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError):
        return UNKNOWN
    return value if 0 <= value < UNKNOWN else UNKNOWN


def encode_frames(state, session, seq):
    """Encode a full state dict into <=7 immutable, <=64-byte frames.

    Missing/invalid timing is UNKNOWN, never guessed. The boot session must
    change when the controller restarts; the sequence wraps modulo 65536.
    ``position_age_ms`` is the age of the genuine source position sample
    when this snapshot is encoded, not the time since Bluetooth connected.
    """
    flags = (FLAG_POWER if state.get("power_on") else 0)
    flags |= FLAG_CONNECTED if state.get("connected") else 0
    flags |= FLAG_AUX if state.get("aux") else 0
    flags |= FLAG_CLOCK_ADVANCING if state.get("clock_advancing", False) else 0
    status = state.get("play_status")
    status = status if status in (0, 1, 2, 3, 4) else 0xFF
    try:
        eq = int(state.get("eq_index", 0xFF))
    except (TypeError, ValueError, OverflowError):
        eq = 0xFF
    eq = eq if 0 <= eq <= 0xFF else 0xFF
    text = tuple(_text_bytes(state.get(key)) for key in ("title", "artist", "album"))
    payload = bytes((flags, status, eq))
    for key in ("duration_ms", "position_ms", "position_age_ms"):
        payload += _time_ms(state.get(key)).to_bytes(4, "big")
    payload += bytes(tuple(len(value) for value in text)) + b"".join(text)
    count = (len(payload) + FRAGMENT_SIZE - 1) // FRAGMENT_SIZE
    prefix = b"BMS2" + (int(session) & UNKNOWN).to_bytes(4, "big") + (int(seq) & 0xFFFF).to_bytes(2, "big")
    suffix = len(payload).to_bytes(2, "big") + crc16(payload).to_bytes(2, "big")
    return tuple(prefix + bytes((index, count)) + suffix + payload[index * FRAGMENT_SIZE:(index + 1) * FRAGMENT_SIZE]
                 for index in range(count))

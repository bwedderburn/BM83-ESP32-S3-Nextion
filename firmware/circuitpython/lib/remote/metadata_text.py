"""Normalize invisible metadata spacing for the CrowPanel's display text.

Keep UTF-8 names and punctuation intact. This module is used only by the
CrowPanel snapshot encoder; it does not rewrite the Nextion's metadata.
"""


def normalize_metadata_text(value):
    """Return display text with visible spaces and no invisible break markers.

    Unicode White_Space and C0/C1 controls become ordinary ASCII spaces.
    Ordinary repeated spaces retain their count. Zero-width space, word
    joiner and BOM are removed; meaningful ZWJ/ZWNJ and letters are retained.
    Font coverage is separate: unsupported visible characters must not be
    silently removed from a song or artist name.
    """
    if value is None:
        return ""
    result = []
    for char in str(value):
        code = ord(char)
        if code in (0x200B, 0x2060, 0xFEFF):
            continue
        if (code < 32 or 0x7F <= code <= 0x9F or code in (0x00A0, 0x1680, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000)
                or 0x2000 <= code <= 0x200A):
            char = " "
        result.append(char)
    return "".join(result)

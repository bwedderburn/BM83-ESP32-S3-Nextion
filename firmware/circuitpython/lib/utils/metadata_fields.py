"""Recover separate fields from the observed Windows AVRCP metadata form."""


def recover_metadata_fields(attrs):
    """Recover ``artist — album`` only when the source omits its album.

    The observed Windows web-player reply contains only attributes 1/2/4
    (optionally a blank 3), with track number exactly "0" and one spaced em
    dash in attribute 2. Require that sparse reply shape too: a real artist
    name can contain an em dash when another source omits its album. Ordinary
    spaces, hyphens and en dashes are not separators. Existing album data
    always wins. Recovery copies the dictionary; other replies pass unchanged.
    """
    if not isinstance(attrs, dict):
        return attrs
    if attrs.get(4) != "0":
        return attrs
    for aid in attrs:
        if aid not in (1, 2, 3, 4):
            return attrs
    album = attrs.get(3)
    if album is not None and (not isinstance(album, str) or album.strip()):
        return attrs
    title = attrs.get(1)
    artist = attrs.get(2)
    if not isinstance(title, str) or not title.strip() or not isinstance(artist, str) or not artist.strip():
        return attrs
    separator = " \u2014 "
    if artist.count(separator) != 1:
        return attrs
    artist, album = artist.split(separator, 1)
    artist, album = artist.strip(), album.strip()
    if not artist or not album:
        return attrs
    recovered = attrs.copy()
    recovered[2], recovered[3] = artist, album
    return recovered

"""Optional bounded startup Wi-Fi join for channel-aligned artwork lookup.

Credentials are provisioned once over local USB into a private device file.
There is no host process in the runtime path. Call before opening the BM83
UART, never from its servicing loop: CircuitPython connect is synchronous.
"""
import json

PROFILE_PATH = "/.artwork_wifi.json"
MAX_PROFILE_BYTES = 512


def _text(value, minimum, maximum):
    if not isinstance(value, str):
        raise ValueError("profile text type")
    if not minimum <= len(value.encode("utf-8")) <= maximum:
        raise ValueError("profile text length")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("profile control character")
    return value


def _bssid(value):
    if not isinstance(value, str):
        raise ValueError("BSSID type")
    parts = value.split(":")
    if len(parts) != 6 or any(len(part) != 2 or any(c not in "0123456789abcdefABCDEF" for c in part)
                              for part in parts):
        raise ValueError("BSSID format")
    raw = bytes(int(part, 16) for part in parts)
    if raw == bytes(6) or raw[0] & 1:
        raise ValueError("BSSID must identify a unicast access point")
    return raw


def validate_profile(profile):
    """Return a normalized private profile; exceptions never include values."""
    if not isinstance(profile, dict) or profile.get("version", 1) != 1:
        raise ValueError("profile version/type")
    ssid = _text(profile.get("ssid"), 1, 32)
    password = _text(profile.get("password"), 0, 63)
    if password and len(password.encode("utf-8")) < 8:
        raise ValueError("password length")
    channel = profile.get("channel")
    if type(channel) is not int or not 1 <= channel <= 13:
        raise ValueError("channel range/type")
    raw = _bssid(profile.get("bssid"))
    return {"version": 1, "ssid": ssid, "password": password,
            "bssid": ":".join("%02X" % byte for byte in raw), "channel": channel}


def load_profile(path=PROFILE_PATH):
    """Load at most 512 bytes; absent configuration keeps Wi-Fi optional."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_PROFILE_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_PROFILE_BYTES:
        raise ValueError("profile too large")
    return validate_profile(json.loads(raw))


def start_artwork_wifi(path=PROFILE_PATH, radio=None, timeout_s=6, log=print):
    """Join the selected AP at startup; failure preserves local ESP-NOW use.

    Pin the BSSID, rather than just the SSID, so mesh nodes on different
    channels cannot separate the two ESP-NOW peers. No credentials are logged.
    The radio handles reconnects after an initially successful connection.
    """
    try:
        profile = load_profile(path)
    except (ValueError, TypeError, UnicodeError):
        log("[NET] artwork profile invalid; using local ESP-NOW")
        return False
    if profile is None:
        return False
    try:
        if radio is None:
            import wifi
            radio = wifi.radio
        expected_bssid = _bssid(profile["bssid"])
        if radio.connected:
            if bytes(radio.ap_info.bssid) != expected_bssid:
                log("[NET] another AP is already active; artwork join skipped")
                return False
        else:
            # Channel zero searches all channels for the pinned AP, allowing
            # its channel to change since the setup scan without changing AP.
            radio.connect(profile["ssid"], profile["password"], bssid=expected_bssid,
                          channel=0, timeout=max(1, min(10, timeout_s)))
        if not radio.connected or bytes(radio.ap_info.bssid) != expected_bssid:
            log("[NET] artwork AP not confirmed; using local ESP-NOW")
            return False
        log("[NET] artwork Wi-Fi ready channel=%d" % radio.ap_info.channel)
        return True
    except Exception:
        # In particular, do not print an exception containing input strings.
        log("[NET] artwork Wi-Fi join failed; using local ESP-NOW")
        return False


def retry_artwork_wifi(path=PROFILE_PATH, reload_fn=None, log=print):
    """User-requested startup retry; never connect in the hot UART loop."""
    try:
        profile = load_profile(path)
    except (ValueError, TypeError, UnicodeError):
        log("[NET] configure artwork Wi-Fi over USB before retrying")
        return False
    if profile is None:
        log("[NET] configure artwork Wi-Fi over USB before retrying")
        return False
    if reload_fn is None:
        import supervisor
        reload_fn = supervisor.reload
    log("[NET] requested coordinated artwork Wi-Fi startup retry")
    reload_fn()
    return True

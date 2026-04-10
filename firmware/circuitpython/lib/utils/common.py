# endregion
DEBUG = False
TIME_UNKNOWN = "--:--"
_MAX_TRACK_TIME_MS = 24 * 60 * 60 * 1000

# endregion
# Function: dprint - Defines the behavior for `dprint`.
def dprint(*a):
# region dprint
# dprint handles dprint logic. #
    # Conditional check
    if DEBUG:
        print(*a)

# endregion
    # Loop through items
# Function: _sanitize_text - Defines the behavior for `_sanitize_text`.
def _sanitize_impl(txt, max_len, ellipsis):
    if txt is None:
        return "—"
    out = []
    out_append = out.append
    ord_ = ord
    for ch in str(txt):
        o = ord_(ch)
        out_append(ch if 32 <= o <= 126 else " ")
    s = "".join(out).replace('"', "'").strip()
    if not s:
        s = "—"
    if len(s) > max_len:
        trim = max_len - len(ellipsis)
        if trim < 0:
            trim = 0
        s = s[:trim] + ellipsis
    return s


def _sanitize_text(txt, max_len=48):
# region _sanitize_text
# _sanitize_text handles  sanitize text logic. #
    return _sanitize_impl(txt, max_len, "…")
# endregion

# endregion
    # Loop through items
# Function: _fmt_ms - Defines the behavior for `_fmt_ms`.
def _fmt_ms(ms):
# region _fmt_ms
# _fmt_ms handles  fmt ms logic. #
    # Conditional check
    if ms is None:
    # Return the result
        return "—"
# endregion
    # Try block to catch exceptions
    try:
        ms = int(ms)
    # Handle exceptions
    except Exception:
    # Return the result
        return _sanitize_text(ms, max_len=16)
# endregion
    # Conditional check
    if ms < 0:
        ms = 0
    total = ms // 1000
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    # Conditional check
    if h > 0:
    # Return the result
        return "%d:%02d:%02d" % (h, m, s)
# endregion
    # Return the result
    return "%d:%02d" % (m, s)
# endregion


# Function: _parse_uint - Parse unsigned decimal text/bytes without regex
def _parse_uint(raw):
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, (bytes, bytearray, memoryview)):
        start = 0
        end = len(raw)
        while start < end and raw[start] <= 32:
            start += 1
        while end > start and raw[end - 1] <= 32:
            end -= 1
        if start >= end:
            return None
        val = 0
        while start < end:
            b = raw[start]
            if 48 <= b <= 57:
                val = (val * 10) + (b - 48)
                start += 1
                continue
            return None
        return val
    s = str(raw).strip()
    if not s:
        return None
    val = 0
    for ch in s:
        o = ord(ch)
        if 48 <= o <= 57:
            val = (val * 10) + (o - 48)
            continue
        return None
    return val


# Function: _normalize_track_time_ms - Normalize media times to canonical milliseconds
def _normalize_track_time_ms(raw, ref_ms=None, from_attr=False):
    if ref_ms is not None:
        ref_ms = _parse_uint(ref_ms)
        if ref_ms is not None and (ref_ms <= 0 or ref_ms > _MAX_TRACK_TIME_MS):
            ref_ms = None
    val = _parse_uint(raw)
    if val is None:
        dprint("[TIME] invalid:", raw)
        return None
    if val < 0:
        dprint("[TIME] negative:", raw)
        return None
    if from_attr and val > 0:
        scaled = val * 1000
        if ref_ms is not None:
            direct_delta = abs(val - ref_ms)
            scaled_delta = abs(scaled - ref_ms) if scaled <= _MAX_TRACK_TIME_MS else None
            if scaled_delta is not None and (scaled_delta + 1000) < direct_delta:
                dprint("[TIME] attr seconds->ms:", raw, "=>", scaled)
                val = scaled
        elif val < 1000 and scaled <= _MAX_TRACK_TIME_MS:
            dprint("[TIME] attr seconds heuristic:", raw, "=>", scaled)
            val = scaled
    if val > _MAX_TRACK_TIME_MS:
        dprint("[TIME] out of range:", raw)
        return None
    return val


# Function: _fmt_track_time_ms - Format canonical or attr-derived media times
def _fmt_track_time_ms(raw, ref_ms=None, from_attr=False):
    val = _normalize_track_time_ms(raw, ref_ms=ref_ms, from_attr=from_attr)
    if val is None:
        return TIME_UNKNOWN
    return _fmt_ms(val)


# Function: hexdump - Hex dump utility for debugging
def hexdump(data, width=16):
    if not data:
        return "<empty>"
    hex_strs = ["%02X" % b for b in data]
    if width and len(hex_strs) > width:
        lines = []
        for i in range(0, len(hex_strs), width):
            lines.append(" ".join(hex_strs[i:i+width]))
        return "\n".join(lines)
    return " ".join(hex_strs)


# Public wrapper for sanitize_text with test-compatible defaults
def sanitize_text(txt, max_len=100):
    # Use "..." instead of "…" for test compatibility
    return _sanitize_impl(txt, max_len, "...")


# Public wrapper for fmt_ms with test-compatible formatting
def fmt_ms(ms):
    # Reuse internal _fmt_ms logic to avoid duplication
    base = _fmt_ms(ms)

    # Preserve special/invalid outputs as-is
    if base == "—":
        return base

    parts = base.split(":")
    # h:mm:ss case (three parts) or unexpected formats are returned unchanged
    if len(parts) != 2:
        return base

    minutes, seconds = parts
    # Only adjust if both components are purely digits
    if minutes.isdigit() and seconds.isdigit() and len(minutes) == 1:
        # Zero-pad minutes for test compatibility (e.g., "0:05" -> "00:05")
        return "0%s:%s" % (minutes, seconds)

    return base

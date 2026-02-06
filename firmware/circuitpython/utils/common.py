# endregion
DEBUG = True

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
def _sanitize_text(txt, max_len=48):
# region _sanitize_text
# _sanitize_text handles  sanitize text logic. #
    # Conditional check
    if txt is None:
    # Return the result
        return "—"
# endregion
    out = []
    out_append = out.append
    ord_ = ord
    max_len_minus_one = max_len - 1
    # Loop through items
    for ch in str(txt):
        o = ord_(ch)
        out_append(ch if 32 <= o <= 126 else " ")
    s = "".join(out).replace('"', "'").strip()
    # Conditional check
    if not s:
        s = "—"
    # Conditional check
    if len(s) > max_len:
        s = s[:max_len_minus_one] + "…"
    # Return the result
    return s
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


# Function: hexdump - Hex dump utility for debugging
def hexdump(data, width=16):
    """Format bytes as hex string for debugging."""
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
    """Sanitize text for display (public API with test-compatible defaults)."""
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

    # Use "..." instead of "…" for test compatibility
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."

    return s


# Public wrapper for fmt_ms with test-compatible formatting
def fmt_ms(ms):
    """Format milliseconds as time string (public API with test-compatible formatting)."""
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

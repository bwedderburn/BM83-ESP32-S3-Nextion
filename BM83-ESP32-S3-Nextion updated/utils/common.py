import time

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
    # Loop through items
    for ch in str(txt):
        o = ord(ch)
        out.append(ch if 32 <= o <= 126 else " ")
    s = "".join(out).replace('"', "'").strip()
    # Conditional check
    if not s:
        s = "—"
    # Conditional check
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
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
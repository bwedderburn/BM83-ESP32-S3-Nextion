# Protocol and parsing robustness audit — 2026-10-05

Scope: host-provable audit of BM83 framing/checksum recovery, Nextion token
parsing, and text sanitization. No firmware behavior or tests were changed.

## Findings

| ID | Severity | Effort | Confidence | Location | Summary |
|---|---|---|---|---|---|
| P-01 | Medium | S | High | `firmware/circuitpython/lib/bm83/bm83.py:1334-1385` | Fragmented GEA response length has no aggregate ceiling; already tracked by open issue [#146](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/issues/146). |
| P-02 | Low | S | High | `firmware/circuitpython/lib/utils/common.py:9-29`, `firmware/circuitpython/lib/nextion/display.py:157-159` | Sanitizer fallback em dash is replaced with `?` by the ASCII-only Nextion TX path. |

### P-01 — Unbounded fragmented GEA aggregate

BM83 UART frames are length- and checksum-validated before dispatch, and
`Bm83.poll()` bounds its receive buffer. Separately, `parse_gea_0x5d()` accepts
a 16-bit aggregate length and retains fragments until that length is reached.
It has a fragment timeout, but no smaller aggregate-size cap. The proposed
oversize/reset/recovery test and parser fix are already recorded in the open
`code-health` issue #146; this audit does not duplicate that issue.

This remains a firmware behavior change and must be verified with BM83 serial
captures on the unit before merge.

### P-02 — Non-ASCII sanitizer fallback

Normal sanitized characters are restricted to printable ASCII and quotes and
backslashes are replaced. However, `_sanitize_impl()` returns `"—"` for `None`
and for input that becomes empty after cleaning. `Nextion.tick()` encodes
commands with `encode("ascii", "replace")`, so the fallback is transmitted as
`?`, not as the intended dash. This also conflicts with the sanitizer comment
that its output stays within ASCII.

The normal firmware token parser is bounded and tolerant of fragmentation:
`read()` consumes only available bytes, limits UART reads to 256 bytes, caps the
RX buffer, and accepts only allowlisted tokens. A token is accepted either
exactly or after a NUL boundary, after at most one known status byte is
stripped from each edge (`_extract_token()`), and with an optional trailing
`0x66` + page-id page-return sequence removed (`_is_token_frame()`). No additional token-parsing weakness was confirmed. The separate
`process_bytes()` helper is only called by host tests and is not a runtime UART
input path.

#### `code-health` issue

Filed as [#165](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/issues/165)
(`utils: keep sanitized fallback text within ASCII`).

**Failing-test sketch:**

```python
def test_sanitizer_empty_and_none_fallbacks_are_ascii():
    for value in (None, "", "\x00"):
        result = _sanitize_text(value)
        assert all(32 <= ord(char) <= 126 for char in result)
```

The current implementation fails because each input returns an em dash. A
minimal proposed fix is to use an ASCII fallback in both early/empty cases:

```diff
-        return "—"
+        return "-"
...
-        s = "—"
+        s = "-"
```

This changes firmware under `firmware/circuitpython/lib/`, so it stays behind
the normal gate: rerun `build_mpy.sh`, verify in a host test that the emitted
command stays ASCII, and check the display on the unit before merge.

## Verification

Audit-only; no firmware files or tests were edited. The full strict flake8 and
pytest checks passed: strict flake8 reported 0 findings, and pytest reported
233 passed, 1 skipped. A host reproduction confirmed that `None`, `""`, and
`"\x00"` currently sanitize to `"—"` and encode to `b"?"` on the Nextion TX
path.

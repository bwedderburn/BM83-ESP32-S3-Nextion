# Firmware code review — 2026-05-26

Scope: `firmware/circuitpython/lib/bm83/bm83.py`, `blehid/ble.py`, `nextion/display.py`, `utils/common.py`, `utils/compat.py`, plus `firmware/circuitpython/main.py`. Uploaded files were verified byte-identical to the repo versions, so this review applies to both.

Findings are grouped by severity. Each item cites a file and line range and proposes a concrete change.

## P0 — Act on these first

### 1. Drift between running `main.py` and repo `main.py`
Running on D:\ has `VOL_REPEAT_MAX = 16`. The repo has `VOL_REPEAT_MAX = 2` (`firmware/circuitpython/main.py:24`). The 2-step cap gives roughly 1.5 s of repeat (initial 0.85 s delay + ~1 step), which is nearly unusable for volume. The 16-step cap on the running version is much closer to right but conflicts with item 2.

**Fix:** Commit the change to `main.py`, set the limit consistently with the time cap (see #2).

### 2. Volume hold-and-repeat limits disagree with each other
`main.py` hold-repeat logic (around the `vol_hold_active` block) caps repeats with two independent guards:
- `hold_elapsed > 2.0` (time)
- `vol_repeat_count >= VOL_REPEAT_MAX` (count)

With `VOL_REPEAT_MAX = 16`, `vol_repeat_interval_s = 0.35`, and `vol_initial_delay_s = 0.85`, the count cap would allow `0.85 + 16 × 0.35 = 6.45 s` of repeats, but the time cap stops everything at 2.0 s. The user sees the button "stop working" 1.15 s into the repeat phase.

**Fix:** Pick one. Recommendation:
```python
vol_initial_delay_s = 0.85
vol_repeat_interval_s = 0.20   # snappier
VOL_REPEAT_MAX = 30            # ~6 s hard cap on count
HOLD_MAX_S = 6.5               # matches the count cap
...
if hold_elapsed > HOLD_MAX_S or vol_repeat_count >= VOL_REPEAT_MAX:
    vol_hold_active = None
    vol_repeat_count = 0
```
Then drop the magic `2.0` literal.

### 3. Heartbeat is generating false-positive DEGRADED lines
`bm83.py:tick_heartbeat` (lines 367-417) flags **DEGRADED** any time the max inter-byte gap exceeds `_hb_degraded_warn_s = 0.2`. When the BM83 has no audio source and no BT link, multi-second silence is normal — the chip simply has nothing to emit. The serial log shows:
```
[BM83 RX] DEGRADED: max 76.53s in last 10s window (now 0.78s) | free=8134464
```
That's not a degradation; it's normal idle silence between boot and the first BTM_Status. The DEGRADED label is misleading.

**Fix:** Gate DEGRADED on having either a recent command outstanding or `self.connected`. Approximate patch:
```python
elif effective_gap >= self._hb_degraded_warn_s:
    # Only meaningful when we expect traffic — connected, or recently
    # commanded the chip. Otherwise idle silence is normal.
    if self.connected:
        print("[BM83 RX] DEGRADED: max %.2fs in last %.0fs window "
              "(now %.2fs) | free=%d"
              % (effective_gap, self._hb_period_s,
                 instantaneous_gap, free))
    else:
        # Quiet "alive but idle" message at debug level.
        dprint("[BM83 RX] idle (max %.2fs) | free=%d"
               % (effective_gap, free))
```
This makes DEGRADED a real signal again: "the chip is connected but the UART went quiet."

## P1 — Real bugs and correctness risks

### 4. `bm83.poll()` slice-reassigns the rx buffer 3-4× per frame
`bm83.py` lines 313, 327, 342, 359 all do `self._rx = self._rx[…:]`. Each slice on a `bytearray` in CircuitPython allocates a new bytearray. Under any BT traffic burst (e.g., AVRCP metadata replies arriving back-to-back), this is several hundred allocations per second. The comments call this out (`CircuitPython bytearray doesn't support slice deletion`) but the workaround is the same head-index pattern you already use in `Nextion._txq` / `_tx_head`.

**Fix:** Track a `_rx_head` int. Advance it instead of reassigning `_rx`. Compact the buffer when `_rx_head` exceeds half of `len(_rx)` (same heuristic as `display.py:174`).

This is almost certainly the largest single CP-side allocation source in steady state. Without it, every BT reconnect storm pushes the heap toward GC churn.

### 5. `schedule_play_status` can move the deadline *later*
`bm83.py:767-773`:
```python
def schedule_play_status(self, delay_s=0.05):
    self._next_playstatus_at = time.monotonic() + delay_s
```
If `tick_avrcp` has already scheduled a poll for `now + 1.0` and a caller then does `schedule_play_status(0.05)`, fine — earlier. But if a caller passes `delay_s=2.0`, the deadline moves *out* and the next poll is delayed. The name says "schedule" but the semantics are "set," which is a footgun for future callers.

**Fix:** Apply `min()` semantics, like `schedule_attrs` (line 786) already does:
```python
def schedule_play_status(self, delay_s=0.05):
    t = time.monotonic() + delay_s
    if self._next_playstatus_at == 0.0 or t < self._next_playstatus_at:
        self._next_playstatus_at = t
```

### 6. `MMI_ENTER_PAIRING = 0x5D` collides with `EVT_AVRCP_VENDOR_DEP_RSP = 0x5D`
`bm83.py:100, 93`. They're used in different contexts (one as the second byte of an MMI payload, the other as a top-level OP code), so it isn't a runtime bug. But it is a confusing collision. If you ever `grep '0x5D'` you can't tell which constant a hit refers to.

**Fix:** Optional. If you want the safety, alias `MMI_ENTER_PAIRING` as `MMI_PAIR = 0x5D` and prefer the unambiguous name at callsites.

### 7. `_pair_attempt_limit` may give up before a slow human finishes the Windows pairing dialog
`ble.py:_ensure_paired` (lines 379-489): `_pair_attempt_limit = 4`, polled every `_pair_retry_s = 2.0` — so we stop polling 8 s after connect. The one-shot drive happens at 6 s (`_pair_auto_after_s = 6.0`). On Windows, the "Allow" dialog frequently takes longer than 8 s for an unhurried click, especially if the user wasn't expecting it. After the limit, `_need_pairing_check = False` and we never re-check, so `[BLE] Paired/encrypted` never prints even if pairing eventually completes (sends still work, but the log misleads).

**Fix:** Extend the budget by ~3×:
```python
self._pair_retry_s = 2.0
self._pair_attempt_limit = 12   # ~24 s of polling, covers slow Windows clicks
```
Or, simpler: don't give up — keep polling forever, the cost is one `getattr` per ~2 s.

### 8. `last_avrcp_rx_at` is dead code in `main.py`
Updated in two places (around `pdu == 0x30` and `pdu == 0x31`/`0x5D` handlers) but never read. Comment says "retained for future use." Delete it or wire it up. Right now it's pure overhead per metadata frame.

### 9. `BT_POWEROFF` token defined but never dispatched
`display.py:24` includes `b"BT_POWEROFF"` in `TOK_BT`, but `main.py`'s token dispatch only handles `b"BT_POWER"` (which already calls `bm.power_toggle()`). If your Nextion HMI ever emits `BT_POWEROFF`, it's parsed and then silently discarded.

**Fix:** Either wire it in main.py:
```python
elif tok == b"BT_POWEROFF":
    bm.power_off_cmd()
```
or remove from `TOK_BT`.

### 10. `flush_page(nx.current_page)` called with `current_page == None`
In `main.py`'s aux-flip block (`if aux_mode != aux_mode_prev:`), after `enter_aux_mode()` / `exit_aux_mode()`, you call `flush_page(nx.current_page)` without a None guard. `flush_page(None)` falls through both branches without crashing, but it's a wasted call and the intent is unclear.

**Fix:** Guard it:
```python
if nx.current_page is not None:
    flush_page(nx.current_page)
```

## P2 — Memory and performance, CircuitPython-specific

### 11. Each ticker calls `time.monotonic()` independently
`main.py` already does `monotonic = time.monotonic` and computes `now` at the top of every loop iteration. But `bm.tick_avrcp`, `bm.tick_avrcp_attrs`, `bm.note_btm_state`, `bm.check_connection_watchdog`, `bm.schedule_play_status`, `bm.schedule_attrs`, and several ble.py helpers all call `time.monotonic()` again internally. On CP each call allocates a float; with main.py running its loop hot, this is the second-largest steady-state alloc source after #4.

**Fix:** Thread `now` through. `tick_heartbeat` already accepts it as an optional arg — extend the pattern:
```python
def tick_avrcp(self, now=None):
    if not self.connected:
        return
    if now is None:
        now = time.monotonic()
    ...
```
…and pass `now` from `main.py`'s loop. Touches ~8 methods.

### 12. `bytes(self._rx[3:3+ln])` per-frame copy
`bm83.py:337`. Combined with the slice-reassignment in #4, every successful frame allocates twice. Once you have a head-index buffer, you can `memoryview` over the slice instead and only `bytes()` it when handing to a public caller that needs immutability.

### 13. `avrcp_register_notification` allocates per call
`bm83.py:716` constructs three bytes objects (`bytes([event_id])`, `int(interval_s).to_bytes(4, "big")`, then the concatenation). Pre-compute the common cases:
```python
_REGNOTIF_STATUS = bytes([0x01]) + (0).to_bytes(4, "big")
_REGNOTIF_TRACK  = bytes([0x02]) + (0).to_bytes(4, "big")
_REGNOTIF_POS_1S = bytes([0x05]) + (1).to_bytes(4, "big")

def avrcp_reregister_track_changed(self, db=0):
    ...
    self.send(self.OP_AVC_VENDOR_CMD, bytes([db]) + self._avc_payload(0x31, _REGNOTIF_TRACK))
```
Only matters if you're re-registering frequently (e.g., after every TrackChanged event); right now the throttles in `_track_changed_reg_throttle_s` / `_status_reg_throttle_s` / `_pos_reg_throttle_s` keep this rare.

### 14. `_send_ccc` allocates a new `ConsumerControl` on every connect
`ble.py:_on_connect` lines 338-342 unconditionally re-instantiates `ConsumerControl(self._hid.devices)`. Comment says "avoid a stale binding if adafruit_ble swapped the HID device out." Defensible, but the BLE GATT pipe is stable across reconnects in practice. Worth measuring: try keeping the original `self._cc` and only reinit on a verifiable failure.

## P3 — Dead code and noise

### 15. ~~`_checksum_range` is unused~~ — RETIRED
Originally flagged as dead code. The rx head-index refactor (P1 #4) put it back into the hot path: it now computes the body checksum in place over a memoryview slice, with no per-frame `bytes()` copy. Keep the function, keep the docstring.

### 16. `parse_avrcp_metadata` looks like a test-only helper bolted onto the production class
`bm83.py:942-961`. Doesn't share format with `parse_gea_0x5d`. If it's only for tests, move it to the test module.

### 17. `# endregion` comments scattered through every file
Looks like a regenerative formatter ran and left orphan markers. Examples: `bm83.py:7-8` ("# endregion" twice in a row, with no opening); `display.py:4, 35, 53, 60, 88, 93, 100, 105, 119, 135, …`. They don't affect runtime but add ~50 lines of pure noise per file.

**Fix:** Sweep them out. `grep -rn '^# endregion' firmware/circuitpython/` to find them all.

### 18. Auto-generated docstrings
Lines like `# bm83 class encapsulates functionality related to bm83. #` (`bm83.py:24`) and `# __init__ handles   init   logic. #` (multiple) are content-free. Same root cause as #17.

### 19. `Bm83.frame` is a public alias for `_frame`, used only by tests
`bm83.py:229-230`. Fine to keep, but mark it explicitly in a docstring so it's not confused with new public API.

## P4 — Small, optional cleanups

### 20. `_extract_token` followed by `_is_token_frame` re-scans the same bytes
`display.py:226-244, 250-269`. `_is_token_frame` calls `_extract_token` and then re-loops over the result re-validating bytes that `_extract_token` already filtered. The second loop is a no-op by construction.

**Fix:** Drop the second loop, keep just `return f if f in TOKENS else None`.

### 21. EQ user constant inconsistency
`display.py:19` maps `b"EQ_USER" -> 11`. `bm83.py:115` has `EQ_SEQ = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11)` skipping 10 entirely. The comment ("Aligned with BM83 EQ_SEQ") explains it, but the skip means `eq_index = 10` of `EQ_SEQ` is the legal "USER" entry — there is no "10" mode. Consider documenting in the BM83 docstring why 10 is skipped (presumably reserved by the chip).

### 22. `_gea_frag_timeout_s = 5.0` is generous
`bm83.py:147`. Five seconds to receive the trailing fragment of one metadata reply is a long time. If the BM83 ever drops the trailing fragment, you carry the stale prefix for 5 s before age-out. Could safely drop to 1.5 s without losing real responses.

## Symptom-to-finding map (from the serial log you posted)

The DEGRADED noise (`max 10.21s in last 10s window`, `max 76.53s in last 10s window`) is finding **#3**.

The fact that *some* DEGRADED lines were legitimate — e.g., a stall during AVRCP metadata exchange right after `[BTM] Connected` — points at finding **#4** (rx buffer slice cost during burst traffic). Fixing #4 should reduce the in-burst gaps; gating DEGRADED on `self.connected` (#3) should silence the boring idle ones.

`Code stopped by auto-reload. Reloading soon.` is normal CP behavior whenever a file changes on the CIRCUITPY drive — not a bug.

`free=8.13-8.16 MB` stayed in a narrow band across the log, so there's no leak. Allocation pressure is real (the swings inside that band are 12-15 KB per heartbeat window) but bounded.

## Suggested merge order

1. Land #3 (gate DEGRADED on connected) — silences the log immediately.
2. Land #1 + #2 together (commit the `VOL_REPEAT_MAX` change and pick consistent limits).
3. Land #4 (rx head-index) — biggest perf win.
4. Sweep #8, #9, #10, #15, #16, #17, #18 — pure cleanup, easy PR.
5. Consider #5, #7, #11 as a follow-up.

The rest (#6, #12, #13, #14, #19, #20, #21, #22) can ride along whenever those areas get touched.

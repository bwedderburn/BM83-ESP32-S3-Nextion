# Firmware code review + fixes — 2026-08-02

Scope: full repo review of `main` @ `d280478` (firmware tree, tests, CI,
build/deploy scripts), followed by the fixes below. All prior findings from
[code-review-2026-05-26.md](code-review-2026-05-26.md) were verified as
addressed before this pass. Host suite after changes: **96 passed** (5 new
regression tests), flake8 critical checks clean, `ast`-verified that the
comment cleanup changed no code.

## Fixed in this pass

### 1. Nextion RX buffer was unbounded (`nextion/display.py`)
`_read_more()` extended `self._rx` with no cap; only a `0xFF 0xFF 0xFF`
terminator ever shrank it. A disconnected display, floating RX pin, or wrong
baud feeds TERM-less bytes (~960 B/s at 9600 baud) that accumulated forever —
eventually heap starvation. The BM83 side already capped its buffer at 4096;
the Nextion side now caps at `_RX_MAX = 512` and keeps a `_RX_KEEP = 128`
tail so a legitimate partial frame straddling the trim still resyncs.
Regression tests: `test_nextion_rx_buffer_capped_on_termless_garbage`,
`test_nextion_rx_cap_still_parses_tokens_after_trim`.

### 2. Truncation ellipsis rendered as `?` on the display (`utils/common.py`)
`_sanitize_text` appended U+2026 `…` after guaranteeing ASCII 32–126, and
`Nextion.tick()`'s `encode("ascii", "replace")` turned it into `?` — every
truncated title/artist ended in a stray question mark. Now uses ASCII `"..."`
so the whole pipeline stays inside the sanitizer's own invariant. This
escaped because tests asserted on the `sanitize_text` public wrapper (which
already used `"..."`) rather than the production `_sanitize_text` path.
Regression test: `test_internal_sanitize_text_truncation_stays_ascii`.

### 3. Machine-generated comment noise stripped (`main.py`, `bm83/bm83.py`, `setup.py`)
Removed 309 auto-generated lines (`# Conditional check`, `# Loop through
items`, `# Return the result`, `# Function: X - Defines the behavior…`,
mismatched `# region`/`# endregion` markers, `# x handles x logic. #`
pseudo-docstrings). Every removal was verified AST-identical — comments
only. Informative fragments buried in the noise were converted to real
docstrings (`next_eq` throttle note, power state-machine notes,
`parse_avrcp_metadata` test-only marker). `main.py` 594→517 lines,
`bm83.py` 972→811.

### 4. Housekeeping
- `setup.py`: real author/URL instead of "Your Name" / `yourusername` placeholders.
- `pytest.ini`: dropped `--maxfail=1` so CI reports every failure in one run
  (use `pytest -x` locally for fail-fast).
- `dist/circuitpython/main.py` re-synced verbatim from firmware per the
  build contract. Run `./build_mpy.sh` before the next `--mpy` deploy.

## Experimental: first-play stall mitigation (needs hardware verification)

**Symptom (reported on the Windows / Apple Music central):** on the first
press of play after the app starts — or after a BT disconnect/reconnect —
audio is heard for a few seconds and then cuts out **while the app still
shows the track as playing**. A pause/stop followed by play restores sound,
and everything is fine after that.

**Why the firmware is a suspect:** the transport staying in "playing" while
sound dies points at the sink side — the A2DP media path is suspended or
muted underneath a source that is still streaming. That is precisely the
failure signature `bm83.py`'s own throttle comments record: some BM83
firmware revs choke on rapid AVRCP register-notification calls during
CT-side establishment and *silently drop the A2DP profile while leaving the
BT link nominally up*. The app never sees a state change (AVRCP stays up),
and pause→play recovers because it forces a fresh AVDTP suspend→start cycle
that re-opens the media channel. Two firmware bursts line up with the
symptom window:

1. **At the CONNECTED edge** the old code sent three register-notification
   commands back-to-back (0x01, 0x02, 0x05) plus GetPlayStatus 50 ms later.
2. **At first play** the status-changed handler re-registered 0x01,
   scheduled GetPlayStatus at +0.05 s and force-scheduled the heavyweight,
   often fragmented GetElementAttributes exchange at +0.15 s — all inside
   the A2DP stream-start window. On the *second* play, metadata is already
   cached and the re-registration throttles are warm, so the burst doesn't
   recur — matching "fine after that".

**Changes:**
- `Bm83.schedule_avrcp_notifications()` + `tick_notif_regs()`: the CONNECTED
  edge now queues the three registrations at +0.25 s / +0.75 s / +1.25 s and
  the main loop releases them on schedule. The queue self-clears if the link
  drops. GetPlayStatus moved to +1.6 s, initial metadata to +2.0 s.
- Play-start metadata request moved from +0.15 s to +1.0 s (`force=True`
  kept). Cost: the title appears ~1 s later on a fresh connect.
- Tests: `test_schedule_avrcp_notifications_staggers_registrations`,
  `test_tick_notif_regs_drops_queue_when_link_lost`.

**Hardware test plan:**
1. Flash, power-cycle, connect from b-intel, open Apple Music, press play
   *immediately*. Repeat ~5×, including after a BT disconnect/reconnect.
2. If audio still cuts out, the serial log at the cutout moment
   discriminates between the remaining suspects:
   - `[BTM_Status] state=0x81` / `[AUX] inferred …` lines → the BM83
     flapped its audio-source state around stream start (same family as the
     documented Line-In jack-detect miss; the fix would be debouncing
     aux_mode entry / gating `kick_aux_routing`, not this patch). Was an
     AUX cable plugged in at the time?
   - A dense run of AVRCP TX right before the cutout, or `[BM83 RX]`
     DEGRADED/SILENT right after → the AVRCP-churn hypothesis this patch
     targets; if the patch didn't fully cure it, stretch the stagger.
   - Nothing unusual at all → BM83-internal routing miss on the first AVDTP
     START (chip-level quirk), or the app itself.
3. Control test with a different player (Spotify / YouTube in a browser) on
   b-intel: if only Apple Music cuts out, the suspect is the app — Apple
   Music on Windows has widely reported first-play Bluetooth dropouts
   (audio dies, timeline keeps moving) that no sink-side firmware can fix.
   If every player does it, it is chip/firmware side.
4. To revert just this experiment: in `main.py`'s CONNECTED handler, replace
   the `schedule_avrcp_notifications((...))` block with the three direct
   `bm.avrcp_register_notification(...)` calls, restore
   `schedule_play_status(0.05)` / `schedule_attrs(0.8)`, and change
   `schedule_attrs(1.0, force=True)` back to `0.15`.

## Hardware session addendum — 2026-08-02 evening (live serial capture)

First hardware results with the staggered build, captured over COM3 on
b-intel while Brian tested with Apple Music:

- **Cold-start first play:** audio dropped for ~1 s and *self-recovered* —
  previously it stayed dead until a manual pause→play. Partial win for the
  stagger on this path.
- **Quick BT off/on reconnect:** captured `0x0C 0x08 0x11 0x0F 0x01` →
  `0x15 0x06 0x0B` (AVRCP/A2DP/ACL teardown → standby/discoverable → ACL
  back → A2DP → AVRCP; codes verified against datasheet §7.2 p.169) with
  **no re-registration line and 1 Hz polling running throughout**. The
  teardown beat the 2 s disconnect debounce, so `connected` never flipped,
  the CONNECTED edge never fired, and the mitigation never executed on this
  path — first play after reconnect cut out exactly as before. This also
  confirmed review finding "disconnect debounce vs. watchdog" with live
  evidence.
- **Heartbeat:** every healthy playback window printed DEGRADED — the max
  inter-byte gap ≈1.0 s *is* the 1 Hz GetPlayStatus cadence; the 0.2 s
  threshold predated that polling.

Round-2 changes (all host-tested, 98 passing):

- `Bm83.AVRCP_DOWN_STATES` (0x00/0x0C/0x0F/0x11) sets an `_avrcp_suspended`
  gate: `tick_avrcp`, `tick_avrcp_attrs`, and `tick_notif_regs` go quiet the
  moment a teardown state is seen, pending registrations are dropped, and
  polling resumes with a 1.5 s settle grace when a connected state returns —
  no more commands landing on a dead or half-established AVRCP channel.
- `main.py`: `BTM_TEARDOWN_STATES` clears `avrcp_notifs_registered`; the
  registration trigger widened to `change == "CONNECTED" or state == 0x0B`
  so a reconnect re-arms the staggered registrations; the AUX-mode probe is
  gated on `avrcp_suspended` too.
- `_hb_degraded_warn_s` 0.2 → 1.4 s (poll period + grace).

## Round 3 — the muted-path wedge, caught live, and the stream kick

Round-2 results: cold-start first play **clean** (no interruption). Reconnect
first play still silent — and this time the wedge state was captured while
active: the app showed playing, the Nextion metadata **and track time kept
updating**, sink-side AVRCP play/pause visibly controlled the app, and the
serial log showed the chip pinned at `state=0x82` ("A2DP is my active
source") for minutes — while outputting nothing. So every protocol layer was
healthy; only the BM83's internal audio path was dead. This is the A2DP
sibling of the documented Line-In jack-detect miss ("path stays muted until
replug").

Recovery experiment: a **quick** app pause/play did NOT restore sound; a
pause → **~2 s wait** → play DID. The gap is the active ingredient — the
source has to fully tear the stream down before the restart re-engages the
chip's routing.

Fix: a one-shot **stream-restart kick** (`Bm83.maybe_stream_kick` /
`tick_stream_kick`). Armed when AVRCP resumes after a suspension (i.e., a
link bounce happened); at the first "playing" status it sends AVRCP PAUSE,
waits 2.5 s, then PLAY (Music_Control actions 0x06/0x05, datasheet §5.2.4).
Guards: strictly one-shot per resume, never fires on cold connects, never
under AUX routing, aborts if the link drops mid-gap, cleared on disconnect.
Cost when the path isn't actually wedged: one audible ~2.5 s pause-resume at
the first play after a reconnect. Host-tested, 101 passing.

**Round-3 hardware result — kick DISABLED by default.** The serial log shows
the kick executed exactly as designed on a real reconnect (suspend through
`0x0C…0x0F` with zero polls into the dead link, staggered re-registration at
`0x06`/`0x0B`, `[KICK] pause sent` at the first playing status, `[KICK]
play sent` 2.5 s later) — and the audio path stayed muted anyway.
Sink-initiated AVRCP pause/play is evidently not equivalent to the manual
app-side pause → 2 s → play. The kick now ships behind
`STREAM_KICK_ENABLED = False` in `main.py` (machinery + tests retained).

**Where this leaves the reconnect wedge:** cold-start first play is fully
fixed (verified twice on hardware). After a BT off/on reconnect, the BM83's
audio path can come back muted — chip pinned at `0x82`, all of AVRCP healthy
— and that instance also showed a host-side component (Apple Music's own
timeline froze, then self-recovered, still silent). Manual workaround:
in the app, pause → wait ~2 s → play; escalate to BT off/on, then a unit
power-cycle. The real fix likely lives at the chip-config level
(BTM_Utility_Function / vendor audio-path options, or a BM83 firmware
behavior documented in Microchip's MSPK2 errata) — a research task, not an
AVRCP-timing tweak. Also worth one control test: reproduce the reconnect
wedge with a different source app (Spotify / browser) to size Apple Music's
contribution.

## Noted, deliberately not changed

- **Disconnect debounce vs. watchdog:** a single non-connected BTM_Status
  right after active traffic is debounced away (`_disconnect_hold_s`), so a
  one-shot disconnect report can leave `connected=True` until the 90 s
  watchdog. Left alone — needs hardware observation of the BM83's actual
  event cadence, and the debounce exists to prevent AUX flapping.
- **`recovered_src/`** (stale divergent copy) and the 33 MB `Documents/`
  folder (incl. a third-party `.exe`): repo hygiene calls for the owner.
  Note: untracked duplicates of the Documents files sit at the repo root of
  the local working tree — a `git add .` would double them into history.
- **BLE-unavailable volume UX:** volume presses silently no-op in BT mode
  when no BLE central is connected; a display hint would help but touches
  the UI layout.

# Incident — phantom AUX and a silent BM83 (2026-08-26)

## Reported

During normal Bluetooth playback (Windows / Apple Music on b-intel): AUX mode
would switch itself on at random, metadata disappeared, and every transport
control (play, next, prev, EQ) stopped working. Sometimes the "AUX IN" label
went blank while the firmware still behaved as though AUX were active. Windows
playback controls and audio output were unaffected throughout.

## Method

Captured the live serial console while the fault was present. Two observations
drove the whole diagnosis:

1. The board printed **nothing at all** — not even the 10s heartbeat.
2. A Ctrl-C returned `KeyboardInterrupt` at `main.py: sleep(0.005)`, i.e. the
   Python loop *was* running normally.

So: firmware healthy, but producing no output and no useful behaviour.

## Root causes (three, stacked)

### 1. Phantom AUX — `should_show_aux()` conflated two states

The fallback `return not self.connected` was written as a *boot-window* guess
("powered, no BT link, never saw a source event ⇒ probably AUX"). But
`_mark_disconnected()` sets `audio_source = None`, which re-creates exactly the
"never saw a source event" condition. So **every** link demotion during A2DP
playback re-armed the boot heuristic, which then asserted AUX.

`main.py` gates `BT_PLAY` / `BT_PREV` / `BT_NEXT` on `aux_mode`, and
`push_meta_updates()` suppresses metadata in AUX — so one wrong boolean
produced the entire reported symptom set. Audio was unaffected because the
BM83 streams A2DP without host involvement.

**Fix:** `_source_ever_seen` latches on the first `0x80/0x81/0x82`. Once real
source reporting has happened, AUX requires positive evidence (a real `0x81`)
and the link-state heuristic never runs again.

### 2. The BM83 stopped reporting after an ESP32-only reboot

`init_link()` — which sends `Event_Mask_Setting` (0x03) and
`BTM_Utility_Function` (0x13) to enable event reporting — only ran from the
power-on state machine. The ESP32 reboots constantly (USB auto-reload, edits,
resets) while the BM83 keeps running across those reboots. Result: a powered,
linked, actively streaming module that reported **nothing** to the host. The
firmware saw no metadata, no link state, and every command was a silent no-op.

Confirmed on hardware: a `Read_Local_BD_Address` — which the datasheet (§4.5.1)
says must be ACKed within 200ms in any state — got zero bytes back.

**Fix:** `tick_boot_init()` sends the handshake once, ~1.5s after boot,
regardless of who powered the module. Plus `power_on` is now *inferred from the
chip's own reporting* rather than tracking only what we powered ourselves.

### 3. Nothing could recover a false "disconnected"

`tick_avrcp()` returns early when not connected, so once the link was demoted
the firmware sent nothing, the chip therefore replied nothing, and `connected`
could never come back. The state was terminal until a reboot. An unbounded
AVRCP suspension (`0x08`/`0x0C` with no following connected-state event) could
also stall polling forever and then starve the silence watchdog into demoting a
healthy link.

**Fixes:**
- `tick_link_recovery()` — probes with `Read_Local_BD_Address` every 5s while
  unlinked (deliberately *not* gated on `power_on`, which a silent module pins
  False), re-asserts `init_link()` every ~6th probe, and prints one actionable
  warning after sustained silence.
- `poll()` — any inbound frame proves the module is alive (`power_on = True`);
  an AVRCP response while "disconnected" proves the link and relinks.
- `tick_avrcp_resume()` — suspensions time out after 6s.
- The silence watchdog now requires **both** the connected-evidence clock and
  the raw RX-byte clock to be stale before demoting.

## Diagnostic defect worth calling out separately

The heartbeat routed its not-connected cases through `dprint` (silent with
`DEBUG=False`), so a genuinely wedged link produced **zero** console output —
indistinguishable from a crashed board. That ambiguity cost roughly 20 minutes
of misdiagnosis. It now prints a compact state line every 30s:

```
[BM83 RX] idle, RX silent 40.0s | power_on=0 src=-- aux=0 | free=8151584
```

**Rule adopted:** never go completely silent. Low-rate liveness beats no output.

## Verification

Live serial capture after deploy, on the previously-dead board:

```
[BM83] boot handshake -> enabling event reporting
[BM83] Link initialized
[BTM] AVRCP traffic while disconnected -> relinking
[AUX] cleared -> enabling AVRCP polling, hiding AUX indicators
[META] GetElementAttributes received: [1, 2, 4]
[PLAY/PAUSE] toggled ... [EQ] set to SOFT ... [PREV] triggered
```

Both new mechanisms fired and restored the session unaided; user confirmed
metadata, timing, EQ, play/pause and next/prev all working. Host suite: 127
passed.

## Design rules taken from this

1. Never assert a mode without positive evidence. Absence of evidence for one
   mode is not evidence for the other.
2. Every suspension must be time-bounded.
3. Every "disconnected" belief needs a probe that can prove it wrong, or a
   false negative is permanent.
4. Never go silent on the console.
5. A UI write issued while the page is unknown must be re-issued once it is
   known (`pending_flush`) — otherwise the panel keeps stale text, which is how
   "AUX IN blank but still acting as AUX" happened.

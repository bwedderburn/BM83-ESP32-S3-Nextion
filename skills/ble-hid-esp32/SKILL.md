---
name: ble-hid-esp32
description: Diagnose and fix cross-platform BLE HID pairing problems on ESP32-S3 (or ESP32-C3/S2) running CircuitPython + adafruit_ble + NimBLE. Use whenever the user is debugging BLE keyboard/mouse/consumer-control pairing that fails on Windows, iPhone, Android, or macOS — especially symptoms like "Windows lists my device under Other devices", "iPhone won't re-pair after Forget Device", "NimBLE crashes during erase_bonding", "fast connect-then-disconnect without pair dialog", "pairing works once then never again", "stale bond mismatch", or any bond-store / SMP-collision failure between a CircuitPython BLE peripheral and a central. Also use when designing a fresh BLE HID peripheral on this stack, so the person avoids the traps upfront.
---

# Cross-platform BLE HID pairing on ESP32 + CircuitPython

BLE HID pairing on ESP32 looks simple on paper (stand up an `HIDService`, start advertising, call `BLERadio().start_advertising(adv)`, done) but in practice it hits a thick layer of platform quirks, a brittle NimBLE stack, and a completely asymmetric bond-store model between central and peripheral. This skill captures the specific traps and their proven fixes from a working BM83-based CircuitPython project that spent many hardware-test cycles getting the cross-platform behaviour right.

Use this as a reference when you're either designing a new BLE HID peripheral on this stack or, more often, debugging one that seemed fine but fell apart the moment a user did "Forget Device" on their phone or PC.

## The core mental model

The single most important thing to internalise before touching code:

**The central (iOS / Windows / Android / macOS) and the peripheral (ESP32) each maintain their own bond store. The two stores can drift out of sync, and when they do, the central will refuse to pair again and the user has no obvious way to recover.** All the hard bugs in this domain flow from that asymmetry.

Concretely:

- The central stores an LTK (Long Term Key), the peripheral's address, and often the peripheral's advertised name in its own Bluetooth subsystem. On Windows this is the BthLEEnum cache; on iOS it's the Bluetooth database. "Forget Device" in the user-facing settings UI clears the *visible* entry, but may leave cached address / role / LTK data in a lower layer.
- The peripheral stores its side of the bond in NVS (on ESP32). `_bleio.adapter.erase_bonding()` clears this.
- Because the stores are on different devices with different lifecycles, the user can wipe one without the other — and this is what happens when "pairing used to work, now it doesn't."

Once you hold this picture, almost every symptom makes sense: central has an entry you cleared, tries to reconnect with a stale LTK, SMP handshake fails, connection drops within a second, user is confused.

## The seven rules that actually matter

These are the lessons that made the hardware-tested project work reliably across iPhone and Windows 11. Every one has a "why", not just a "do":

### 1. Do NOT set GAP `Appearance` to a specific HID subtype

It is tempting to set `BLERadio().appearance = 0x03C1` (HID Keyboard) or similar so Windows shows your device with a keyboard icon. **Don't.** Windows' BLE HID driver keys its bond cache on **MAC + HID role** (not on device name), and an advertised Appearance of HID Keyboard tells Windows "I'm that specific keyboard you already know." Windows will then silently attempt a stale-LTK reconnect on every advertisement you emit, bypassing the Add-device → Pair dialog entirely. The connection will come up for ~1 second, fail to encrypt, and drop — in a loop, with no way for the user to trigger a fresh pair from the UI.

Leaving Appearance unset (default `0x0000` / Unknown) makes Windows classify the device under "Other devices" in the settings list (cosmetic only — HID still works for ConsumerControl / keyboard / mouse data), and more importantly forces Windows through the normal Add-device → "Pair device? Allow" flow every time. That flow is the one the user needs.

iOS and Android are more forgiving and don't depend on Appearance for HID recognition.

### 2. Cycle the advertised device name on every bond wipe

Because Windows caches by MAC + role, even a clean NVS wipe on the peripheral may not defeat a stale Windows cache entry. The practical workaround is to present a *new identity* to the central each time you wipe. Append an incrementing counter to the advertised name:

    base_name = "My BLE Device"
    advertised_name = "My BLE Device"       # first boot, counter = 0
    advertised_name = "My BLE Device_1"     # after first EBIND
    advertised_name = "My BLE Device_2"     # after second EBIND
    ...

From the central's perspective each cycle is a brand-new device with no cached state, so "Add device → Pair" is the only available path. Persist the counter in a small file on CIRCUITPY (e.g. `/ble_counter.txt`) with a read-only-filesystem-safe fallback (see reference code). See `references/name_cycling.py`.

### 3. Never run `erase_bonding()` while connected or advertising

`_bleio.adapter.erase_bonding()` on NimBLE is brittle. If the radio is actively pumping (connected link or active advertisement), it can hard-crash the stack — which on ESP32-S3 / CircuitPython manifests as Thonny losing the COM port and the board requiring a power-cycle.

The fix is to treat the user's bond-wipe request as a *flag* rather than an immediate action. Buffer the request in a boolean, then service it from the main `tick()` loop only when the peripheral is fully disconnected. If the user pressed the button while connected, print a message telling them to disconnect from the central first and the wipe will happen shortly after. See `references/safe_erase_bonds.py` for the exact sequence: stop_adv → 50 ms settle → gc.collect() × 2 → 50 ms settle → erase_bonding → 50 ms settle → gc → start_adv(force=True).

Also rate-limit: add a ~30 second cooldown between successful erases. Back-to-back wipes crash the NimBLE stack. Initialise the last-erase timestamp well in the past (`-cooldown - 1`) so the *first* EBIND after boot isn't blocked by a false-positive cooldown check against `t=0`.

### 4. Never call `c.pair()` or `c.disconnect()` synchronously from a UI callback

Both calls are blocking on NimBLE and both can take 30-50 seconds to return when the bond stores disagree. Calling them from a Nextion-button-press handler (or any synchronous handler) starves the main loop: UART input from your BM83 / CSR / other BT audio module piles up, AVRCP handshake metadata times out, and in the worst case the call crashes the stack outright because the stack is mid-handshake when you pulled the rug out.

Treat both as operations to be driven from the main loop under controlled conditions (see rules 3 and 5), not from a button callback.

### 5. Drive pairing asymmetrically for iOS vs Windows

iOS auto-initiates BLE HID pairing within ~1-2 seconds of connecting to a peripheral that advertises an encrypted characteristic. Windows does not — it waits for either the central-side user to click "Pair" or the peripheral to send a Security Request.

The working pattern is a *hybrid* driver:

- **Passive observer phase** (first several seconds after connect): just watch `c.paired`. If it flips to `True` on its own, you're done. iOS handshakes complete here the vast majority of the time. Polling every ~2 seconds is plenty.
- **One-shot drive phase** (after ~6 seconds if still unpaired): call `c.pair()` exactly once, not in a loop. This rescues the Windows "I'm waiting for something to happen" case. 6 seconds is long enough that a user clicking through the Windows "Pair device? Allow" dialog will finish the pair first (avoiding a collision where our Security Request lands while the central is already mid-SMP), and short enough that the truly-stuck case gets a nudge before the user gives up.

Do not drive multiple times, and do not drive below ~5 seconds — a fast drive collides with user-mediated Windows pair flows and causes "Connection failed" in the central UI. See `references/hybrid_pair_driver.py`.

### 6. Diagnose fast-disconnect-without-pair explicitly in the log

The most common failure mode in the field is: central connects, realises its stored LTK doesn't match (because the peripheral's NVS was wiped), silently drops the link within a second or two, and the user sees nothing helpful on either side. Make this visible.

In your `_on_connect` callback, latch the current `time.monotonic()`. In `_on_disconnect`, compute uptime and check whether `c.paired` ever flipped to True during the connection. If uptime is under ~2 seconds and the connection never paired, print a clear multi-line hint naming the likely cause and the fix:

    [BLE] Fast disconnect without pairing — likely stale bond on
          central side. Fix: Forget Device on the phone/PC, then
          press EBIND on the device, then reconnect from the
          central's OTHER DEVICES list.

This turns a mysterious "it just doesn't work" into a self-explaining log line. See `references/fast_disconnect_detection.py`.

### 7. Log the peer address from the first pair-poll, NOT from `_on_connect`

`BLERadio.connections` is frequently still an empty list at the moment your connect-event handler fires — the peer record hasn't been linked into the list yet on NimBLE builds. Iterating there silently yields nothing and your `peer:` log line never appears.

Instead, set a `_peer_logged = False` latch in `_on_connect` and print the peer address from the first iteration of your pair-polling routine (one tick later), where `connections` is reliably populated. Once printed, latch `_peer_logged = True` so you only log once per connection.

Peer address is genuinely useful in a mixed-central log: iOS / Android use random resolvable addresses (different every reconnect), while Windows typically presents a stable public address. Even the *format* of the address tells you which central is in play without guessing.

## Putting it together

A CircuitPython BLE HID peripheral that wants to survive real cross-platform use ends up with a shape like this (full reference implementation under `references/`):

    BleHid:
        setup()               # read persisted name-cycle counter,
                              # build advertised name, start advertising
        tick()                # service connect/disconnect edges,
                              # poll pairing state, handle queued bond wipe
        request_erase_bonds() # pure flag-setter, cooldown-checked
        _do_erase_bonds()     # main-loop worker: safe sequence +
                              # name-cycle bump
        _ensure_paired()      # hybrid driver: passive, then one-shot
                              # drive after 6s; peer address logged here
        _on_connect()         # reset per-connection latches only;
                              # no blocking calls
        _on_disconnect()      # fast-disconnect-without-pair hint;
                              # immediate re-advertise
        volume(up), mute()    # HID ConsumerControl sends with
                              # minimum interval clamp

Ship all of this behind a `BLE_ENABLED` feature flag — at development time with a Thonny connection you often want BLE off so you can focus on the rest of the system.

## When you're debugging an existing peripheral

Follow this order — it matches the order of likelihood in real hardware work:

1. **Is `Appearance` set to an HID subtype?** If yes, that's almost certainly the root cause of the Windows problem. Remove it (rule 1).
2. **Does the peripheral cycle its name on bond wipe?** If no, add it (rule 2). This is what makes Windows actually show the Add-device dialog after a Forget Device.
3. **Does the bond-wipe button call `erase_bonding()` synchronously?** If yes, rewrite it as a flag + main-loop worker (rule 3). This is the NimBLE crash fix.
4. **Is `c.pair()` being called from a button callback, or in a tight loop?** If yes, move it to the main loop and make it one-shot with a grace period (rules 4 and 5).
5. **Do the logs say anything useful when pairing fails?** If not, add the fast-disconnect-without-pair hint (rule 6). This converts user-facing frustration into "oh, I need to Forget Device on my phone first, then press EBIND."
6. **Can you tell iPhone from PC connections in the log?** If not, log peer address from the first pair-poll (rule 7).

## Related reference files

- `references/name_cycling.py` — persistent counter helpers and the rename-after-erase flow
- `references/safe_erase_bonds.py` — the six-step NimBLE-safe erase_bonding sequence with cooldown + deferral
- `references/hybrid_pair_driver.py` — the passive-then-one-shot pairing poller
- `references/fast_disconnect_detection.py` — latches and log messages for bond-mismatch diagnostics
- `references/full_ble_py.py` — the complete working BleHid module from the reference hardware project, integrating all seven rules

## What this skill is NOT

- Not a guide to Bluetooth Classic (BR/EDR), A2DP, HFP, AVRCP — those run on a separate module (e.g. BM83, CSR8670) wired over UART; this skill is purely about the BLE side that carries HID.
- Not a replacement for reading the BLE / adafruit_ble / _bleio source when you hit something truly novel. It's a distilled set of traps and recipes that cover ~90% of what goes wrong in practice on this stack.
- Not applicable to Arduino / ESP-IDF native builds — the NimBLE quirks exist there too but the API surface is different. The principles (asymmetric bond stores, don't set Appearance, cycle the name) still apply.

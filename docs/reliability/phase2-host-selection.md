# BLE volume host selection: implementation and acceptance

The November 4 [B-Intel Phase 1 run](phase1-bintel-2026-11-04.md) is accepted
within its recorded scope. The November 5–6 Phase 2 tests verified the Windows
bench controls, a saved Raspberry Pi host, and the CrowPanel and badge changes
described below. Broader platform coverage and a new qualified timing window
remain separate gates.

## Intended behavior

CrowPanel Settings opens **Volume hosts**. **Disconnect** requests a persistent
PAUSED policy: the controller releases the BLE volume connection and stops
advertising while preserving saved bonds. Resetting the controller must retain
that explicit pause. **Connect** selects one saved identity and enables AUTO for
that identity; another nearby bonded host must not take the connection. Normal
startup and an unexpected connection loss resume only that saved selection.

**Pair new host** opens a separate, bounded 60-second enrollment window. It must
not overwrite or evict an existing bond to make space. Timeout, cancellation,
storage failure and a full store must produce an observed failure or paused
state. They must not silently enable unrestricted admission.

The current native candidate refuses descriptor-resolved and software
IRK-resolved saved identities before SMP. It does not invite an existing host
to rekey before rejecting its new records. A software resolution is a policy
classification, not proof of which physical host made the connection. The empty
baseline is the starting point for this investigation; later intended hosts are
added one at a time without clearing already verified hosts. For a new candidate,
OUR_SEC is held in a bounded RAM slot until PEER_SEC validates any supplied IRK
as unique among other saved identities. An RPA link must supply an IRK resolving
the original RPA; public/static-address enrollment without an IRK is supported.
Failed validation stores neither security record. A backend
failure after a validated OUR_SEC write can still leave a partial new candidate;
it is reported without automatic cleanup or replacement of another host. AUTO
behavior is unchanged. The earlier experimental software-hint deferral is no
longer active.
See the [native enrollment contract](../../tools/circuitpython-runtime/HOST-POLICY-API.md#intent-and-advertising-handshake)
for the callback ordering, scoped failure handling and error codes.

Host labels are owner-defined aliases. The native inventory exposes stable
opaque identities and security/CCCD availability flags, without exporting keys
or presenting a rotating private address as a saved identity. A valid peripheral
bond can have only OUR_SEC encryption material; PEER_SEC and an identity key are
separate observations. Existing but unusable records remain visible rather than
being deleted as a switching step. The explicit, confirmed single-host
**Forget** extension can remove an unusable saved identity only from clean
persisted PAUSED, with current generation/list checks. It clears that host's
alias and selection while preserving the local IRK and every other host's
records. Existing version-1 runtimes can keep their current policy actions
without implementing this optional extension.

The separate optional `clear_saved_hosts(bond_generation)` maintenance operation
removes all five peer-store families only under an explicit owner instruction.
It requires clean persisted PAUSED, no link or advertising, an idle operation
queue and a freshly checked bond generation. It clears selection and aliases,
verifies the canonical peer slots absent, then clears those RAM families and
their counters. Local IRK, unrelated NVS namespaces and private application files
are retained. It does not start pairing, retry, reset or restore old bonds
automatically. The obsolete CrowPanel **Erase BLE bonds** button has been removed;
this maintenance operation is separate from that disabled legacy command. See
[the all-peer maintenance contract](../../tools/circuitpython-runtime/HOST-POLICY-API.md#explicit-all-peer-maintenance-clear).

For the current iPhone investigation, the owner's clean-baseline instruction
supersedes keeping the original three bonds active. Preserve their full backups
for recovery, enroll and verify the iPhone first, then add each other intended
host individually. Record each result before adding the next host; finish with
selected-host switching and persistence through a controller power cycle.

BM83 audio pairing and streaming remain separate from the ESP32's BLE volume
connection. Selecting a volume host does not move the audio source. The existing
relative volume buttons and center-return adjustment slider retain their
semantics; this feature does not add absolute volume feedback or accepted mute
synchronization.

## Matching components

The candidate needs the project native runtime with
`_bleio.adapter.host_policy_version == 1`, matching CircuitPython application
files, and the matching CrowPanel application. The older eight-bond runtime
alone does not provide this API. A missing or unsupported native capability must
disable host-management actions honestly while preserving existing media and
legacy status compatibility. BLS2 remains exactly 21 bytes for the badge.

The new BHC1/BHP1 extension carries bounded commands, fragmented observations and
operation identities. A fresh, read-only LIST handshake admits a new CrowPanel
session before mutations. Its challenge refers to a complete STATUS packet
whose fragments have observed native transmit completion; enqueue acceptance
alone cannot issue a challenge. Retrying that handshake cannot change the native
policy. Repeated panel restarts must not permanently exhaust a client registry.

Completion needs fresh matching controller, client, request and native-operation
observations. Connected status additionally needs the selected identity,
encryption, a durable bond and the actual HID input subscription. A radio ACK,
an accepted command or an advancing display clock is insufficient.

CrowPanel displays a cached result only while it still belongs to the current
controller/session/native operation/request. A same-operation read-only LIST
refresh does not discard completion. A late matching terminal observation can
resolve a local timeout without reopening pairing or completing a newer request.
Current native ERROR takes precedence; leftover non-ERROR diagnostics are labeled
as a previous operation. Active connection/waiting labels use the actual native
target, even when another unacknowledged selection is pending.

Native advertising and report submissions must be ordered with policy and
connection changes. Old queued input must not reach a reused connection handle
or a different selected host. Native callbacks retain fixed C records, with no
Python allocation or public GAP calls under a spinlock. Any cooperative VM wait
needs a measured live timing check; a nominal timeout is not a UART latency
guarantee.

## Required gates

| Gate | Evidence required | Current state |
| --- | --- | --- |
| Phase 1 prerequisite | Qualified measured window, owner controls/screens, exact restoration and automatic CrowPanel recovery | Accepted for the recorded B-Intel scope |
| Host integration | Production Python/C++ and native bridge/core fault tests, wire golden vectors, lint and security checks | Implementation tree `0c7555e`: 2,256 passed, 6 skipped and 177 subtests passed on Linux, with MPY/parity, fatal lint, reliability and security checks. Physical evidence is separate. |
| CrowPanel compilation | Actual ESP32-S3 application build with recorded source, dependency and image hashes | The current application, including removal of the obsolete Erase button, compiled and passed full 4 MiB composite readback and a normal startup capture. Host-specific functional acceptance is recorded separately below. |
| Native compilation | Two clean Linux builds, exact source/patch/tool provenance, offline app/partition checks and byte comparison | Tree `0c7555e` produced 14 byte-identical outputs in two fresh Linux builds; offline image checks passed. The app is 1,976,816 bytes. Live acceptance remains separate. |
| Installation and rollback | Fresh paused state, verified safe/ROM mode, scoped write authority, private backups and protected-range readback | Matching dual 8 MiB backups, fresh full prewrite match, one native app-slot write and full 8 MiB composite readback passed. Before boot, protected 6 MiB, raw NVS, the three recovery-checkpoint peer records and local IRK were unchanged. CrowPanel full 4 MiB readback and both startups passed. |
| Persistent Disconnect | No connection or advertising through reset; retain the bonds enrolled for that test | Normal startup retained clean PAUSED with the fresh iPhone/B-Intel/Mac rows. The final four-host set still needs its physical power-cycle check. Historical November 5–6 Windows/badge pause evidence is retained below. |
| Selected AUTO | Correct host after explicit Select, unexpected loss, controller restart and target absence | Saved Pi reconnection and direct Pi → B-Intel → Mac selection passed for the fresh host set. Selection of the saved iPhone is waiting for that host; final saved-iPhone reconnection and physical power-cycle checks remain open. Historical Windows/Pi evidence is retained below. |
| Enrollment | New-host success, expiry, cancel, stale requests, capacity and storage failure | Fresh iPhone-first, B-Intel, Mac and Pi enrollment reached encrypted, bonded HID-ready AUTO. The owner verified iPhone/B-Intel controls; Mac and Pi OS measurements are recorded below. Historical expiry/cancel evidence remains scoped to its recorded builds. |
| Single-host Forget | Native fault harnesses, controller/CrowPanel and wire tests, then scoped physical removal and preservation checks | The strict per-host path remains supported. Historical A6 cleanup stopped on duplicate legacy CCCDs; the authorized all-peer operation established the clean baseline. A later ordinary Mac-only Forget removed that row and kept the fresh iPhone/B-Intel rows; its temporary hook was disarmed before fresh Mac enrollment. |
| Owner-authorized all-peer clean baseline | Recovery backups retained; own clear operation, advanced generation, clean persisted PAUSED and coherent empty roster; no automatic pairing | Observed `HOST_CLEAR_ALL` `EMPTY_PAUSED`, operation 1, bond generation 2 and roster `[]`. The temporary hook entry was disarmed and the original observer entry restored before fresh enrollment. No post-clear raw-NVS audit is claimed. |
| iPhone-first clean-baseline acceptance | Verify iPhone enrollment and volume up/down/mute with usable onscreen keyboard; add each other intended host individually; verify Connect/Disconnect, selected switching and power-cycle persistence | The owner verified iPhone and B-Intel controls. Mac/Pi controls and saved Pi → B-Intel → Mac selection passed within the recorded scopes below. Saved iPhone reconnection and physical power-cycle persistence remain open. The original three bonds remain recovery backups, not an active-bond prerequisite. |
| Stable Mac handle name | Verify the running native GAP/GATT Device Name and the Mac's saved and reconnected display name as `B's Groovy BT CTRL` | Passed: passive startup/connected GAP reads are correct, and Mac saved reconnection, Bluetooth off/on and a normal controller restart retain the corrected local name. Physical power-cycle acceptance remains separate. |
| Live regression | Audio, Nextion, CrowPanel, badge, artwork, controls and measured UART/radio service during a new stability window | Functional bench checks passed for the tested controls, Windows launch and media playback. A new qualified Phase 2 timing window remains open. |

## November 13: current runtime and four-host acceptance checkpoint

The current native application was built from Git tree
`0c7555eda3f029820908244e97f98429dd3ddaad`. Its Linux-native suite passed
**2,256 tests and 177 subtests, with six skips**; MPY/main parity, fatal flake8,
the reliability checker and the Host security Bandit command passed. Two clean
native builds produced 14 byte-identical outputs and passed the reproducibility
and offline image validators. The 1,976,816-byte application has SHA-256
`69e7ef8a2249ad3fb8a1b627c264e04aa107a983b0e5821baa8af99cbdeb0fdf`.
The installed Python owner includes the separately qualified connected-peer
cache correction; readiness and connected flags are derived from fresh native
status even when the saved-host generation does not change. These host/build
results remain separate from the physical results below.

| Host | Physical controls | Saved reconnection and selected switching |
| --- | --- | --- |
| iPhone | The owner confirmed fresh pairing, volume up/down and mute working; the bundled onscreen-keyboard acceptance prompt also passed. | The fresh row remains saved and resumable. The saved iPhone has been selected in the current four-host matrix; reconnection is pending the physical phone-on check. |
| B-Intel | The owner confirmed fresh pairing and controls earlier in this investigation. | Direct selection from Pi reached encrypted, bonded, HID-ready CONNECTED/AUTO with no current native error and all four saved rows retained. A later Windows endpoint read found no active audio render endpoint while the separate BM83 audio link was held by Pi; that observation does not negate controller HID readiness or the earlier owner control result. |
| Mac | Actual macOS output volume changed 10 to 6 and then 6 to 13; mute changed false to true and back to false after separate guarded gestures. | Saved reconnection occurred without another pairing request. Direct B-Intel-to-Mac selection also reached CONNECTED/AUTO with no native error. The required name `B's Groovy BT CTRL` remained visible after Mac Bluetooth off/on and a normal controller restart. |
| Raspberry Pi 5 | Actual OS ALSA volume changed 95% to 90% and back to 95%, and mute changed false to true to false. The kernel input device also reported a volume-up press and release. | Fresh enrollment reached encrypted, bonded, HID-ready CONNECTED/AUTO. Explicit Disconnect followed by Select reconnected the saved Pi without re-pairing; direct selection onward to B-Intel and Mac preserved the four-host roster. |

The Pi's successful fresh enrollment was captured continuously for 300 seconds:
one CONNECT, one admission and one CircuitPython publication, no refusals,
one connection/subscription generation, and a new fourth saved row. The capture helper
sent zero application bytes and requested no resets or reconnects. Later
authenticated status receipts for saved Pi, B-Intel and Mac selection all report
CONNECTED/AUTO, encrypted/bonded/HID-ready flags, `NONE/0`, the same four resumable
rows and unchanged bond generation. Those later receipts are controller status
snapshots, not a complete native event history.

Pi controls affected the ALSA target selected by its desktop media-key routing.
The separately queried Bluetooth audio sink stayed at 10%; HID delivery does not
promise that every OS audio endpoint changes. The volume peripheral remains a
consumer-only HID device, separate from the BM83 audio connection.

The Pi-side trace of the earlier failed attempt ended with HCI `0x3E` without SMP or ATT traffic. The
successful attempt used verified wired Ethernet with Pi Wi-Fi disabled; a
normal controller restart also occurred, so the comparison supports a radio
coexistence contribution without proving the cause. The attempted 5 GHz profile
change had actually remained on 2462 MHz and was rolled back; it is not evidence
of a successful 5 GHz trial. A later pre-SMP reconnect failure should be traced
before discarding a healthy saved bond.

The Mac name correction was made to its local cached Bluetooth name. Passive
reads of the running controller's GAP name already returned the required name,
including while connected. No firmware rename is inferred from the local edit.
The temporary Mac-only cleanup hook removed only that host, preserved the other
two fresh rows, and was disarmed before fresh Mac enrollment. No cleanup hook
remains active in these acceptance tests.

The final application entry was then restored to the canonical production
layout: the exact temporary observer `code.py` was backed up and retired,
leaving the unchanged 43,032-byte `main.py` as the startup entry. Boot, the Python
host-policy owner and native image were unchanged. Optional observer modules
remain unused. One automatic normal restart and a completed 180-second passive
startup capture verified no fatal errors and no temporary observation streams.
Fresh authenticated status showed all four resumable rows and the persisted
AUTO/iPhone selection. Production-entry selections to Mac, Pi and B-Intel then
reached encrypted, bonded, HID-ready CONNECTED/AUTO with no native error; a Mac
volume command changed the reported level from 10 to 6. Selection was returned
to the saved iPhone for the pending physical check.

Before that restart, the recorded network endpoint had become unreachable
while a separate passive USB capture showed the application still servicing
BM83 and metadata. The normal restart restored network access. It reinitializes
both Wi-Fi and the endpoint, so this recovery does not establish the failure's
cause or prove long-term network reliability. The restart was software-issued;
the startup reset-reason label alone is not evidence of physical power removal.

At this checkpoint saved-iPhone reconnection, complete four-host switching
sequence and physical controller power-cycle persistence remain open. The
normal controller restart and host Bluetooth off/on checks above do not replace
a power-cycle test. Final publication/CI and any wider stability claim are also
separate. Private flash backups, bonding records, profiles and raw captures stay
outside Git; pre-boot write-preservation proofs do not claim byte equality after
intentional host cleanup or fresh enrollment.

## November 13 CCCD correction and Mac recovery

The next qualified implementation is Git tree
`0c7555eda3f029820908244e97f98429dd3ddaad`. Its full native-Linux suite
reported **2,256 passed, 6 skipped and 177 subtests passed**. MPY/main parity,
fatal lint, reliability and the Host security workflow's Bandit check passed.
The six skips retain the documented Node.js and filesystem limitations. Two
fresh Linux native builds produced 14 byte-identical outputs and passed both
offline image validators. The 1,976,816-byte app SHA-256 is
`69e7ef8a2249ad3fb8a1b627c264e04aa107a983b0e5821baa8af99cbdeb0fdf`;
its padded 2 MiB slot SHA-256 is
`7587da36ffac3d19e3f3a68da3e4bfa2267290f6f47799e0a0eb88b6bfaca381`.

Pinned NimBLE routes a bonded peer's CCCD-zero write through its delete
callback. The old guard incorrectly treated that normal notification-disable
operation as a protected bond deletion. The correction retains one exact
canonical CCCD slot with disabled flags, commits and checks its complete
readback before updating RAM, and supports later authorized resubscription.
Tests cover the current encrypted/bonded peer, characteristic identity,
Disconnect/Select barriers, stale and wildcard requests, storage failures and
preservation of other records. A saved host remains resumable with its CCCD
disabled; HID readiness still requires an active input subscription. Secondary
store-guard callbacks also retain the first pending or published native fault;
this does not cover every core failure path or provide a full error history. A separate
test-fixture correction models the vendor's first-empty-NVS-slot allocation
after a non-tail Forget. These are source correctness fixes; neither alone
establishes the cause of an earlier Mac field error.

Installation used the automatic native-USB path. Two fresh complete 8 MiB
backups matched SHA-256
`618f65c2152a8eb6adbf2549866f18ae2241ed26c81132713984273b01c0a6d4`.
The sole app-slot write passed fresh full prewrite equality and complete 8 MiB
readback, SHA-256
`58cdaf25cd2ba942f1c203b5c44cb51097a0b3d8153c81dbb230c6aea3298d7d`.
Before normal startup, an independent comparison confirmed the protected 6 MiB,
raw NVS, all three current complete peer-security records and the local IRK
unchanged. This checkpoint contains the freshly enrolled iPhone and B-Intel plus
the Mac association, rather than the original suspect three-host set.

The captured normal boot was clean PAUSED with those three resumable rows and
no native error. Its passive in-app read returned the exact GAP/GATT Device Name
`B's Groovy BT CTRL`. A saved-Mac Select, operation 1, then admitted one link;
the Mac showed the handle as a Nearby Device named `CIRCUITPY6e8e`. One OS
Connect attempt produced a first SECURITY/5 fault, connection generation 1,
subscription generation 0 and local disconnect reason 534. No encrypted or
HID-ready sample was observed in that attempt. Operation 2 explicitly restored
clean PAUSED with the three rows retained. The result does not identify a unique
fault call site. Mac-only recovery, the connected/reconnected display name,
functional Mac controls, Pi enrollment and the final switching/power-cycle
matrix remain open at this checkpoint.

Claude Code contributed pinned-source review and scratch witnesses. Its
CCCD-disable, first-fault and test-model findings were independently checked
against the actual local files. Its separate client-feature delete hypothesis
was withdrawn after checking the already applied, source-pinned
`nimble-csfc-upsert.patch`. Review replies, host models, installed bytes and
physical results retain their separate evidence scopes.

## November 13 iPhone-first clean-baseline build

The earlier iPhone-first implementation snapshot was Git tree
`0e412220e887326268b1b25febe32581189a3099`. Its Linux-native suite with
`RUN_MPY_TESTS=1` reported **2,253 passed, 6 skipped, 177 subtests passed**.
Four skips require unavailable Node.js and two require a case-insensitive file
system. MPY compilation/main parity, fatal flake8 `E9,F63,F7,F82`, the reliability
checker and Bandit with the Host security workflow arguments passed. Two fresh
Linux native builds produced 14 byte-identical outputs and passed the committed
reproducibility and offline image validators. Their 1,976,608-byte app SHA-256 is
`872f600726a62775679bbefb1d04c94453dcd044d4200d02e633f02ddd93cc68`.

The latest CrowPanel app SHA-256 is
`b1621d83363143526f725dc8509fcf5afec0bcef3004cf5e7752847337c3d06a`.
Its full 4 MiB composite readback and normal startup capture passed. The
controller's two equal full 8 MiB backups have SHA-256
`0264a978e710973b4c1304c6270f4f04ffc920419bb7affb6586347e54c08223`.
The runtime write passed fresh prewrite equality and complete 8 MiB composite
readback, SHA-256
`c3d9d30785e8bd394b22cf3e6775ee80bcd88515051a29c654fbefd9414274ac`.
The independent preboot comparator verified the protected 6 MiB, raw NVS,
complete checkpoint peer-security records and local IRK unchanged. That proves
the runtime write's protected ranges before the authorized cleanup boot, not
preservation of those peer records after cleanup.

After the captured normal boot, the one-shot all-peer maintenance hook reported
`HOST_CLEAR_ALL` `EMPTY_PAUSED` for operation 1 at bond generation 2, with an
empty coherent roster. At 05:28:15 UTC the hook entry was disarmed and the
original 4,025-byte observer-only entry was restored and verified, SHA-256
`c5765d295305d2d3bf6cd42e62a48931bdb4bc0449222094015cb681a36fe39b`,
before the fresh-enrollment prompt. This is public operation/status/roster
evidence; it is not an independent post-clear raw-NVS readback. The old backups
remain recovery artifacts.

In the same uninterrupted capture, operation 2 reached encrypted, bonded,
HID-ready CONNECTED/AUTO at 161.536 seconds, with exactly one saved row
`12cd87fca6f5b827`, one connection/admission and no saved-IRK match or refusal.
The ready connection persisted about 302 seconds until a distinct PAUSED
request, operation 3. The owner confirmed that the iPhone was connected and
controlled volume appropriately, then answered the volume/mute/onscreen-keyboard
acceptance prompt with all checks working, specifically including mute and
volume up/down. The earlier pair-then-immediate-disconnect outcome did not recur
in this measured interval.

The owner next removed the stale Windows volume-peripheral entry, freshly
paired B-Intel and confirmed all volume and other controls working. That later
transition occurred after the bounded serial probes ended, so its physical
control result is owner evidence and is not inferred from the old capture.
Mac and Raspberry Pi enrollment, selected switching and controller power-cycle
persistence remain open. The fresh host set must stay intact while adding each
later verified host.

### Earlier November 13 candidate: historical evidence

The earlier pre-documentation implementation snapshot was Git tree
`0c3b5c5366e6de504362c3e9655df28ea0a96cd5`. Its Linux-native suite with
`RUN_MPY_TESTS=1` reported **2,251 passed, 6 skipped, 177 subtests passed**.
Four skips require unavailable Node.js and two require a case-insensitive file
system. MPY compilation/main parity, fatal flake8 `E9,F63,F7,F82`, the reliability
checker and Bandit with the Host security workflow arguments passed.

Two independent clean Linux native builds produced 14 byte-identical outputs
and passed the committed reproducibility and offline image validators. Their
1,975,680-byte application has SHA-256
`2188109d1d6156eca470ae1fd6a96bcb9d2d7aedbad0a3846a3d2e15f394cae7`.
That candidate included the experimental software-hint deferral later removed.
CrowPanel compilation and focused production C++ tests also passed. These are
host/build results. At the subsequent pre-boot full readbacks, controller
protected ranges and the original three complete peer-security records/local IRK
were unchanged; CrowPanel preserved every byte outside its new application image.
Both applications then completed captured normal startups. Fresh iPhone pairing, retained-host
reconnection, controls, power-cycle persistence and a new measured stability window
remain separate physical gates. Neither a model
witness nor cached panel text establishes the cause of an earlier field failure.

## November 5–6 physical results

- Fresh Windows enrollment reached HID ready and produced a measured volume
  down and up step on the BM83 output. The Windows companion requested
  Disconnect while Apple Music continued through the separate audio link. A
  confirmed cold restart preserved the paused state and the Windows pairing.
  Passive monitoring observed other nearby radio traffic and zero packets from
  the paused volume peripheral during the measured window.
- CrowPanel selected an existing Raspberry Pi 5 bond. Native HID readiness and
  the Pi's saved bond were verified across Disconnect and reconnection.
  Windows retained its separate BM83 audio connection during that test.
- The badge selected the saved Windows host, opened and cancelled the pairing
  window, and reconnected to Windows with the same four saved volume hosts.
  Windows confirmed the volume application opened and reported volume changes
  from the badge while Apple Music was playing through BM83.
- CrowPanel and badge each opened the Windows companion from their respective
  menu. The revised CrowPanel Rename keyboard saved a label containing letters
  and digits, and the controller reported the updated label with the same
  saved host identities. The badge battery gauge and status text were visually
  checked together on the physical display.

These results cover the exercised devices and operations. The companion's dry
run was exercised on Linux. The physical Raspberry Pi test used the existing
saved host and the Windows companion to request Disconnect.
Fresh enrollment on another platform, the wider radio and power-order matrix,
and a new measured UART and radio stability window remain open.

## Earlier bring-up observations

The first live Select exposed a CircuitPython builtin incompatibility: the
saved-peer lookup passed a default to `next()`, which this runtime does not
support. The corrected lookup walks the bounded peer list, and a request
failure now leaves the media loop running. A later trial reached the native
owner and was rejected before advertising. The fallback durably paused the
volume handle. Two matching flash backups showed that the active NimBLE bond
records remained byte-for-byte identical; the separate host-policy namespace
recorded the paused state.

The corrected native runtime verifies typed bond fields and ignores padding
and unused key bytes. It retains fail-closed handling for missing records and
changed fields. Its NVS status can identify a record family and mismatch
category without exposing keys or addresses. The corrected runtime reported
NVS `-20531`: it found a matching peer and CCCD characteristic but the RAM and
saved values differed. The controller was paused, had no connection, and did
not advertise. The result does not test whether Windows can reuse its bond.

The next runtime entered ENROLL and advertised on the unit. B-Intel saw the
device and attempted to pair while its old bond was still saved on the unit.
The connection was not admitted. Advertising stopped after approximately
15 seconds, before the countdown expired, and stayed off during later
requests. Windows still reported the volume device unpaired, with the BM83
audio connected. The pinned NimBLE stack can signal early peripheral link
loss as a CONNECT failure. Publish a CircuitPython connection only after
policy admission and successful callback registration, and release the
matching native and CircuitPython state on that failure event. The capture
did not include raw HCI events, so it cannot identify the exact termination
reason.

The earlier second-host enrollment check required Windows to remain saved and
to reconnect without a pairing prompt. That describes the historical bring-up
scope, not a requirement to retain the suspect original three bonds during the
current iPhone investigation. The current acceptance sequence starts from the
verified empty baseline, verifies the iPhone first and adds each other intended
host individually before switching and power-cycle checks.

Single-host Forget remains a separate targeted contract: start from Disconnect,
confirm the named host, observe its removal at a new generation, remove the unit
on that host and re-enroll it while preserving other hosts and local IRK. The
November 5–6 runs did not exercise that extension. A failed storage guard stops
the operation for diagnosis; a later explicit recovery action must match the
actual failure. The optional all-peer maintenance clear has its own owner scope
and does not promise to preserve the peer records it intentionally removes.

Windows may offer only **Remove device** for the volume handle. Firmware cannot
add an operating-system Disconnect button. A disconnect reason alone also does
not reliably distinguish a user click from sleep or another link loss. The
initial deterministic stay-disconnected path is the explicit CrowPanel action.

Raw flash backups contain bonding keys and device data. Keep them, private
profiles, captures and approval records outside Git. Follow the separate
[native runtime write guards](RUNTIME-FLASH-GUARDS.md); never change protected
branch policy, security settings or approval rules to make a gate pass.

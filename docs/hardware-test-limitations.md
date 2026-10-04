# Hardware Test Limitations (Host Simulation)

These automated tests intentionally focus on host-simulatable behavior and avoid claiming full end-to-end hardware validation.

## Covered in host tests

- String sanitization and formatting behavior in `utils.common`.
- Parser/tokenization behavior for Nextion token streams, including noisy burst inputs.
- BM83 frame assembly/parsing behavior, including fragmentation and checksum recovery.
- Build-output checks that `.mpy` artifacts are generated when `RUN_MPY_TESTS=1` and `mpy-cross` is present.

## Not fully testable in host simulation

- Real UART timing jitter and electrical-layer framing faults.
- BM83 radio behavior (pairing, reconnect timing, RF coexistence, codec negotiation).
- Nextion display firmware differences across panel versions.
- CircuitPython runtime memory-pressure behavior on the actual MCU.
- Latency and interaction effects across ISR/load patterns on the ESP32-S3 target.

## Practical guidance

Treat host tests as regression protection for deterministic logic, not as proof of full device behavior. Run a hardware validation checklist before releases that touch UART timing, power sequencing, or UI event throughput.

## Assisted USB bench capture

`tools/hardware_bench.py` captures the production CircuitPython console and
records timestamped evidence without transmitting serial data or changing the
device's files. It selects only USB VID:PID `303A:7003`; absent or ambiguous
matches stop the capture rather than selecting another board. Use the USB serial
number reported by `--list`, because COM numbers can change:

```powershell
python tools/hardware_bench.py --list
python tools/hardware_bench.py --serial <USB-serial-number> --duration 180 --markers --output-prefix build/hardware/power-cycle
```

The tool uses 115200 baud, asserts DTR to connect the native CircuitPython console,
and leaves RTS off. It sends no reset sequence or control characters. Close other
serial terminals before capturing. Enter action descriptions on the host terminal
to add markers; these lines are never forwarded to the board. New `.log` and
`.json` outputs are created, and existing output files are refused.

Every capture summary says `hardware_verdict: NOT_ASSESSED`. Attach participant
observations before judging audio, LEDs, displayed metadata, or volume behavior.
Heartbeats and error messages are evidence; a quiet console does not establish a
crash. Record the runtime and deployed source separately, including whether a
`code.py` entrypoint overrides `main.py` and whether project `.py` and `.mpy` files
coexist. Preserve that deployed state before installing diagnostics.

A useful supervised sequence is:

1. Capture normal playback, Next, pause/resume, and one short volume tap each way.
   Verify audible output, metadata, the paused clock, and single-step volume.
2. Perform one production Power OFF/ON cycle, leaving at least ten seconds off.
   Corroborate OFF with chip reports and physical LEDs/audio, and verify affirmative
   ON evidence plus functional playback and BLE volume afterward.
3. Disconnect and reconnect source audio Bluetooth once, allowing it to settle.
   Verify first playback, metadata refresh, and volume control after reconnect.
4. With an available AUX source, check AUX/A2DP routing and indicator transitions.
   Watch for unexpected gain changes or beeps while confirming transport gating.

If power cycling restores controls and metadata but leaves audio silent, record
audible recovery as a failure. Keep any later recovery action as a separate
result. The [muted-path wedge note](muted-path-wedge.md) describes a similar
historical symptom and a source-app Pause, wait at least two seconds, Play
workaround. For a new incident, also establish the source report (`0x82` for
A2DP), Windows output selection, mute, and volume before assigning a cause.
Working AVRCP or a profile-established event alone does not prove audio routing.

For raw BM83 TX/event evidence, `tools/bench_debug_entrypoint.py` is an optional
temporary `code.py` that runs the unchanged production `main.main()` with DEBUG
logging. It adds device millisecond tick timestamps to debug messages. Back up any
existing `code.py` and `main.py`, explicitly reload to start the wrapper, then
restore the original entrypoint state and reload again when finished. The wrapper
disables autoreload during capture. Logging changes allocation and execution timing,
so use this mode for protocol/state evidence rather than a production performance
verdict. Tick values wrap at `2**29` ms; use `utils.ticks.ticks_diff()` for intervals.

`tools/bench_a2dp_reconnect_entrypoint.py` is a separate, experimental temporary
`code.py` for one unit-initiated A2DP recovery trial. Pause source playback before
installing or restoring entrypoints. It uses the current production driver and
arms only after an accepted user Power OFF followed by Power ON; startup alone
does not arm recovery. A fresh `Read_Link_Status` reply must show exactly one
A2DP database before it sends `Disconnect` (`0x18`, mask `0x04`). After confirmed
teardown and a ten-second gap, it sends at most one `Profiles_Link_Back`
(`0x17`, type `0x02`), unless A2DP has already returned during the gap. The
disconnect affects all A2DP connections, and link-back targets the last paired
A2DP source, so establish the intended source before testing.

Use these disconnect diagnostics only with a known single A2DP source. The status
reply exposes DB0 and DB1; observing one populated slot is not a universal
enumeration of all peers in every multi-speaker firmware configuration.

The trial has bounded deadlines and cancels on explicit OFF, AUX selection, or
an unexpected power transition. It holds ordinary AVRCP and probe traffic during
the deliberate disconnect. It never initiates pairing, bond erase, AUX gain,
PLAY, or a power cycle. Command acceptance and fresh profile events are recorded
separately from the participant's audible result. Even a `Read_Link_Status`
streaming flag does not prove sound output. Both wrappers use CircuitPython's
`supervisor.runtime.autoreload = False`; restore the prior entrypoint state and
deliberately reload after testing.

`tools/bench_clean_shutdown_entrypoint.py` tests a separate prevention hypothesis.
One qualifying user OFF initiates a fresh single-source A2DP/AVRCP snapshot,
explicit Pause, a three-second settle, one A2DP disconnect with accepted ACK and
actual `0x08` evidence, and a one-second settle before the unchanged OFF driver.
Preparation is nonblocking and limited to ten seconds; errors, ambiguous state,
AUX, or new profile/ACL establishment fall back to the original OFF sequence.
Repeated OFF bypasses preparation immediately. The wrapper never generates PLAY,
link-back, pairing, gain changes, or an automatic ON. Allow up to twelve seconds
from the OFF press to physical shutdown, then time the off interval from the LEDs
going off. Use a confirmed audible baseline and report the result after normal
user ON separately; host tests cannot establish that this prevents an audio fault.

`tools/bench_version_probe_entrypoint.py` is a temporary read-only firmware
fingerprint wrapper. With the source paused and the original files backed up,
it attempts `Read_BTM_Version` (`0x08`) types `00`, `01`, `03`, `04`, and `05`
once after fresh validated UART events have settled. Leave the BM83 physically
powered; UART responsiveness does not prove ON state or an active audio session.
An ESP32-only VM reload can lose the controller's cached ON state while an
already-on module continues answering, so this read-only probe does not require
or alter that cache. It records command ACKs separately from typed event
`0x18` replies and preserves the raw version bytes. Optional types depend on the
installed firmware family; rejection, missing replies, and invalid lengths are
INCONCLUSIVE. A missing, malformed, or conflicting untyped command ACK stops the
remaining queries to avoid associating a late ACK with the next type. The probe
generates no reset, reconnect, power, pairing, or EEPROM-write commands and never
rearms on Power. Normal production RX, event acknowledgements, and controls still
run. Restore the original entrypoint and deliberately reload before resuming
playback. Module markings and basic version bytes alone may not identify a full
firmware build; retain detailed application/DSP bytes when supported.

In the supervised B-Intel trial on 2026-10-03 (CircuitPython 10.3.1, temporary
DEBUG entrypoint), the unit's disconnect and link-back commands were accepted,
actual teardown was observed, and A2DP/AVRCP returned. The participant still
reported no sound and an Apple Music clock stuck at zero. AVRCP position replies
continued advancing, so even fresh source position data did not establish working
audio. That experiment failed audible recovery; do not enable this sequence as a
production fix on the strength of protocol completion alone.

A separate prevention trial restored audible playback through a Windows
disconnect/reconnect, then paused through the CrowPanel before the normal OFF/ON
sequence. The captured pause-to-OFF interval was 19.737 seconds, and the module
was fully off for 16.716 seconds before ON. The participant again reported a
stalled Apple Music clock and no sound after ON. No further diagnostic disconnect
or link-back commands ran during that cycle. Pause-before-OFF alone did not
prevent the fault in this setup.

The clean-disconnect-before-OFF trial also failed audible recovery. Its fresh
snapshot reported `04 07 00 01 00 01 00`; explicit Pause produced an actual
paused-status notification, Disconnect was accepted and produced `0x08`, and the
preparation completed without fallback. Normal OFF followed, with 38.472 seconds
fully off before the user ON. A2DP/AVRCP links returned, but the participant
reported Apple Music taking about ten seconds to show Play, its visible clock
remaining stuck, and no sound. Metadata and the Nextion clock still advanced.
The temporary entrypoint was then removed and the original production main was
reloaded with source playback paused. These results establish failed audible
recovery in this setup, not a verified unit-side recovery mechanism or ownership
of the fault by either stack.

After the failed clean-shutdown trial, all fourteen original device files matched
the pre-test snapshot and the original absence of `code.py` was restored. The
participant then used Windows BM83 Disconnect, waited at least ten seconds, and
connected again. Audible music, both clocks, metadata, and a CrowPanel volume tap
passed; the BLE control connection also needed reconnecting. Keep audio-profile
recovery and BLE control recovery as separate observations.

Hardware reset is a distinct operation. Microchip's
[BM83 module datasheet, DS70005402H](https://ww1.microchip.com/downloads/aemDocuments/documents/WSG/ProductDocuments/DataSheets/BM83-Bluetooth-Stereo-Audio-Module-Data-Sheet-DS70005402.pdf)
defines active-low `RST_N` at module pad 43; this is not a carrier-board
header number. Verify the actual board's reset connection before GPIO wiring.
The participant identified the attached board as a BurgessWorld breakout, with
separate RESET and PWR/MFB buttons and `RST_N` at carrier pin 8. No ESP32 GPIO is
wired to reset. The reported `v2.0` and `BM83M1` markings do not independently
establish the installed BM83 firmware version.

The subsequent manual RESET trial used unchanged production firmware and passive
capture. The initial silent result, with both clocks stopped and retained Nextion
metadata, was incomplete because the participant reported that RESET left the
board off. A later panel press completed the controller's OFF sequence; a further
press requested ON. Fresh chip `0x02`, A2DP `0x06`, and AVRCP `0x0B` reports then
established startup, with A2DP and AVRCP observed 4.700 and 6.543 seconds after the
ON token. The participant still reported a long Play delay and no sound after
twenty seconds. Record reset followed by confirmed startup as failed audible
recovery in this setup. The compact log does not independently locate the
physical reset transition, and the controller's OFF log is distinct from a
chip-reported OFF state.

These four unit-side trials do not establish a successful automatic recovery
mechanism. Require audible playback and correct source/display clocks before
enabling recovery in production; successful commands, profile links, or an
apparently advancing timeline cannot substitute for that acceptance check.

During the silent post-reset state, a read-only Windows CoreAudio inventory
reported Speakers (BM83) as ACTIVE and the default render endpoint for Console,
Multimedia, and Communications. The inventory opened no audio stream and changed
no device settings. The participant then restored audible playback through the
Windows disconnect/reconnect sequence and passed the clock, metadata, and remote
volume checks. A second inventory showed the same BM83 endpoint identity, ACTIVE
state, and default roles. Endpoint presence, ACTIVE state, and default selection
alone therefore cannot distinguish this captured failure from working playback.
The original production files remained unchanged throughout this physical-reset
trial and its restoration.

A separate source comparison established audible playback on an already-paired
iPhone 17 Pro Max running iOS 26.6.2 and Apple Music. The participant confirmed
matching phone/Nextion clocks and metadata, with BLE volume control working.
B-Intel's BM83 audio connection was disconnected for this comparison; a read-only
Windows snapshot before the phone power cycle reported its BM83 render endpoint
as UNPLUGGED. The phone returned metadata attributes `[1, 2, 3, 4, 5, 6, 7]`,
including genre (`6`), whereas the earlier Windows replies contained `[1, 2, 4]`.
The participant's populated Nextion genre field for the phone and blank field for
Windows are consistent with this difference in returned source metadata. Compact
production logs do not independently identify the audio peer or BLE central.

One subsequent normal OFF/ON cycle passed on the iPhone with unchanged production
files and no source Bluetooth reconnect. Chip OFF was followed by the user's ON
token 16.941 seconds later; fresh A2DP and AVRCP reports arrived 4.485 and 6.118
seconds after ON. A captured CrowPanel Play input was followed by fresh audio-source
`0x82` reporting after 0.203 seconds. The participant confirmed audible playback,
matching clocks and metadata, and working remote volume, and left playback running.
Play was received 19.790 seconds after ON, shorter than the requested thirty-second
wait. Windows still reported its BM83 endpoint as UNPLUGGED afterward, and all
fourteen original device files matched their snapshot with `code.py` absent.
This single phone result narrows the observed failure to the B-Intel/BM83 source
interaction under the tested conditions; it does not identify the responsible
stack or establish a successful unit-side Windows recovery mechanism.

The subsequent read-only fingerprint returned UART protocol `2.06`, basic
application `1.03`, detailed application `1.03.0008`, and DSP `1.04.0412` in
accepted, correctly tagged replies. Five version queries were sent once each.
The project-target query was accepted but returned event parameters `47 46 50`
(ASCII `GFP`) without the documented leading type `05`; preserve those raw bytes
and record the typed project result as INCONCLUSIVE. The first attempt had sent
no version queries because its stricter ON-state readiness gate expired after
an ESP32-only VM reload; fresh validated UART-event readiness allowed the second
attempt without a power cycle or production-state mutation.

The checked MSPK2 release notes list application `1.03.0008` with DSP `1.04.0006`
under release 1.3, and application `1.03.0506_SPP` with DSP `1.04.0412` under
release 1.3.5. The captured pair is absent from those listed bundles. This raises
a package-consistency question; SDK-customized applications are possible, so it
does not prove an invalid installation, incompatibility, or the Windows fault's
cause. Establish the appropriate complete firmware package and preserve device
configuration before considering an update. The fingerprint probe changed no
BM83 configuration, and its temporary entrypoint was removed afterward; all
fourteen original ESP32 files again matched the snapshot.
The participant then resumed iPhone playback and passed audible output, both
clocks, matching metadata, and a CrowPanel volume tap with the original firmware.
The final passive capture was closed after that report; leave the working unit
on its restored production entrypoint.

The older `tools/power_cycle_harness.py` is a narrow diagnostic, not an acceptance
verdict: its checks do not independently enforce the current power-evidence
whitelist or establish physical shutdown, and its loop omits the production BLE,
display, and AVRCP workload. Do not use its PASS alone to approve a release.
`tools/power_stress_harness.py` documents hard freezes during rapid cycles; it is
excluded from the routine sequence above.

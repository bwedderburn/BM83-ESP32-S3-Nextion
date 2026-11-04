# Silent playback after reconnect or power cycling

This note separates the earlier muted-path observations from the later
B-Intel/Windows capture. Similar visible symptoms do not establish a single
root cause or a universal recovery procedure. The
[hardware test record](../validation/hardware-test-limitations.md) retains the
later source comparisons, diagnostic sequences and participant results.

## Recognize the failure

A source can show Play while no audio is audible. BM83 can still report A2DP
source `0x82`, accept AVRCP commands and supply metadata or advancing position
replies. The Nextion clock can therefore move while the Windows Apple Music
clock is stalled. Neither metadata nor a Bluetooth endpoint reported ACTIVE
proves that an audio stream is rendering.

In one earlier Windows observation, the Sound settings Test control disappeared.
That is a useful symptom to record, not independent proof of which chip or host
component owns the fault. The later failed and restored states both exposed the
same ACTIVE/default BM83 endpoint identity.

## Recovery observed on B-Intel

The supervised October 3 Windows trial repeatedly recovered through the source's
BM83 Bluetooth audio connection: pause Apple Music, disconnect BM83 audio, wait
at least ten seconds, reconnect, then try Play once and check audible output,
source/display clocks and metadata. The separate BLE control connection sometimes
also needed reconnecting; keep those results distinct.

Pause/wait/Play, pausing before OFF, a unit-initiated A2DP disconnect/link-back,
a clean disconnect before OFF and a board reset followed by confirmed startup
did not establish audible recovery in that tested Windows configuration. Do not
enable automatic unit-side recovery merely because commands were accepted or
profiles re-established. A recovery on a different host or occasion does not
make this sequence guaranteed.

A separate iPhone baseline and one normal OFF/ON cycle passed with audible
playback, clocks, metadata and relative volume. That comparison narrows the
observed conditions but does not identify the responsible stack or qualify all
phone and Windows sessions.

## Earlier observations

The August 2, August 26 and August 29 notes described silence following abnormal
stream teardown, including reconnects, source reboot and application reloads.
Source-app Pause, a delay and Play or a track change sometimes restored sound
in those sessions. Firmware-initiated AVRCP Pause/Play did not restore the tested
audio path; that attempt remains disabled through `STREAM_KICK_ENABLED = False`.
The [August review](../reviews/code-review-2026-08-02.md) preserves those findings.

The earlier description of a chip/host audio-path wedge was a working
interpretation of the observations, not a traced root-cause determination. Later
Windows failures show that the earlier source-app workaround is insufficient in
some sessions.

## Maintenance and investigation

Pause the source before a separately authorized controller file update, preserve
the installed entrypoints/configuration and follow the
[deployment recovery safeguards](../guides/deployment.md#optional-universe-badge-receiver).
An evaluated native runtime also hard-faulted during VM teardown; a soft reload
is not a generally safe recovery procedure for that installation. Repository
cleanup does not authorize hardware operations.

For another incident, record source/app and BM83 firmware identities, output
selection, mute/volume, exact transition sequence, UART status, source-clock
movement and audible results separately. Retain failed attempts alongside later
recovery. The [vendor archive](../reference/vendor/bm83/README.md) contains the
retained BM83 reference material; module markings alone do not establish the
installed firmware build.

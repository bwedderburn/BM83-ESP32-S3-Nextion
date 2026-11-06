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

Host labels are owner-defined aliases. The native inventory exposes stable
opaque identities and security/CCCD availability flags, without exporting keys
or presenting a rotating private address as a saved identity. A valid peripheral
bond can have only OUR_SEC encryption material; PEER_SEC and an identity key are
separate observations. Existing but unusable records remain visible rather than
being deleted as a switching step.

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
| Host integration | Production Python/C++ and native bridge/core fault tests, wire golden vectors, lint and security checks | Linux host coverage includes the host policy and both remote controls. Physical evidence is recorded separately below. |
| CrowPanel compilation | Actual ESP32-S3 application build with recorded source, dependency and image hashes | Clean app builds installed with complete 4 MiB readback. The Volume hosts menu, Windows launch and revised Rename keyboard were exercised on the panel. |
| Native compilation | Two clean Linux builds, exact source/patch/tool provenance, offline app/partition checks and byte comparison | Both the first and corrected candidates have two matching clean builds; live acceptance is separate |
| Installation and rollback | Fresh paused state, verified safe/ROM mode, exact scoped native approval, private backups and protected-range readback | Both native app-slot writes passed full 8 MiB verification after separate exact approvals; every byte outside the app slot matched its prewrite backup |
| Persistent Disconnect | Saved bonds unchanged and no connection or advertising through reset, with host Bluetooth on | Windows companion Disconnect stayed paused through a physical power cycle. The Windows bond and enabled radio were verified. The badge independently confirmed a persisted pause and stopped advertising. |
| Selected AUTO | Correct host after explicit Select, unexpected loss, controller restart and target absence | Windows and Raspberry Pi were selected and reconnected using saved bonds. Unexpected-loss, target-absence and broader competitor cases remain open. |
| Enrollment | New-host success, expiry, cancel, stale requests, capacity and storage failure with bond preservation | Fresh Windows enrollment succeeded. Live timeout was observed during bring-up. The later badge test verified pairing-window entry and cancellation with the same four saved hosts. Enrollment of a second unpaired host remains open. |
| Live regression | Audio, Nextion, CrowPanel, badge, artwork, controls and measured UART/radio service during a new stability window | Functional bench checks passed for the tested controls, Windows launch and media playback. A new qualified Phase 2 timing window remains open. |

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

For the remaining enrollment gate, pair a second unpaired host and verify that
Windows remains saved. Return to Windows via **Connect** and record whether a
pairing prompt appears. Record each exercised direction and return leg.

Windows may offer only **Remove device** for the volume handle. Firmware cannot
add an operating-system Disconnect button. A disconnect reason alone also does
not reliably distinguish a user click from sleep or another link loss. The
initial deterministic stay-disconnected path is the explicit CrowPanel action.

Raw flash backups contain bonding keys and device data. Keep them, private
profiles, captures and approval records outside Git. Follow the separate
[native runtime write guards](RUNTIME-FLASH-GUARDS.md); never change protected
branch policy, security settings or approval rules to make a gate pass.

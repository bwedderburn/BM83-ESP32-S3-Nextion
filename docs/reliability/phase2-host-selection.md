# BLE volume host selection: implementation and acceptance

The November 4 [B-Intel Phase 1 run](phase1-bintel-2026-11-04.md) is accepted
within its recorded scope. Disconnect + Select host is a separate development
candidate. Its host tests and CrowPanel compilation do not establish successful
BLE switching, native persistence, privacy resolution or live UART timing.
Do not describe the candidate as physically accepted until the gates below have
actual results.

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
| Host integration | Production Python/C++ and native bridge/core fault tests, wire golden vectors, lint and security checks | 1,637 Linux host tests passed with five skipped; physical evidence remains separate |
| CrowPanel compilation | Actual ESP32-S3 application build with recorded source, dependency and image hashes | Initial matching candidate compiled; not installed |
| Native compilation | Two clean Linux builds, exact source/patch/tool provenance, offline app/partition checks and byte comparison | In progress; no installable image accepted |
| Installation and rollback | Fresh paused state, verified safe/ROM mode, exact scoped native approval, private backups and protected-range readback | Pending; accepted firmware remains installed |
| Persistent Disconnect | Saved bonds unchanged; no connection or advertising through reset, with other hosts' Bluetooth on | Pending physical test |
| Selected AUTO | Correct host after explicit Select, unexpected loss, controller restart and target absence; competitors cannot take ownership | Pending physical test |
| Enrollment | New-host success, expiry, cancel, stale requests, capacity and storage failure without old-bond deletion | Pending; destructive capacity cases require a spare fixture or an explicit untested boundary |
| Live regression | Audio, Nextion, CrowPanel, badge, artwork, controls and measured UART/radio service during a new stability window | Pending; Phase 1 timing does not certify this changed native runtime |

Test Windows, macOS, iPhone and Raspberry Pi/Linux only against their actual saved
entries and available stacks. Record every exercised direction and return leg.
A host-side forgotten entry can leave a stale unit-side half-bond; that is a
separate repair case, not permission for a global bond wipe. Do not fill or erase
the owner's live store to claim capacity acceptance.

Windows may offer only **Remove device** for the volume handle. Firmware cannot
add an operating-system Disconnect button. A disconnect reason alone also does
not reliably distinguish a user click from sleep or another link loss. The
initial deterministic stay-disconnected path is the explicit CrowPanel action.

Raw flash backups contain bonding keys and device data. Keep them, private
profiles, captures and approval records outside Git. Follow the separate
[native runtime write guards](RUNTIME-FLASH-GUARDS.md); never change protected
branch policy, security settings or approval rules to make a gate pass.

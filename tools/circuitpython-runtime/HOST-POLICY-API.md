# ESP32 native host-policy API, version 1

This is the project-specific capability added by `host-policy.patch` to the
pinned ESP32 runtime. It is not a portable CircuitPython or Adafruit BLE API.
The application HID service, Report ID 3, report map, advertising payload, local
identity and GATT layout are unchanged. Native compilation, host fault tests,
installation and physical host-switch acceptance remain separate evidence.

`adapter.host_policy_version` stays `1`. A capable client must also require
`arm_host_input`. Forget is an optional version-1 capability, detected separately
by checking that `adapter.forget_host` is callable after claiming the existing
policy API. Installed version-1 runtimes without it continue to support the
existing policy actions and report Forget as unsupported.

## Intent and advertising handshake

`adapter.set_host_policy(mode, target_id=None, timeout_s=60)` returns a nonzero
32-bit operation ID for a bounded queued request. It does not mean connected,
paired, persisted or HID ready. The modes are:

* `PAUSED`: persist a pause, stop advertising, cancel queued input and terminate
  the old connection once. A later explicit operation may retry a failed
  terminate; background ticks do not retry indefinitely.
* `AUTO`: require one usable saved identity. An omitted target resumes only the
  previously selected identity; it never selects an arbitrary bond. An
  unexpected disconnect retains this selection. A full disconnect reason such
  as `0x213` is not treated as proof that a person clicked an OS control.
* `ENROLL`: an explicit 5–120 second window, with one candidate and preflight
  headroom in the security, CCCD, CSFC and RPA-mapping stores. Persisted intent
  remains PAUSED until the new resume key and actual input CCCD are read back
  from NVS and AUTO(new identity) commits. Timeout, cancellation or an error
  cannot silently evict or replace an old pairing. Partial new records remain
  visible for a separately scoped repair; there is no automatic destructive
  cleanup.

Create the existing Adafruit HID services and payload while native policy is
paused. After `state` is `WAITING` or `ENROLLING`, `filter_ready` is true and
`applied_mode` matches the requested policy, call the normal application
`start_advertising()`. Do not wait for CONNECTED before advertising. Native
code never invents a replacement payload.

Every application and supervisor advertising entry goes through a bounded
native request with copied payload bytes. The actual GAP start runs on the same
host task as policy transitions and rechecks admission there. Stop/filter and
start run in separate event contexts. ENROLL also clamps the controller's
advertising timeout to its remaining window. Native denial has no unrestricted
advertising fallback.

The advertising wrapper's cooperative VM wait is nominally limited to **200 ms**;
the native service cadence is **100 ms**. This is not a hard deadline over
underlying GAP/HCI, flash, OS scheduling or background callbacks. A timed-out
request is cancelled using native-owned buffers and cannot retain a VM pointer.
The changed runtime needs fresh UART/timing measurements before hardware
acceptance. No per-report VM wait is added for HID input.

## Read-only snapshots

`adapter.bonded_peers` is a tuple containing at most eight dictionaries:

| Field | Meaning |
| --- | --- |
| `id` | 16 lowercase hexadecimal characters, stable opaque label derived from normalized identity, never an OTA RPA or recycled slot |
| `alias` | Native-persisted printable UTF-8, at most 24 bytes; no C0/DEL/C1 controls |
| `generation` | Snapshot `bond_generation`; clients must check coherence with `host_status` |
| `our_sec` | Local peripheral-resume LTK available |
| `peer_sec` | Peer LTK or peer IRK available; independent diagnostic flag |
| `cccd` | Persisted notifying CCCD present, restricted to the observed input handle once known |
| `resumable` | Required OUR_SEC LTK is present and the corresponding persistent records read back correctly |
| `connected` | Observed connection identity matches this saved identity |

The pinned peripheral LTK restore path reads OUR_SEC. PEER_SEC/IRK is optional
for a stable-identity peripheral resume. A rotating RPA needs a matching stored
IRK and actual controller resolution; a stable-address-only selection does not
claim that privacy case passed. Native admission always compares full normalized
identity; the opaque label is not an authentication credential. Hash collisions,
invalid identities, inconsistent inventories and over-capacity snapshots fail
closed. No LTK, IRK, CSRK, EDIV or RAND is exported.

`adapter.host_status` contains:

* `version`, `requested_mode`, `applied_mode`, `state`, `target_id`, `connected_id`;
* `operation_id`, `policy_generation`, `connection_generation`,
  `subscription_generation`, `bond_generation`;
* `filter_ready`, actual `advertising`, `connected`, `encrypted`, `bonded`,
  `hid_ready`, `persisted`, `enroll_remaining_s`;
* `error_domain` (`NONE`, `POLICY`, `NVS`, `NIMBLE`, `SECURITY`) and full integer
  `error_code`;
* full integer `last_disconnect_reason`, `last_disconnect_generation` and
  `last_disconnect_local` (local termination intent).

States are `PAUSED`, `SWITCHING`, `WAITING`, `ENROLLING`, `CONNECTED`, `ERROR`.
Routine host-task activity does not synthesize a SWITCHING or readiness edge.
CONNECTED/HID ready requires the actual encrypted, bonded connection and its
input subscription, plus persistent resume/CCCD readback. Completion requires
the expected operation ID and observed state; an ESP-NOW/BMW1 ACK is insufficient.
An advertiser-stop failure remains ERROR and actual advertising is reported
honestly. Bluetooth need not be turned off to release an ordinary working link.

`adapter.set_host_alias(id, alias)` returns a queued operation ID. Claim saved
only after that operation is observed, persistence succeeded and a coherent peer
snapshot contains the exact alias. An actual alias change updates the snapshot
generation; identical aliases may retain it.

## Forget one saved host

`adapter.forget_host(host_id, bond_generation)` returns a nonzero u32 operation
ID for one queued request. Both arguments identify a currently listed saved
identity at the exact observed bond generation. The generation must be a Python
integer with that exact value. Admission requires clean PAUSED: requested and
applied modes and state are PAUSED, PAUSED is persisted, there is no link or
advertising, no error and nothing queued, busy or faulted. Invalid entry raises
`ValueError` before queuing or terminating a link. A later explicit PAUSED
request may replace a pending Forget.

The host task refreshes the inventory, rechecks the generation and identity,
and preflights all five peer-store families. It requires equal RAM/NVS counts,
one-to-one matching records and unambiguous target keys. It stops advertising
and clears the admission filter, then commits and reads back PAUSED with only
the target alias and selection cleared before deleting records. For each row,
it erases and commits that exact NVS key, verifies its absence, then removes
the RAM row through the vendor API and rechecks the family. The order is
PEER_ADDR, CSFC, OUR_SEC, CCCD, PEER_SEC. Other saved hosts and the local IRK
keep their bytes. There is no automatic retry or restoration after an error.

Completion requires the caller's observed operation, clean persisted PAUSED,
a coherent peer list at a new bond generation without the target, and a
different status target. An ACK, missing list or another operation cannot
confirm Forget. After failure, explicitly Disconnect and Forget again.
Power-cycle first if the store fault persists. Hardware actions require their
own scoped approval.

The CrowPanel asks for confirmation naming the saved host. FORGET, like every
BHC1 command, travels over unencrypted, CRC-only, MAC-filtered ESP-NOW. A
spoofed panel could forget a paused host. The owner must accept that transport
risk before installation. This source work has host tests only; native build,
installation and physical acceptance are pending.

## Generation-bound input

Immediately before each ConsumerControl gesture, validate a fresh status and
call:

```python
armed = adapter.arm_host_input(
    status["operation_id"], status["policy_generation"],
    status["connection_generation"], status["subscription_generation"],
)
```

Only literal `True` permits that gesture. False means stale or unready; abandon
the old gesture and clear local held state. Do not pause a healthy new host or
re-arm an old gesture from a new snapshot. The native arm compares exact Python
integer epochs without truncation and captures the selected identity and actual
input handle. It is an origin lease, not a delivery ACK.

The native producer uses this lease rather than labelling a previously prepared
VM report with whatever connection is current on entry. Reports carry operation,
policy, connection, subscription, identity and handle metadata in a fixed
eight-entry FIFO (32 bytes per entry; the current Consumer Control report remains
two bytes). The host task submits at most four entries per tick, with a fresh
epoch/security/CCCD check immediately before the actual notification. Policy or
connection changes discard old entries. A stale lease or old-generation entry
is rejected/discarded without pausing a healthy new host.

Capacity/ENOMEM failures close admission and disconnect rather than retry
indefinitely or silently retain held input. A neutral old-host report is attempted
before explicit policy or alias changes when a non-neutral report was submitted.
GATT input reads return the matching native-generation report state or neutral
bytes, never another host's stale VM characteristic cache.

## Persistence, failures and validation boundary

Policy and aliases occupy an atomic checksummed blob in the separate
`bm83_hid_policy/policy_v1` namespace. Missing policy starts PAUSED with no
arbitrary selected host. Corrupt/unavailable policy reports ERROR and admission
stays closed. A failed request attempts to persist PAUSED; if NVS is unwritable,
`persisted=False` means a new durable intent cannot be promised. Existing
`nimble_bond` records are retained during ordinary switching. Only an explicit,
confirmed single-host Forget removes the chosen peer records. The local IRK,
other saved hosts, partition layout and application settings are retained.

Security/CCCD/CSFC overflow never invokes round-robin deletion. Existing key
replacement and repeat-pair attempts are refused. The legacy global
`erase_bonding()` method raises under this capability; normal switching has no
erase or repair side effect. Explicit Forget is available only under the
clean-PAUSED preconditions above. Native faults take priority over already queued
commands; recovery requires a later explicit intent.

The host harness compiles production core and ESP32 bridge function bodies with
external API/header stubs, including ASan/UBSan fault cases. It does not validate
the controller's RF resolving list, actual NVS persistence, OS HID behavior,
audible audio, physical screens, or whole-runtime timing. Two identical clean
Linux native builds and the declared physical matrix remain required before
claiming the corresponding acceptance scope.

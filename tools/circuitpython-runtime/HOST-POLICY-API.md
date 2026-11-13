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

During an explicit ENROLL window, descriptor-resolved and software IRK-resolved
saved identities are refused before SMP. This preserves the host's existing
bond instead of inviting rekeying that the unit would later refuse to store.
The bounded software resolver is a policy classification, not proof of physical
host ownership. Fresh enrollment uses an explicitly established empty baseline.
A saved identity supplied later by SMP also rejects the admitted link before
its key writes. Even equal-key security writes for a saved identity in that
window are refused, so the vendor cannot change its existing `bond_count`.
AUTO selection is unchanged. The earlier experimental software-hint deferral
and failed-restore drain have been removed.

For every ENROLL link, the pinned SMP OUR→PEER callback order is guarded with
one bounded private RAM slot. OUR is held without NVS writes or a persisted
candidate mark until PEER arrives. A distributed peer IRK must differ from
every other saved identity's IRK and, for an RPA link, resolve the original
connection RPA. Only then are OUR and PEER written and read back in order.
The slot is bound to handle, connection generation and operation, and is
zeroed on rejection, disconnect, timeout, cancellation, fault or replacement.
The store-lock callback latches rejection without calling GAP; the host service
then reports SECURITY code10 (duplicate IRK),11 (missing/nonmatching IRK for
the original RPA), or12 (key sequence/scope mismatch) and terminates once.
These checks write no new security records when validation fails. A later
backend failure after OUR is durable can still leave that partial new record;
it fails closed without replacing an old host or automatically deleting data.
Stable-address peers without a distributed IRK are supported: the pinned SMP
code unconditionally dispatches PEER after OUR, even when its key flags are
empty. AUTO and saved-key restoration do not use this staging path.

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

### Optional pre-admission diagnostics, version 1

The optional saved-refusal identity observation is separate from the unchanged
33-counter diagnostic block. `saved_refusal_version=1` adds
`last_saved_refusal_id` (public opaque16-hex label or `None`),
`last_saved_refusal_source` (`descriptor`, `software`, or `None`),
`last_saved_refusal_operation_id` and `saved_refusal_window_count` (u32).
All five fields are copied atomically with status. An actual
`HP_CONNECT_SAVED_IDENTITY` refusal or an authoritative saved identity newly
rejected by SMP identity handling updates the record. The latter uses
`descriptor` and counts once per admitted link; repeated late callbacks do not
count again. The unchanged33-counter block counts pre-admission refusals only,
so a late saved-ID record on an admitted generation can be distinguished from
a pre-admission refusal or an identity-free timeout. A different operation
resets the record's saturating count on its first actual refusal. A new window without
such a refusal retains the explicitly older-operation record. The empty record
has `None` identity/source and zero operation/count. No address, key or IRK is
exported. `NativeHostPolicy.refusal_identity` validates/caches these fields from
the same existing status read; missing/future/malformed capability gives `None`
without changing readiness. A separate optional tag may observe this cache;
frozen state and admission counter records are unchanged. This labels native
classification, not a proven physical-device attribution. Continuity must be
established by uninterrupted capture; post-interrupt snapshots cannot repair a
lost native observation epoch.

Instrumented runtimes add `diag_version=1` and flat `diag_*` scalar fields to
the existing `host_status` dictionary. `host_policy_version` remains1, and the
ordinary policy/status fields and admission decisions are unchanged. Older
clients ignore these additions; older runtimes omit them. The Python owner
extracts a bounded `NativeHostPolicy.diagnostics` cache from its existing status
read without an extra native call. Missing, malformed or future diagnostics
produce `None` without changing policy readiness or input decisions. Diagnostic
output belongs under a separate `[HOST_ADMISSION]` record, not inside the strict
observer schema2 record.

Counters are unsigned32-bit, saturate at `0xffffffff`, and persist for the
native image's boot lifetime, including VM reloads and BLE disable/re-enable.
They are not persisted to NVS. `event_sequence` saturates too; once saturated,
exact event differences cannot be recovered. Updates and the complete exported
diagnostic snapshot use the existing short policy mux; callbacks allocate,
print and call no extra GAP/store function. No address, opaque peer ID or key
material is present in this diagnostic block.

The names below are shown without the native `diag_` prefix:

| Fields | Meaning |
| --- | --- |
| `connect_events`, `connect_successes`, `connect_failures` | CONNECT callbacks observed before admission/publication or wrapper/generation filters. Success means raw status0 only, not admitted, bonded or HID ready. |
| `last_connect_status`, `last_connect_source` | Full signed native status; source1=central Adapter callback,2=advertising callback,3=connection callback. Meaningful after `connect_events>0`. |
| `admission_attempts`, `admissions` | Bridge admission calls and nonzero policy generations allocated. Attachment can still fail before a CircuitPython wrapper is published. |
| `adapter_publications`, `attach_failures`, `refused_adapter_slot` | Actual wrapper publication, callback-attachment failure, and no free CircuitPython connection slot. Distinct from a raw CONNECT or core admission. |
| `refused_unsynced`, `refused_store_guard`, `refused_conn_missing`, `refused_resolver` | Bridge refusal before the core: unavailable sync, changed store guards, missing live descriptor, and software resolver failure/ambiguity. |
| `refused_policy`, `refused_slot`, `refused_auto_identity`, `refused_saved_identity`, `refused_candidate` | Exactly the core predicates: closed admission, existing active handle, wrong AUTO identity, existing ENROLL identity, and another ENROLL candidate. Each refused core call still terminates once and allocates no generation. |
| `saved_irk_matches` | A completed software resolver match, separate from whether the core subsequently refuses it. It does not identify which saved host matched, nor establish the iPhone's address type. |
| `adv_complete_events`, `adv_complete_zero_reason`, `adv_complete_nonzero_reason`, `last_adv_complete_reason` | Raw advertising completion callbacks and full last reason. A zero reason is not universally a successful connection: the pinned legacy directed-timeout path also emits0. Meaningful last reason requires an observed completion. |
| `policy_stop_calls`, `policy_stop_errors` | Existing policy backend GAP-stop calls and errors other than the previously tolerated EALREADY/EINVAL. No additional stop is issued. |
| `vm_stop_requests`, `vm_stop_active`, `vm_stop_errors` | Existing Adapter stop requests, those whose existing active check was true, and untolerated native stop errors. Includes automatic Adapter cleanup after advertising callbacks; not necessarily an owner action. |
| `last_stop_result`, `last_adv_cause` | Last local stop result and latest observed category:1=policy stop call,2=Adapter stop request,3=CONNECT callback,4=ADV_COMPLETE callback. These categories are observations, not proof of RF causality or why an unobserved controller transition occurred. |
| `last_refusal_reason` | Last counted category:1=unsynced,2=store guard,3=missing descriptor,4=resolver,5=policy,6=active slot,7=AUTO identity,8=saved ENROLL identity,9=candidate mismatch,10=Adapter slot. Meaningful only after a refusal count. |

The callbacks and admission attempts are intentionally different metrics. A
single physical attempt can yield more than one callback or no observed
successful CONNECT before an early failure. Counters do not identify a central,
replace iPhone-side/SMP evidence or count unreported RF activity. Native faults,
security, subscription and ordinary policy generations remain independently
reported through the original status fields.

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
risk before installation. The current host tests, native builds, installation
and scoped physical results are recorded separately in the
[Phase 2 evidence](../../docs/reliability/phase2-host-selection.md). A successful
build or install does not establish the remaining physical acceptance checks.

## Explicit all-peer maintenance clear

`adapter.clear_saved_hosts(bond_generation)` is an optional version-1 capability;
clients detect that method separately. It returns one queued operation ID and
does not run at startup, on pairing failure or from the legacy Erase action.
The owner must explicitly authorize deleting every saved peer. The native and
Python owner both require current coherent generation, clean persisted PAUSED,
no link, no advertising and no queued, busy or faulted operation. The host task
refreshes and rechecks generation before modifying storage. A fault consumes the
queued operation without silently treating it as a policy-mode request.

The host task stops advertising, clears controller resolving/accept lists,
commits and reads back PAUSED with all selection/alias entries cleared, then
erases only the pinned peer-family slot keys in `nimble_bond`: `rpa_rec_1..8`,
`csfc_sec_1..8`, `our_sec_1..8`, `cccd_sec_1..24`, `peer_sec_1..8`. It commits
and verifies every slot absent before clearing those exact RAM arrays, counts
and OUR/PEER bond counters under the host lock. This intentional ALL-peer path
accepts legacy duplicates and orphan owners without weakening per-host Forget.
It never calls `ble_store_clear`, `erase_bonding`, namespace erase or partition
erase; local IRK records/RAM, unrelated NVS namespaces and application/private
files are untouched. No advertising or pairing starts automatically.

Completion requires the caller's own operation, an advanced bond generation,
clean PAUSED, no target and a coherent empty peer list. A partial NVS erase,
commit/readback failure or stale generation reports ERROR and stops; there is
no automatic retry or restoration. Full backups remain the separate recovery
artifact. Public empty-list evidence does not itself prove raw key-byte erasure.

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
confirmed single-host Forget removes the chosen peer records. The separate
owner-authorized all-peer maintenance operation above removes all five peer
families. Both retain local IRK, partition layout and application settings.

Security/CCCD/CSFC overflow never invokes round-robin deletion. Existing key
replacement and repeat-pair attempts are refused. The legacy global
`erase_bonding()` method raises under this capability; normal switching has no
erase or repair side effect. Explicit Forget is available only under the
clean-PAUSED preconditions above. Native faults take priority over already queued
commands; recovery requires a later explicit intent.

A bonded peer disabling notifications is a subscription change. Pinned NimBLE
routes a write of CCCD flags zero through its delete callback. For the exact
still-connected, encrypted, bonded peer and a concrete characteristic, the
bridge retains that canonical CCCD slot with flags zero. A subsequent authorized
subscription updates the same slot. Neither operation deletes security keys or
another host's records. Wildcard keys, another peer, stale/disconnected links,
ambiguous slots and pending faults cannot use this path. Disabling the old live
link remains permitted during a queued Disconnect or Select; enabling reports
cannot cross that policy or input-generation barrier.

The subscription writer changes one uniquely matched NVS slot, commits and reads
back the complete canonical record before updating RAM. A failed write, commit
or readback stops with an NVS fault and leaves RAM unchanged; it does not promise
transactional restoration of a slot that may already have reached flash. A saved
host with disabled notifications remains resumable, while HID readiness still
requires a current input subscription. Secondary store-guard callbacks retain
the domain and code of the first pending or published native fault, so a
subsequent security refusal cannot mask that storage failure. This is scoped
fault retention, not a complete event history: other core failure paths can
still report a later error.

The host harness compiles production core and ESP32 bridge function bodies with
external API/header stubs, including ASan/UBSan fault cases. It does not validate
the controller's RF resolving list, actual NVS persistence, OS HID behavior,
audible audio, physical screens, or whole-runtime timing. Two identical clean
Linux native builds and the declared physical matrix remain required before
claiming the corresponding acceptance scope.

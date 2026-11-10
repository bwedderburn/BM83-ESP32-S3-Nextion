# BM83 Remote - Verified Reliability

[Private Project](https://github.com/users/bwedderburn/projects/3) |
[Milestone](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/milestone/1)

Owner: @bwedderburn. The separately authorized November 4 B-Intel hardware run
completed its agreed Phase 1 scope; see the
[dated acceptance record](phase1-bintel-2026-11-04.md). Phase 2 Disconnect + Select
host source work may now proceed, with its own build and physical-test gates.
Other hosts, power orders and native-failure cases are not accepted by that result.
Codex delivers validated work by direct commit/push;
see [the current maintenance handoff](DIRECT-MAINTENANCE.md). Historical drafts:
[BM83 #189](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/pull/189) and
[Universe #10](https://github.com/bwedderburn/github-universe-2026/pull/10).

## Evidence, not inferred success

| Observation | What it establishes / does not establish |
| --- | --- |
| True original main and 20 project libraries matched pre-task source b695d8d | Original provenance; not a receiver-bearing rollback |
| Original observation: 582.4 seconds, stopped on user-confirmed intentional Music volume change | Incomplete observation, not a proven controller fault; physical acceptance unconfirmed |
| User reported original/helper stability over ten minutes | User report, not instrumented acceptance |
| Receiver-bearing v2: 600.4 seconds; last fresh sample around 146.1 seconds; 70 fresh samples all matched Music | Data path failed well before late IP loss; cached flags cannot count as healthy time/link |
| Native ESP-NOW NO_MEM and roughly 2.7-second stalls | Resource failure symptom, not proof of a full TX queue as root cause |
| Hash/PSA lifetime hazard in pinned source | Conditional on actual native backend; deployed binary/configuration and causality unproven |
| Host tests and simulator cases passed | Neither proves current physical screens, live metadata, controls or safe runtime teardown |

The historical observations above retain their original classifications. The
November 4 B-Intel run later passed its scoped measured and physical checks,
restored the exact original 127 controller files, and verified CrowPanel recovery
without manual reconnect. Candidates, private manifests and raw captures stay
outside Git. Repository work itself does not authorize device operation.

### Per-arm evidence follow-up (2026-11-09)

These are separate historical arms, not a matched experiment. Host and route,
native-runtime provenance and instrumentation differ; the records establish no
receiver/radio causal comparison. The receiver-present but inert arm was not run.

| Arm | Committed evidence | Host, runtime and instrumentation boundary |
| --- | --- | --- |
| True-original baseline, November 1 | [Hash-close record, lines 9-15](../../tools/circuitpython-runtime/VALIDATION-HASH-CLOSE-2026-11-01.md#L9-L15): verified original entrypoint and 20 libraries; 1,800 uninterrupted seconds and six natural Music track changes. | Original Music path, before the patched native image was installed; that paragraph does not specify host versions. Passive CrowPanel playback and owner screen observations; badge at its launcher. The later stopped-runtime heap probe was a separate check. |
| Receiver enabled, Mac route, November 2 | [Delivery record, lines 148-178](../validation/bm83-startup-artwork-validation-2026-11-01.md#L148-L178): 1,800.010162 seconds, with the scoped owner-combined controls/screens result. | Mac metadata-helper route on the patched runtime already [installed separately](../validation/bm83-startup-artwork-validation-2026-11-01.md#L71-L78); host STATUS/route/helper/clock observer plus owner checks, without native heap instrumentation. Retries and transient no-reply observations remain in the record; its [remaining limits](../validation/bm83-startup-artwork-validation-2026-11-01.md#L187-L201) still apply. |
| Receiver enabled, Windows B-Intel, November 4 | [Accepted Phase 1 scope](phase1-bintel-2026-11-04.md#L1-L28), [measured window](phase1-bintel-2026-11-04.md#L49-L89) and [remaining limits](phase1-bintel-2026-11-04.md#L91-L121). | Windows Apple Music route, qualified UART/clock observer and owner physical checks; original controller files were restored, but native controller flash was not freshly attested. This accepts only the agreed B-Intel scope. |
| Receiver present but inert | Not run. | No matched host/route, native-runtime or instrumentation evidence exists for this arm. |

The [hash-close record's then-pending 1,800-second receiver-enabled run](../../tools/circuitpython-runtime/VALIDATION-HASH-CLOSE-2026-11-01.md#L135-L139)
was subsequently performed on [November 2](../validation/bm83-startup-artwork-validation-2026-11-01.md#L148-L178),
within that Mac-route scope; the dated record remains unchanged.

### Hash-lifetime claim attribution (2026-11-09)

The existing hash/PSA hazard row above is historical. These later records support
different claims; none attributes the earlier failure near 146 seconds or resolves
the VM-teardown fault.

| Record | What it establishes | What it does not establish |
| --- | --- | --- |
| [Installed-runtime allocation check, lines 17-23](../../tools/circuitpython-runtime/VALIDATION-HASH-CLOSE-2026-11-01.md#L17-L23) | On the stopped installed runtime, hash construction followed by GC left unrecovered native allocations: 1,060 bytes after eight hashes and 1,920 bytes after another sixteen. | Cause of the earlier radio failure, DMA-specific health or receiver stability. |
| [Reviewed Hash.deinit patch and host tests, 95dde86](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/commit/95dde864b08d44b07bfbe75d26f583fa316a2099), with [validation boundaries](../../tools/circuitpython-runtime/VALIDATION-HASH-CLOSE-2026-11-01.md#L40-L73) | Deterministic cleanup/error paths and bounded host-model behavior were reviewed and tested. | A host model is not the actual ESP32 backend/collector or physical radio proof. |
| [Patched-image installation, lines 75-85](../../tools/circuitpython-runtime/VALIDATION-HASH-CLOSE-2026-11-01.md#L75-L85) | Separately approved app-slot write, full 8 MiB readback, exact new image and unchanged bytes outside the app slot. | A subsequent native heap trend, radio causality or general runtime acceptance. |
| [Scoped native hash/HMAC checks, lines 100-119](../../tools/circuitpython-runtime/VALIDATION-HASH-CLOSE-2026-11-01.md#L100-L119) | The specified warmed batches and predeclared collection decision passed on the patched image. The earlier failed first-collection result remains recorded. | DMA headroom, a universal resource bound or safe VM teardown. |
| [November 2 receiver-enabled run, lines 148-178](../validation/bm83-startup-artwork-validation-2026-11-01.md#L148-L178), on the [separately installed patched image](../validation/bm83-startup-artwork-validation-2026-11-01.md#L71-L78) | The Mac-route workload and combined owner checks passed for 1,800.010162 seconds. | This run carried no native heap instrumentation, so it establishes no native heap trend or attribution of the earlier failure. The [teardown and power-order limits](../validation/bm83-startup-artwork-validation-2026-11-01.md#L187-L201) remain. |

## Work graph

| Issue | Scope | Closure predecessors |
| --- | --- | --- |
| #190 | Original-versus-receiver dropout isolation | Approved protocol before experiments |
| #193 | Crypto/socket/native heap | #190 |
| #195 | ESP-NOW TX / UART responsiveness | #190, #193 |
| #191 | Metadata/status/control UX and paired add-on | #193, #195 |
| #194 | Reproducible rollback and final hardware acceptance | #190, #193, #195, #191 |
| #192 | Phase 2 bond-preserving BLE HID Disconnect | #194 and actual Phase 1 acceptance |

Preparing this protocol does not require closing #194. Experiments follow the
protocol, while #194 closes only after the resulting integration is accepted.

## Local maintenance / VS Code

Codex owns the current work while Copilot's allowance is exhausted. Use isolated
integration worktrees, pinned host tools and direct commits/normal pushes to
`origin/main`; no new PRs or paid AI jobs. Preserve account, billing, credentials,
MCP, approvals, folder trust and protected-branch policy. Never force-push.
The two user-invoked read/search VS Code review profiles remain for future use;
a loaded profile does not establish an executed review or hardware acceptance.

The weekly Copilot and Claude workflows are retired. Codacy remains the sole
explicitly exempt legacy scanner; retired filenames cannot bypass policy checks.
Existing secrets are untouched. Keep hardware offline throughout these checks.

Development-only requirements pin pytest/flake8, Bandit, pip-audit and PyYAML.
They provide host regression, security/dependency checks and configuration
parsing; they are not firmware dependencies. In this checkout:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-reliability.txt
.venv/bin/python scripts/check_reliability_setup.py
.venv/bin/python -m flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
.venv/bin/python -m pytest -q
.venv/bin/python -m bandit --ini .bandit -r firmware/circuitpython addons/universe-badge/apps/bm83_remote scripts -ll
.venv/bin/python -m pip_audit -r requirements-reliability.txt
.venv/bin/python -m pip_audit -r tools/mcp/repo_health/requirements.txt
```

Windows uses `.venv\Scripts\python.exe`. VS Code's `BM83:` tasks only run selected
Python processes on explicit invocation; none deploy, open serial or run at
folder open. Run the Universe repository's
`scripts/check-bm83-addon.py --bm83-repo <canonical-checkout>`; that script is the
authoritative file list. Use exact
reviewed revisions in the evidence record, not changing branch tips.

Checked-in PR workflows use GitHub-hosted runners, read-only contents permission, full-SHA
Actions and nonpersistent checkout credentials. Security/dependency checks do
not need Codacy tokens, SARIF write permissions or a paid security feature.
YAML is supported for issue forms; GitHub PR templates are Markdown, not YAML.
The structural checker is a regression guard, not a complete GitHub/VS Code
schema validator or security sandbox.
It requires the declared workflow files and checks the literal Bandit command,
target paths and matching VS Code arguments. It does not execute Bandit or prove
every workflow behavior. The [post-landing CI records](release-handoff-2026-11-07.md#later-main-scope-and-ci-record)
provide the recorded execution results.

### Native-build dependency security and separate hardware gate

The active isolated recipe updates `cryptography==46.0.7` to **50.0.0**, covering
the four previously reported advisories (three high, one moderate). The matching
constraint is a deliberate security override validated against the pinned IDF
tools. Because cryptography 49+ removed Intel macOS support/wheels, preparation
and compilation use a supported Linux amd64 container on the Mac. The native
CircuitPython/IDF/NimBLE source commits and reviewed board configuration remain
unchanged. These are host build-tool dependencies, not evidence about the
controller's native PSA/SHA failure.

```sh
.venv/bin/python -m pip_audit --disable-pip --no-deps -r tools/circuitpython-runtime/requirements-build.txt
```

The corresponding VS Code task preserves a nonzero result; no advisory is
ignored. Host-security CI now audits this entire pinned manifest alongside the
development and MCP requirements. Dependabot continues to cover the directory.
See the [isolated build recipe](../../tools/circuitpython-runtime/README.md) and
its [sanitized validation record](../../tools/circuitpython-runtime/VALIDATION-2026-11-01.md)
for actual tool compatibility, clean-build reproduction and provenance checks.
Keep raw logs and generated firmware outside Git. Original frozen images,
backups and historical constraint hashes remain intact; the active snapshot has
separate hashes. Issue #193's native-radio causality investigation and the
physical acceptance gates remain open independently of dependency remediation.

## Derive budgets before claiming responsiveness

Record the original baseline's loop/TX/UART distributions, sample count and
maximum, plus configured UART baud, frame sizes, receive-buffer capacity and
protocol timeouts. For 8N1, wire time is `10 * frame_bytes / baud`; buffering
headroom follows from bytes available and incoming byte rate. Subtract measured
work and a documented safety margin from the tightest protocol/buffer deadline.
Measure under the same workload in both arms. Record missing quantities as
unmeasured and block acceptance until obtained.

The candidate's 250ms/2s thresholds are provisional containment triggers, not
approved latency budgets. Python cannot preempt the first synchronous native TX
stall. Report Python GC and native 8-bit heap separately; neither proves internal
DMA availability. Unsupported queue/socket counters are unavailable, not zero.

Source-input inventory (2026-11-09), pinned to
[N2 c14b108](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/commit/c14b108bd46059bad903e3250cc1fec9b38b8c7a):
these configured values and code paths are inputs, not new measured budgets.
Measurements for new matched arms remain unmeasured; private prior-run captures
are not substituted for a matched experiment.

| Input | Source-defined value or behavior | Measurement status / missing evidence |
| --- | --- | --- |
| UART configuration | BM83 115200 baud / configured 8192-byte receive buffer; Nextion 9600 baud / configured 1024-byte receive buffer; both UART calls use `timeout=0.0`. [main.py:29–30](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/main.py#L29-L30); [main.py:84–88](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/main.py#L84-L88). | Configuration is source evidence. Actual usable driver/FIFO capacity and reserve are unmeasured/unavailable; the diagnostic schema explicitly sets `capacity_verified=False`, reserve and native-overflow fields to `None` ([phase1_metrics.py:265–275](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/utils/phase1_metrics.py#L265-L275)). The diagnostic record assumes 8N1; UART constructors leave bits/parity/stop at runtime defaults. |
| BM83 frame/parser/service bounds | `0xAA`, two-byte body length, opcode/parameters and checksum; parser active cap 4096 bytes; default poll reads at most 768 bytes and returns at most 8 events. [bm83.py:201](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/bm83/bm83.py#L201); [bm83.py:426–431](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/bm83/bm83.py#L426-L431); [bm83.py:462–470](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/bm83/bm83.py#L462-L470); [bm83.py:518–526](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/bm83/bm83.py#L518-L526). | Actual frame-size distribution, arrival bursts, queue peaks and service gaps for matched arms are unmeasured; raw captures from prior scoped runs are held privately. Parser storage is separate from the configured native UART buffer. |
| Nextion framing and pacing | ASCII command plus three `0xFF` terminators; parser cap 512 bytes, retains 128 on overflow; reads at most 256 bytes and returns at most 6 tokens per call; TX interval 35 ms, queue cap 50. [display.py:5–14](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/nextion/display.py#L5-L14); [display.py:103–108](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/nextion/display.py#L103-L108); [display.py:148–183](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/nextion/display.py#L148-L183); [display.py:239–280](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/nextion/display.py#L239-L280). | Actual command/frame lengths, queue residence, burst rate and write duration are unmeasured for matched arms or held privately for prior runs. The comment about ordinary frames under 32 bytes is not an enforced universal wire-size limit. |
| Main-loop service order | Nextion tick/read precedes BM83 poll; remote input is serviced later; cached state publication occurs after UART/control work; loop requests a 5 ms sleep and periodic GC is checked after more than 4 s since the prior collection. [main.py:358–375](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/main.py#L358-L375); [main.py:456](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/main.py#L456); [main.py:637–645](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/main.py#L637-L645); [main.py:846–862](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/main.py#L846-L862). | Observed loop/UART service-gap distributions, sample counts, maxima, GC cost and matched-workload workload traces are unmeasured for new arms or held privately for prior runs. Sleep/ordering are not a measured loop period or a maximum blocking bound. |
| ESP-NOW publication bounds | State snapshots: 1000 ms period, 40 ms frame gap, 2000 ms incomplete-snapshot deadline; at most one frame per publisher tick. BMS2 frames max 64 bytes; BLS2 exactly 21; BHP1 fragments max 64, status period 1000 ms, list period 4000 ms. [state_tx.py:12–14](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/remote/state_tx.py#L12-L14); [state_tx.py:197–238](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/remote/state_tx.py#L197-L238); [espnow_rx.py:280–301](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/remote/espnow_rx.py#L280-L301); [host_policy.py:14–18](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/remote/host_policy.py#L14-L18); [host_policy.py:89–106](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/remote/host_policy.py#L89-L106). | Actual publisher wait, native send-call time, observed completion latency and accepted/dropped frame distributions are unmeasured for matched arms or held privately for prior runs. These constants are scheduling/protocol controls, not approved responsiveness budgets. |
| Native send ownership/completion/backoff | One existing native radio and configured peer; BMS2/BLS2/BHP1 share the pending slot and native success/failure-counter check. Synchronous failure sets a 5 s backoff. RX recovery clears the peer, cancels the pending ticket as `False`, and deinitializes before setup. [espnow_rx.py:238–278](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/remote/espnow_rx.py#L238-L278); [espnow_rx.py:303–355](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/remote/espnow_rx.py#L303-L355); [espnow_rx.py:391–410](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/remote/espnow_rx.py#L391-L410). | First synchronous native send cannot be preempted by Python; the source warning describes native retries up to 2 s, not a universal measured bound. An unchanged callback counter leaves the pending slot blocked; no callback timeout/quarantine guarantee is implemented. For a new matched experiment, live native timing, queue/FIFO/ISR/DMA pressure and per-frame delivery remain unmeasured/unavailable or held privately for prior runs, not zero. |
| Measurement definitions | Optional diagnostics distinguish loop gap, UART queue-poll/read/write, native send call and observed completion; retain samples/maxima/histograms and generation-aware callback deltas. [phase1_metrics.py:14–38](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/utils/phase1_metrics.py#L14-L38); [phase1_metrics.py:147–189](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/utils/phase1_metrics.py#L147-L189); [phase1_metrics.py:203–230](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/blob/c14b108bd46059bad903e3250cc1fec9b38b8c7a/firmware/circuitpython/lib/utils/phase1_metrics.py#L203-L230). | Full original/candidate distributions, hidden-byte allowance, actual protocol deadlines, measured work and owner-selected margin for a new matched experiment are unmeasured or held privately. Native callback observations are not per-frame delivery evidence. |

The [B-Intel fixed limits and callback boundaries](phase1-bintel-2026-11-04.md#L73-L89)
are scoped historical results: derivation preceded arming, cumulative maxima retain
earlier intervals, and callback baseline boundaries differ. Its
[remaining limits](phase1-bintel-2026-11-04.md#L100-L116) retain unavailable native
FIFO/ISR, DMA/internal-heap and socket counts, and the first synchronous native-send
risk. Raw details remain private; these summaries yield no new headroom figure,
responsiveness budget, universal worst-case bound or earlier-failure attribution.

## Later hardware run card - separate authorization required

1. Record exact candidate, source/compiler and true-original rollback hashes
   privately; distinguish previous receiver-bearing rollbacks. Check serial
   ownership and guarded files. Preserve profiles, keys, bonds and other apps.
2. Prepare an allowlisted paused-runtime/safe-mode install and bounded recovery
   path. State the exact change and required cold start before seeking consent.
   A teardown fault is distinct from a post-start runtime/data-path fault.
3. Keep route, helper, workload and instrumentation matched across original and
   receiver arms. Original baseline has BMW1 traffic disabled. Never start a
   competing helper; preserve user-intended playback and volume.
4. Run at least **30 uninterrupted stable minutes** per accepted build/workload.
   Use one persistent authenticated client where the receiver is enabled; no
   client churn, power/retry gestures or CrowPanel serial reopen during quiet soak.
5. Stop on first fault or uncontrolled condition change; classify the cause.
   Do not reset repeatedly or count truncated/stale intervals as passed time.
   Capture fresh-only metadata match rates, clock/link advancement, unavailable
   intervals, native errors and latency/resource trends.
6. After a quiet soak passes, separately coordinate power/reconnect regression.
   Correlate actual track changes helper-off and helper-on across source,
   receiver and badge; identify origin and unsupported artwork/time/native fields.
7. Require actual user confirmation of Nextion, CrowPanel and badge screens,
   play/pause, next/previous, volume, HOME and reopen. Automated answers, audio,
   UART ACKs and local API results cannot substitute for this check.

| Platform / path | Required evidence | Current verdict |
| --- | --- | --- |
| macOS / Apple Music / helper off | Real track correlation; native origin or honest unsupported result | Not accepted |
| macOS / Apple Music / helper on | Fresh receiver/badge title/artist; controls and advancing link | Not accepted |
| Windows / B-Intel Apple Music + separate BLE HID | Qualified measured window, owner screens/buttons, exact restoration and automatic CrowPanel recovery | [Accepted scoped run, 2026-11-04](phase1-bintel-2026-11-04.md); BM83 audio power-cycle wedge remains separate |
| Linux / claimed audio + BLE HID stack | Exact OS/stack/runtime, supported paths, reconnect and physical controls | Not tested |

Record exact versions privately and publish only sanitized coverage/results.
Do not infer another platform or power-order result from the accepted B-Intel
case. Phase 2 needs its own complete bond-preserving disconnect/select-host
matrix; the dated B-Intel acceptance supplies its agreed Phase 1 prerequisite.

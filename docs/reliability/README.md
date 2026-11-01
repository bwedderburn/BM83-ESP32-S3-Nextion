# BM83 Remote - Verified Reliability

[Private Project](https://github.com/users/bwedderburn/projects/3) |
[Milestone](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/milestone/1)

Owner: @bwedderburn. This is a frozen, host-only investigation setup, not hardware
authorization or Phase 1 acceptance. Both implementation PRs remain draft:
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

The last verified restore used the original application with new receiver files
inert, and the badge was confirmed at its launcher. Candidates, exact private
manifests and raw captures stay outside Git. Do not operate the device to refresh
this record during repository work.

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

## Local Copilot / VS Code

Open the intended checkout in VS Code, retain the existing signed-in GitHub
account and normal approval settings, and select its `.venv` Python interpreter.
The two `.github/agents/reliability-*.agent.md` profiles are user-invoked, VS Code
scoped and read/search only, with no model pin. Use the runtime profile for
protocol/resource ownership and the delivery profile for CI/evidence/UX gates.
Select an appropriate model actually offered in the Copilot picker. Claude
models inside Copilot are allowed; separate Claude Code/app workflows are not.
Omitting `model` uses the currently selected model, per the
[VS Code agent reference](https://code.visualstudio.com/docs/agents/reference/custom-agent-file-reference).
Verify both agents appear and actually run read-only reviews in VS Code. Record
the selected model, exact diff/revision, tools used, findings and disposition.
File validation and reviews in Copilot Desktop alone do not establish this.

Do not add MCP servers, accounts, tokens, firewall exceptions or change billing
or approvals. If Restricted Mode blocks the agents, ask the owner before
trusting the specific source folder; never broaden trust to its parent or
disable Workspace Trust. Do not assign issues to the cloud coding agent. The
weekly Claude/Copilot and Codacy workflows are preserved as labeled out-of-scope
general automation (see `docs/agents/SETUP.md`); they are not PR checks and must
not be dispatched for reliability work. Existing secrets/settings are untouched.

Development-only requirements pin pytest/flake8, Bandit, pip-audit and PyYAML.
They provide host regression, security/dependency checks and configuration
parsing; they are not firmware dependencies. In this checkout:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-reliability.txt
.venv/bin/python scripts/check_reliability_setup.py
.venv/bin/python -m flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
.venv/bin/python -m pytest -q
.venv/bin/python -m bandit --ini .bandit -r firmware/circuitpython addons/universe-badge/apps/bm83_remote -ll
.venv/bin/python -m pip_audit -r requirements-reliability.txt
.venv/bin/python -m pip_audit -r tools/mcp/repo_health/requirements.txt
```

Windows uses `.venv\Scripts\python.exe`. VS Code's `BM83:` tasks only run selected
Python processes on explicit invocation; none deploy, open serial or run at
folder open. Run Universe's existing `scripts/check-bm83-addon.py --bm83-repo
<canonical-checkout>` to compare seven app files and three tests. Use exact
reviewed revisions in the evidence record, not changing branch tips.

Checked-in PR workflows use GitHub-hosted runners, read-only contents permission, full-SHA
Actions and nonpersistent checkout credentials. Security/dependency checks do
not need Codacy tokens, SARIF write permissions or a paid security feature.
YAML is supported for issue forms; GitHub PR templates are Markdown, not YAML.
The structural checker is a regression guard, not a complete GitHub/VS Code
schema validator or security sandbox.

### Separate frozen native-build dependency gate

GitHub currently reports **four pre-existing alerts (three high, one moderate)**
for `cryptography==46.0.7` in `tools/circuitpython-runtime/requirements-build.txt`.
The explicit non-installing audit below also fails. These are host build-tool
dependencies, not evidence about the controller's native PSA/SHA failure.

```sh
.venv/bin/python -m pip_audit --disable-pip --no-deps -r tools/circuitpython-runtime/requirements-build.txt
```

The corresponding VS Code task preserves a nonzero result; no advisory is
ignored. Dependabot now covers this directory for reviewed update proposals.
The frozen build snapshot, native source/compiler pins and candidate artifacts
are unchanged. Compatible remediation and reproducible-build validation remain
an open gate in #193. The PR host-security job audits development/MCP dependencies,
not this frozen toolchain; its green result must not be called a clean bill of
health for every manifest. See the repository's protected Dependabot alerts for
details; do not publish private build reports.

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
| Windows / claimed audio + BLE HID stack | Exact OS/stack/runtime, supported paths, reconnect and physical controls | Not tested |
| Linux / claimed audio + BLE HID stack | Exact OS/stack/runtime, supported paths, reconnect and physical controls | Not tested |

Record exact versions privately and publish only sanitized coverage/results.
Do not infer Windows/Linux support from macOS. Phase 2 needs its own complete
bond-preserving disconnect/re-enable matrix after Phase 1 acceptance.

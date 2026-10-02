# Extensive code review & modernization audit — 2026-10-01

Scope: full repository review for correctness, robustness, CircuitPython modernization,
toolchain/dependencies, security, tests/CI, and documentation. The only changes made
are host-verifiable documentation corrections; no firmware behavior or CI workflow
was changed. Hardware validation was not available.

## Executive summary

- Baseline: strict flake8 clean; pytest **146 passed, 1 skipped**; Bandit reports one
  low-severity `try/except/pass` at `blehid/ble.py:466`.
- The core UART paths are defensive: BM83 validates frame bounds/checksums before
  dispatch, and Nextion caps its receive queue and validates tokens against an
  allowlist. The power/link/AUX behavior contracts have substantial regression
  coverage and should not be simplified.
- One concrete robustness candidate remains: the fragmented AVRCP attributes parser
  trusts its 16-bit aggregate length and can retain up to 65,535 bytes across otherwise
  valid frames.
- The build workflow selects an mpy-cross binary dynamically. The S3 listing could not
  be retrieved from this environment, so the exact current binary version is unknown.
- Several documentation paths and Nextion pin references were stale; these were
  corrected in `CODE_REFERENCE.md`, `README.md`, and `DEPLOYMENT.md`.
- The open-issue listing showed this audit issue (#142) and no other open issues. The
  available GitHub issue tools in this session are read-only, so the proposed Phase B/C
  issues below could not be created here.

## Baseline and repository health

| Check | Result |
|---|---|
| Strict flake8 (`E9,F63,F7,F82`) | Pass, 0 findings |
| Style/complexity flake8 | 251 non-blocking findings across maintained code, tests, generated/reference copies; see Phase 2 |
| `pytest -q` | 146 passed, 1 skipped |
| `bandit -c pyproject.toml -r firmware/ -q` | Exit 1 for one low-severity B110 finding |
| Repo-health TODO scan | 0 TODO/FIXME/HACK/XXX/WATCH markers |
| Repo-health 180-day churn | 2 visible commits; shallow history limits the result |
| `repo-health` dependency/inventory calls | Completed through the checked-in MCP server |

Selected inventory from the MCP report: 7,965 Python LOC across the scanned repository;
largest production modules are `lib/bm83/bm83.py` (1,420 lines), `lib/blehid/ble.py`
(696), and `main.py` (633). The largest test is `tests/test_bm83.py` (1,603 lines).
Churn listed many files with one change; because only two commits are visible, this is
not a complete defect-risk ranking.

The style pass reports these complexity offenders in maintained firmware:

| Function | Complexity | Decomposition idea |
|---|---:|---|
| `main()` | 113 | Extract event dispatch, display/token handling, volume-repeat timing, and periodic maintenance into helpers while preserving ordering |
| `Bm83.poll()` | 22 | Separate RX append/trim, frame validation/resync, and validated event dispatch |
| `BleHid._ensure_paired()` | 20 | Separate peer-address probing from pairing-state observation |
| `BleHid._do_erase_bonds()` | 16 | Separate erase fallback and post-erase identity/advertising recovery |
| `Bm83.note_btm_state()` | 15 | Separate state classification from transition/evidence updates |
| `Bm83.parse_gea_0x5d()` | 15 | Separate fragment assembly from attribute decoding |
| `_parse_uint()` | 12 | Isolate input normalization, digit scan, and overflow/range checks |

The style pass also reports an unused `last_avrcp_rx_at` local and a 131-character
condition in `main.py`, along with older whitespace/comment warnings in firmware,
tests, generated `dist/`, and reference code. They are not strict-lint failures. The
unused local and line wrap were not changed: `dist/circuitpython/main.py` is generated
and must stay byte-identical, while mpy-cross is unavailable in this environment.

## Findings

| ID | Severity | Effort | Confidence | Location | Summary |
|---|---|---|---|---|---|
| R-01 | Medium | S | High | `firmware/circuitpython/lib/bm83/bm83.py:1339-1368` | GEA fragment aggregate length is not capped independently of the 16-bit wire length |
| R-02 | Low | M | High | `firmware/circuitpython/lib/blehid/ble.py:569-636` | Bond erase runs synchronously from `tick()` and sleeps three times (0.15 s total) |
| R-03 | Low | M | Medium | `firmware/circuitpython/main.py`, `lib/bm83/bm83.py`, `lib/blehid/ble.py` | Timers use `time.monotonic()`; float precision over long uptime is worth target-runtime verification |
| R-04 | Low | S | High | `firmware/circuitpython/main.py:129,406,476` | `last_avrcp_rx_at` is assigned but never read |
| R-05 | Low | S | High | `firmware/circuitpython/lib/blehid/ble.py:453-467` | Bandit B110 is an intentional best-effort probe over version-dependent BLE address attributes |
| R-06 | Low | S | High | `CODE_REFERENCE.md`, `README.md`, `DEPLOYMENT.md` | Stale source-tree, pin, and deployed-module paths; corrected in this PR |
| R-07 | Low | M | High | `.github/workflows/build-circuitpython-dist.yml:27-71` | Build selects a dynamic mpy-cross version without a pin or checksum |
| R-08 | Medium | S | High | `.github/workflows/python-package.yml:21`, setup-python v7 | CI still includes EOL Python 3.9; setup-python v7 release notes remove EOL versions |
| R-09 | Low | M | High | `tests/test_parser_stress.py`, `tests/test_bm83.py` | Add focused tests for aggregate GEA limits and empty-metadata retry behavior |

### R-01 — Aggregate GEA fragment length

The BM83 UART parser rejects impossible frame lengths and bad checksums before
dispatch (`bm83.py:466-490`), and the UART RX buffer is capped. However,
`parse_gea_0x5d()` reads `total_len` from a 16-bit field (`:1339`), assigns it to
`_gea_expect_len` (`:1359-1364`), and continues appending fragments until that length
is met. There is no smaller aggregate cap. A malformed or unexpectedly large
attribute response can therefore retain tens of kilobytes despite the per-frame
limit. Add a protocol-appropriate aggregate ceiling and a deterministic test for
oversize headers, reset behavior, and subsequent valid parsing. Treat the parser
behavior change as Phase C and verify it against BM83 captures before deployment.

### R-02 — BLE erase timing in the main loop

`BleHid.tick()` invokes `_do_erase_bonds()` when an erase is pending and the central is
disconnected (`ble.py:518-524`). The erase sequence sleeps three times for
`_BLE_STABILIZE_S = 0.05` (`:48`, `:587`, `:590`, `:631`), synchronously delaying
the main loop by about 150 ms. This is a deliberate, hardware-derived sequence rather
than a repeated hot-loop sleep, so do not remove it without testing. A future
step-driven erase state machine could keep UART and UI servicing responsive between
settling steps.

### R-03 — Monotonic timer precision

Main-loop volume-repeat timing and the BM83/BLE schedulers use floating-point
`time.monotonic()` deadlines. No target-runtime precision failure was reproduced here.
Because timers include short intervals (for example, the 80 ms volume repeat), verify
long-uptime resolution on CircuitPython 10.x before considering wrap-safe
`supervisor.ticks_ms()` arithmetic. Do not mechanically replace clocks: all consumers
must retain a consistent time base.

### R-04 — Unused timestamp

`last_avrcp_rx_at` is initialized and assigned for AVRCP responses but is never read.
It is safe dead state by static inspection. The corresponding cleanup was deferred
because this run could not obtain the matching mpy-cross compiler to regenerate and
verify the generated `dist/circuitpython/main.py`.

### R-05 — Bandit B110 triage

Bandit identifies `try/except/pass` around probing `peer_address` and alternate
underlying BLE connection attribute paths. The surrounding code intentionally probes
several version-dependent wrapper shapes and moves to the next candidate when an
attribute getter raises. This is narrowly scoped diagnostic best-effort logic, not a
security boundary or swallowed protocol failure. Retain it; avoid blanket suppression
or logging every failed candidate on each BLE tick.

## Phase 1 — Correctness and robustness

- **BM83 framing:** Length and checksum are checked before event dispatch. Partial
  frames remain buffered, bad frames advance the resynchronization head, and the RX
  accumulator has a maximum size (`bm83.py:425-490`). The GEA aggregate-length issue
  above is separate from these frame-level checks.
- **Nextion:** RX is capped at 512 bytes with a 128-byte retained tail
  (`display.py:156-167`); the queue is bounded, token recovery requires recognized
  tokens, and UI text is sanitized before ASCII output. Reads are guarded by
  `in_waiting`; command writes happen incrementally from `tick()`.
- **BLE:** Pairing is passive-only because initiating pairing from this device has
  caused NimBLE hard crashes during BM83 activity. Advertising failures use bounded
  backoff. Bond erase has the one-time synchronous settle delay described in R-02.
  Preserve the passive pairing and backoff contracts.
- **Main loop:** UARTs use `timeout=0.0`; the loop services events with a short 5 ms
  sleep. Power, link-demotion, AUX boot-window, and staggered AVRCP-notification
  contracts are documented in `.github/copilot-instructions.md` and covered by
  regressions in `tests/test_bm83.py`. Do not change those behaviors without the
  required serial capture/hardware test.
- **Metadata retry:** requests are throttled by `_attrs_throttle_s` and scheduled
  through `tick_avrcp_attrs()`. Add an integration-style host test that an empty
  metadata response cannot create a tight retry loop; tune any retry policy only
  after observing reconnect behavior on hardware.
- **Allocation:** BM83 avoids repeated whole-buffer slicing in its frame scan, but
  validated event payloads and complete GEA attributes are materialized as bytes and
  strings. This is reasonable for current traffic; measure heap pressure before
  optimizing further.

## Phase 2 — Upgradeable code

- No deprecated `busio.UART`, BLE, or supervisor API was established from the source
  review. The code intentionally stays within CircuitPython-compatible APIs.
- Style flake8 reports the complexity offenders listed above. Decompose only in
  focused changes with unchanged event ordering and protocol contracts.
- No hot-loop rewrite is justified from static inspection alone. Continue to avoid
  extra formatted strings and byte copies in frequent UART polling paths.
- `setup.py` still owns package metadata; `pyproject.toml` currently contains only
  CircuitPython bundle and Bandit tool configuration. A `[project]` migration is a
  separate host-packaging task, not required for firmware.

## Phase 3 — Package and toolchain upgrade matrix

Versions below reflect repository evidence or upstream release information available
on 2026-10-01. Runtime libraries are downloaded by users; the repository does not pin
their bundle version.

| Component | Current | Latest stable / observed | Risk | Breaking changes | Recommendation |
|---|---|---|---|---|---|
| CircuitPython runtime | Docs say 10.x; issue context says device has run 10.0.3 | 10.3.1, released 2026-09-14 | Medium | Release notes include Espressif BLE workflow fixes and packet/notification fixes; no UART or supervisor-specific change is called out. ESP32-S3 remains a stable Espressif target. | Test 10.3.1 on the actual board before updating deployment guidance. Keep mpy-cross matched to the runtime. |
| `adafruit_ble` | Required by docs; no bundle/version pin | 10.1.5 (2026-09-29) | Low–Medium | Release fixes forwarding fixed length for complex BLE characteristics; no API break stated. | Record the library bundle/archive version and smoke-test advertise/connect/pair on-device. |
| `adafruit_hid` | Required by docs; no bundle/version pin | 6.1.10 (2026-04-23) | Low | Release notes only describe a Ruff update. | Record bundle version; test ConsumerControl volume/mute after upgrades. |
| mpy-cross | Workflow downloads highest S3 listing match at build time | Exact current version not retrieved; S3 DNS lookup failed in this session | High | A tool/runtime mismatch can create incompatible `.mpy` files; changing S3 contents changes builds without source changes. | Pin a release matching the deployed CircuitPython version and verify a published checksum. |
| Python CI | 3.9, 3.10, 3.11 | Python 3.9 EOL 2025-10-31; Python 3.10 EOL 2026-10-31 | High | Latest installed flake8 7.4.1, pytest 9.1.1, and Bandit 1.9.4 require Python >=3.10; setup-python v7 notes removal of EOL versions. | Remove 3.9; add 3.12 and 3.13, retain 3.11 as baseline, and remove 3.10 by its EOL. Evaluate 3.14 separately. |
| flake8 / pytest / Bandit | Unpinned in CI; resolved here to 7.4.1 / 9.1.1 / 1.9.4 | Same versions were latest available from pip index on audit date | Medium | All observed versions require Python >=3.10, so 3.9 resolves older tool versions. Advisory scan found no known advisories in the observed versions. | Prefer a tested constraints file or explicitly document that versions float; matrix should target supported Python. |
| repo-health `mcp` | `mcp>=1.2,<2` | 1.30.0 installed in audit environment | Low | Major-version range is bounded; no issue known from this audit. Advisory scan found no known advisory for 1.30.0. | Keep the upper bound and review major changes before relaxing it. |
| GitHub Actions | checkout/setup-python/upload-artifact `@v7`; SARIF action `@v4.38.2`; Codacy and Claude action SHAs | checkout v7.0.1, setup-python v7.0.0, upload-artifact v7.0.1 | Low–Medium | setup-python v7 removes its `pip-install` input and EOL Python versions; this workflow does not use `pip-install`, but still requests Python 3.9. | Existing major tags are current; address the Python matrix. Keep third-party SHA pins and review Dependabot updates. |

Advisory check: the resolved pip versions of flake8, pytest, Bandit, and `mcp` were
checked; no vulnerabilities were reported. No dependencies were added or changed.

## Phase 4 — Security and safety

- **Bandit:** one low B110 finding as triaged in R-05; no medium/high findings.
- **Input trust:** BM83 frame checks precede dispatch. AVRCP attribute strings are
  decoded from received bytes and passed through `_sanitize_text()` before display
  updates in `main.py`; Nextion commands use an ASCII encoder and terminator.
  R-01 is the remaining buffer-bound concern.
- **BLE:** pairing stays passive; the service is HID ConsumerControl. The advertised
  name is configurable and no application data channel was identified.
- **Workflows:** Python/build workflows have `contents: read`; Codacy has explicit
  SARIF upload permissions; the weekly Claude workflow has broader write permissions
  for its PR/issue automation. First-party actions use version tags and the Codacy
  and Claude actions are commit-pinned. The unpinned mpy-cross download is the main
  supply-chain reproducibility concern. Workflow changes are out of scope here.

## Phase 5 — Tests and CI gaps

The suite already has strong unit coverage for power evidence, link flaps, AUX
boot-window gating, fragmented UART frames, checksum recovery, metadata parsing, and
volume hold caps. `test_parser_stress.py` currently has two tests. Prioritize:

1. GEA aggregate-length rejection/reset followed by a valid frame.
2. Empty metadata response throttling/backoff without repeated requests.
3. Additional deterministic malformed/truncated parser streams.
4. An end-to-end AUX reconnect sequence test only if it can preserve the current
   hardware-derived `source_ever_seen` guard.

Do not edit CI in this audit; it is explicitly read-only. The following ready-to-apply
proposal deduplicates flake8 from the Python matrix, adds pip caching, updates supported
Python versions, and cancels superseded runs. It is a proposal only; no workflow file
was changed:

```diff
diff --git a/.github/workflows/python-package.yml b/.github/workflows/python-package.yml
--- a/.github/workflows/python-package.yml
+++ b/.github/workflows/python-package.yml
@@ -10,5 +10,8 @@
     branches: [ "main" ]
   pull_request:
     branches: [ "main" ]
-
+concurrency:
+  group: ${{ github.workflow }}-${{ github.ref }}
+  cancel-in-progress: true
+
 jobs:
@@ -18,6 +21,5 @@
     strategy:
       fail-fast: false
       matrix:
-        python-version: ["3.9", "3.10", "3.11"]
+        python-version: ["3.11", "3.12", "3.13"]
-
     steps:
@@ -26,5 +28,7 @@
         uses: actions/setup-python@v7
         with:
           python-version: ${{ matrix.python-version }}
+          cache: pip
+          cache-dependency-path: pyproject.toml
       - name: Install dependencies
         run: |
@@ -33,4 +37,5 @@
           if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
           pip install -e .
       - name: Lint with flake8
+        if: matrix.python-version == '3.11'
         run: |
```

## Phase 6 — Documentation drift

The code reference previously showed project modules beside `main.py`, listed a
nonexistent `test_blehid_advanced.py`, described `settings.toml` and package metadata
that are not in their current locations, and claimed Nextion pins IO43/IO44.
`README.md` also had the wrong Nextion pins. `DEPLOYMENT.md` showed project modules
outside `CIRCUITPY/lib/`. These were corrected to match `firmware/circuitpython/lib`,
the actual tests and configuration, the deploy script, and the source pin assignments
(`IO15/IO16`). Other core guides remain broadly consistent. A standalone
`docs/power-contract.md` would improve discoverability, but the authoritative
behavioral contracts already exist and should be reproduced without reinterpretation.

## Phased plan

### Phase A — safe now

- **Implemented (R-06):** corrected source layout, test inventory, current
  configuration description, deployed module paths, and Nextion pin references in
  `CODE_REFERENCE.md`, `README.md`, and `DEPLOYMENT.md`.
- No firmware files, generated artifacts, dependency versions, or workflows changed.
- The unused timestamp cleanup (R-04) is mechanically safe but was deferred because
  the required generated-artifact build could not be run without mpy-cross.

### Phase B — dependency/toolchain issues to file

1. **Pin mpy-cross to the matching CircuitPython runtime** — make release selection
   and checksum explicit; run the build and parity checks for each pin update.
2. **Refresh supported Python and dev-tool policy** — drop 3.9, add 3.12/3.13, plan
   the 3.10 EOL transition, and choose constraints vs. intentionally floating tools.
3. **Record runtime and library bundle versions** — test CircuitPython 10.3.1 and
   current Adafruit BLE/HID bundles on hardware before updating deployment guidance.

### Phase C — design/behavior issues to file

1. **Bound fragmented GEA metadata and test retry behavior** — add an aggregate
   maximum and empty-response backoff coverage; validate on a BM83 serial capture.
2. **Keep BLE maintenance and long-uptime timers responsive** — consider stepping the
   bond-erase sequence and verify monotonic timer precision on target hardware.
3. **Decompose high-complexity protocol/event functions** — break down `main()`,
   `Bm83.poll()`, `note_btm_state()`, `parse_gea_0x5d()`, and BLE maintenance without
   changing ordering or any documented behavioral contract.

### Issue filing status

Open issues were checked before drafting these themes; the visible open list contains
this audit issue (#142), with no separate open issue matching the themes above. This
session's GitHub tool set provides issue listing/reading but no issue-creation
operation. Consequently, the issues above are ready-to-file drafts, not completed
GitHub issues. Issue #142 remains open to track this unfinished filing work and
should not be closed by this PR.

## Verification summary

Baseline verification was completed before documentation edits: strict flake8 passed,
pytest reported 146 passed and 1 skipped, and Bandit reported only the single low
B110 finding documented above. Documentation-only changes do not affect firmware
or generated artifacts; re-run the final strict lint and pytest checks before merge.
Hardware test: not required for these documentation corrections; future firmware
behavior proposals require `needs-hardware-test`.

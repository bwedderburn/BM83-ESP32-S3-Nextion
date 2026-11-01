# Direct maintenance handoff — 2026-11-01

The owner has paused Copilot usage because the monthly allowance is exhausted
and authorized Codex to finish applicable work in both repositories and the Mac
editor using tested direct commits and normal pushes to `origin/main`, without
new PRs. This supersedes the earlier Copilot-only and draft-PR delivery rules.
It does not authorize hardware operation or changes to branch/security policy.

## Delivery procedure

1. Fetch both repositories and preserve the original dirty/frozen investigation
   checkouts. Integrate existing draft commits in separate clean worktrees.
2. Repair the known review findings with failed-before/passed-after host tests:
   client offline/handshake expiry, held-volume cleanup and socket status;
   policy allowlists, optional PyYAML discovery and scoped editor instructions;
   private receiver-profile packaging; receiver handshake replay, BLE reply
   correlation, tick-based limiting and refusal of remote reset while USB is up.
3. Regenerate changed firmware modules with the pinned compiler. Run host tests,
   static/security checks, dependency audits and exact paired badge/test parity.
4. Commit and push normally, rechecking remote ancestry first. Never force-push,
   change rules or fabricate a review approval. If push is rejected, retain the
   commits and report the rejection. No new PR or paid AI request is needed.
5. Verify remote containment and report the checks at that revision. Existing
   draft discussion remains historical evidence; closure is not physical approval.

## Ownership and automation

The active Copilot assignment on Universe #10 and the four scheduled-improvement
issues in BM83 were removed while preserving human ownership. The reliability
issues #190–#195 remain human-owned and open. The two weekly AI workflows are
retired so they cannot create more sessions or PRs. Security scans, ordinary
host CI and dependency alerting remain. No stored secret or permission changed.

Mac editor changes are local preferences, not repository configuration: Todo
Tree uses a verified installed ripgrep, and the unused localhost LLM gateway is
disabled while retaining its installation/settings. Private backups and live
verification evidence are kept outside Git. Model extension activation is not
an AI backend response test; Copilot requests are intentionally paused.

## Explicit remaining gates

- **Hardware reliability:** no devices, serial ports, device disks, radio probes,
  Music/helper controls, resets or deployments are part of this maintenance.
  Keep BM83/CrowPanel offline. The original and receiver observations in the
  runbook are incomplete or failed evidence, not acceptance. Preserve all frozen
  native candidates and private captures. The host changes are uninstalled.
- **Receiver admission:** replay memory is bounded to 512 bytes and 64 unique
  HELLO nonces per activation. It fails closed for additional new sessions at
  capacity; established clients, retries and required releases continue. A local
  restart is required to admit more sessions. This is a host-tested candidate,
  not a deployed or physically accepted protocol change.
- **Native build dependencies:** four open cryptography advisories affect the
  frozen host-build recipe. All fixes require cryptography 50.0.0, while its
  pinned ESP-IDF constraint requires `<46.1`. A pin-only upgrade is unsatisfiable.
  Keep alerts visible; issue #193 must validate compatible updated constraints
  and reproducible native builds in a separate isolated experiment before
  replacing frozen pins or artifacts. This is not proof of native fault cause.
- **Phase 1 acceptance:** requires the separately authorized run card, measured
  latency budgets, fresh-only status and at least 30 uninterrupted stable minutes
  plus actual screens/buttons/reconnect checks. Unit tests do not close it.
- **Phase 2 BLE HID Disconnect:** remains blocked by actual Phase 1 acceptance.
  No new firmware feature, bond change or cross-platform physical claim is made.

The full work graph and evidence classifications remain in
[the reliability runbook](README.md). Universe retains the matching badge add-on
and host tests; its offline validation must not be described as real radio or
physical display verification.

## Offline validation at delivery

- BM83: 1,294 tests and 116 subtests passed, including the enabled real-compiler
  test (no skipped compiler gate); pinned mpy-cross 10.3.1 build passed.
- Universe: 272 tests passed; all seven badge app files and three shared test
  files match the BM83 add-on exactly. HYB26 validation reports zero warnings.
- Policy suites pass (16 BM83, 15 Universe); clean no-PyYAML discovery skips are
  verified. Retired workflow filenames cannot reserve exemptions.
- Strict CI lint, production Bandit analysis and whitespace checks pass. Audits
  of development/MCP/map dependencies report no known vulnerabilities. This
  does not include the frozen native-build manifest's four alerts above.
- Python/Node loopback smoke checks, offline geography catalog and iOS export
  reproduction pass. Pinned HYB26 tooling tests: 68 tests, two expected skips.
- Independent final source review found no new actionable regression. The 39
  files in the pre-existing private frozen manifest remain hash-identical.

No runtime/native images were installed. These counts are host validation and
are deliberately separate from physical acceptance or backend AI connectivity.

## Existing dependency proposals

The remaining host-only proposals are integrated directly: the repo-health MCP
requirement is pinned to 2.3.0 (#185), and Codacy SARIF upload uses the verified
full commit for CodeQL action 4.39.1 (#186). No new PR is needed. Frozen native
build proposals #183, #196 and #197 remain unmerged for the isolated compatibility
and reproducibility work in #193. Existing Dependabot automation may open such
proposals independently; alerting and security settings have not been disabled.

The repo-health registration also uses a portable Node launcher selecting the
checkout's `.venv`, replacing bare `python` (unavailable in the Mac's clean PATH).
Only command/args changed; existing servers, environment and permissions were
preserved. Both direct-venv and exact registered-command stdio initialization
listed the same six tools with unchanged read-only annotations, without tool
execution, AI requests or hardware access. Four launcher fixtures cover missing
venv, inherited stdio/exit status, paths with spaces and platform-specific layout.

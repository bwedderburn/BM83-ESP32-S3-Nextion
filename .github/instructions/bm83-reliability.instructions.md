---
applyTo: "firmware/circuitpython/**,addons/universe-badge/**,tests/**,.github/instructions/bm83-reliability.instructions.md,.github/agents/reliability-*.agent.md,.github/ISSUE_TEMPLATE/reliability.yml,.github/skills/extensive-review/**,.github/workflows/host-security.yml,.vscode/tasks.json,docs/reliability/**,scripts/check_reliability_setup.py,requirements-reliability.txt"
---

# Verified reliability

Read `docs/reliability/README.md` before proposing runtime work. Codex owns local
implementation and review while Copilot is unavailable. Run the relevant offline
checks, then use ordinary direct commits and pushes to `origin/main` as authorized
by the user; do not create PRs or Copilot jobs. Do not force-push or change
repository policy, security settings, account, billing, approvals or MCP permissions.

Host candidates are frozen, not approved for deployment. Do not open serial,
mounted devices, Bluetooth, Music, helpers or SSH during repository validation.
An issue, plan, green CI or automated answer is not hardware authorization.
Preserve profiles, bonds, keys, unrelated apps and all private rollback evidence.

Separate source proof, host tests, fresh hardware observations, user reports and
hypotheses. Audio, UART ACKs and cached snapshots do not prove fresh metadata or
controller health. The 582.4-second original observation stopped on an intentional
user volume change, not a proven fault; physical acceptance is unconfirmed.

Derive latency budgets from original measurements and protocol/buffer deadlines;
candidate thresholds are not acceptance criteria. Report unsupported native
counters as unavailable, not zero. Review crypto finalization and socket/native
ownership without assuming Python heap proves native resource health.

Keep the canonical add-on and Universe app plus three mirrored tests identical.
Do not include frozen runtime experiments in tooling-only commits. Publish only
sanitized aggregates. Source-only commits do not establish physical acceptance.
Hardware access and deployment remain blocked until explicitly authorized.
Physical acceptance still requires >=30-minute stable soak, power/reconnect,
screens/buttons, HOME and a platform matrix. Phase 2 BLE Disconnect stays blocked.

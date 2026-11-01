---
applyTo: "firmware/circuitpython/**,addons/universe-badge/**,tests/**,.github/**,.vscode/**,docs/reliability/**,scripts/check_reliability_setup.py"
---

# Verified reliability

Read `docs/reliability/README.md` before proposing runtime work. This initiative
uses GitHub Copilot locally, with GPT review profiles; no Claude or cloud coding
jobs. Keep existing account, billing, approval modes and MCP permissions.

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
sanitized aggregates. Keep both implementation PRs draft until explicit physical
acceptance, including >=30-minute stable soak, power/reconnect, screens/buttons,
HOME and a platform matrix. Phase 2 BLE Disconnect stays blocked.

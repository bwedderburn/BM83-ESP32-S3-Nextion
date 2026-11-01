# Local Copilot review setup

Use the [verified reliability runbook](../reliability/README.md) for current
instructions, evidence, host commands and physical acceptance gates.

Open the intended source checkout in VS Code using the existing signed-in GitHub
Copilot account. Select its `.venv` interpreter and explicitly choose one of:

- **Reliability runtime review**: protocol deadlines, native ownership,
  authentication/replay and metadata freshness.
- **Reliability delivery review**: CI safety, evidence, rollback gates and status UX.

Both profiles request GPT-5.3-Codex and expose only read/search tools. If the model
or profile is unavailable, report the blocker rather than selecting Claude or
launching a cloud coding job. Availability must be checked in the actual picker;
parsing a file does not establish it.

Keep normal approvals, account, billing, MCP permissions and existing credentials
unchanged. This setup requires no new token, cloud-agent assignment, firewall
exception or secret. Do not run private device/capture tools from review sessions.

The old weekly Claude audit and automatic cloud-coding assignment workflows are
removed in this draft. Their historical setup remains in Git history, not in the
active runbook. **Unmerged source changes do not disable default-branch schedules.**
Do not dispatch them. This task does not alter their remote enabled state or any
stored secrets. The retained `copilot-setup-steps.yml` only prepares dependencies;
running an ordinary setup check does not launch a coding agent.

Run only explicit host checks under the `BM83:` VS Code tasks. Independent review
and green CI do not replace actual hardware acceptance. Keep both implementation
PRs draft and Phase 2 blocked.

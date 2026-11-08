# Local review and validation setup

Current maintenance uses Codex with direct commits and normal pushes to
`origin/main`, as authorized by the owner. Copilot's monthly allowance is
exhausted; do not launch Copilot queries, reviews, assignments or cloud jobs.
Do not create PRs, force-push, or change protected-branch rules to deliver work.
See [the maintenance handoff](../reliability/DIRECT-MAINTENANCE.md) and
[the reliability runbook](../reliability/README.md).

The weekly Copilot issue-rotation and Claude audit workflows have been removed.
Their setup and secret-provisioning instructions are retired with them; Git
history retains the old configuration. No stored credential was read or changed.
The existing Codacy security scan is retained for push/schedule analysis. Its
explicit validator exemption does not exempt future files with retired names.
The optional `copilot-setup-steps.yml` prepares dependencies on explicit dispatch
and does not launch a model or create a coding-agent assignment.

## Host-only tools

Select the checkout's `.venv` interpreter in VS Code. Install the pinned
`requirements-reliability.txt` and invoke only the relevant `BM83:` tasks.
For the repo-health MCP server, also install
`tools/mcp/repo_health/requirements.txt` with that `.venv` Python. The registration
uses `node tools/mcp/repo_health/launch.mjs`, which selects this checkout's
`.venv/bin/python` on Mac/Linux or `.venv/Scripts/python.exe` on Windows, with
inherited stdio. It never falls back to a global Python or installs packages.
Node must be in the client's PATH; missing `.venv` produces explicit setup help.
No shell activation or new credential is needed. Host fixtures exercise the
platform layouts; only the Mac command has a live protocol handshake here.
No task runs at folder open or deploys firmware. Keep approval settings, account,
billing, credentials, MCP permissions and folder trust unchanged. Never start
private device/capture tools from a repository review.

The two `.github/agents/reliability-*.agent.md` profiles are preserved, explicitly
invoked, read/search only and omit a model pin. Their presence is not evidence of
an executed review. Future Copilot use needs an available allowance and owner
instruction. The manual extensive-review skill and repo-health MCP configuration
are retained; `repo_test_summary` executes tests and writes caches, so it is not
a read-only tool. No wildcard permission grant is required by this maintenance.

Offline tests and repository integration do not satisfy physical acceptance.
Keep BM83 and CrowPanel offline during repository maintenance; the
[November 4 B-Intel run](../reliability/phase1-bintel-2026-11-04.md) was
accepted for its agreed Phase 1 scope, so Phase 2 Disconnect + Select host
source work may proceed with its own build, host-selection matrix, qualified
timing-window and physical acceptance gates, and this grants no new device
authorization.

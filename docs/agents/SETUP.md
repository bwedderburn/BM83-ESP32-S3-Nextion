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
Keep BM83 and CrowPanel offline and Phase 2 blocked until the separately
authorized hardware protocol passes.

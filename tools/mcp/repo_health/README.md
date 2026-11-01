# repo_health_mcp

Read-only MCP server that hands coding agents the repo-health facts they
otherwise re-derive every session: inventory, TODO debt, churn hotspots,
dependency/toolchain versions, and test/lint status.

## Read-only guarantee

Every tool except `repo_test_summary` is read-only and carries
`readOnlyHint: true` — that subset is safe for Copilot code review as well as
the coding agent. The exception: `repo_test_summary` executes the
repository's test code and lets pytest write its caches, so it is not marked
read-only and must be left out of any code-review tool set (coding-agent use
is fine). `repo_lint_summary` only reads sources.

## Tools

| Tool | What it returns |
|---|---|
| `repo_inventory` | LOC by extension, largest files, firmware module list |
| `repo_todo_scan` | TODO/FIXME/HACK/XXX/WATCH markers with file:line |
| `repo_churn_hotspots` | most-changed files over N days (defect-risk ranking) |
| `repo_dependency_report` | CI Python matrix, action versions, pip pins, CircuitPython refs |
| `repo_test_summary` | pytest run tail (host suite) — **not read-only**: runs repo test code, writes caches |
| `repo_lint_summary` | both CI flake8 passes (strict + style/complexity) |

## Install & run locally

On Mac/Linux, from the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r tools/mcp/repo_health/requirements.txt
node tools/mcp/repo_health/launch.mjs
```

On Windows use `py -3 -m venv .venv`,
`.venv\Scripts\python.exe -m pip install --upgrade pip`, and
`.venv\Scripts\python.exe -m pip install -r tools/mcp/repo_health/requirements.txt`,
then run the same Node command. Node must be in the MCP client's PATH. The
launcher chooses only this checkout's `.venv` Python and fixed `server.py`,
forwards stdio/exit status, and gives setup help instead of using a global Python
when `.venv` is absent. No shell activation, package auto-install or model call
is part of startup. Current maintenance pauses Copilot usage; see
[the handoff](../../../docs/reliability/DIRECT-MAINTENANCE.md).

The server resolves the repo root via `git rev-parse` (override with the
`REPO_HEALTH_ROOT` environment variable).

## Where it is registered

- **Copilot CLI, GitHub Copilot app, VS Code Copilot harness and Claude Code**:
  `.mcp.json` at the repo root (portable `mcpServers` format, repo-relative
  path, no secrets). The deprecated duplicate `.vscode/mcp.json` entry was
  migrated here and removed.
- **Copilot coding agent (github.com)**: paste
  `docs/agents/copilot-coding-agent-mcp.json` into
  *Repo Settings → Copilot → Coding agent → MCP configuration*. The
  `copilot-setup-steps` workflow preinstalls the `mcp` dependency for it.

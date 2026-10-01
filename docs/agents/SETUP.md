# Agent automation — setup & operations

One-time setup for the extensive-review prompt, the repo-health MCP server, and the two
weekly improvement workflows. Everything here was added in the `chore/weekly-agent-automation`
PR; this file is the runbook.

## What was added

| Path | Purpose |
|---|---|
| `.github/prompts/extensive-review.prompt.md` | The full code-review & modernization brief (VS Code `/extensive-review`, Copilot coding agent, or Claude Code) |
| `.github/copilot-instructions.md` | + Behavioral Contracts & automation conventions sections |
| `.github/workflows/copilot-setup-steps.yml` | Preinstalls flake8/pytest/bandit + MCP deps in Copilot coding agent sessions |
| `.github/workflows/weekly-copilot-review.yml` | Mondays: focused issue (deps→robustness→quality→tests rotation) auto-assigned to Copilot |
| `.github/agent-tasks/weekly-copilot-body.md` | Issue body template for the Monday task |
| `.github/workflows/weekly-claude-audit.yml` | Thursdays: Claude Code dependency/upgrade audit → report + safe-fix PR + issues |
| `.github/dependabot.yml` | + pip ecosystem for the MCP server |
| `tools/mcp/repo_health/` | Read-only repo-health MCP server (inventory, TODOs, churn, deps, test/lint) |
| `.mcp.json`, `.vscode/mcp.json` | MCP registration for Claude Code and VS Code agent mode |
| `docs/agents/copilot-coding-agent-mcp.json` | MCP config to paste into repo settings (coding agent) |

## One-time setup (after merging the PR)

### 1. Repo secrets

**`GH_AGENT_PAT`** — lets the Monday workflow auto-assign Copilot, and lets the Thursday
audit open its PR as you (so CI triggers on it). Create a fine-grained PAT at
github.com → Settings → Developer settings → Fine-grained tokens, scoped to
`bwedderburn/BM83-ESP32-S3-Nextion`, with **Read: metadata** and **Read + Write: actions,
contents, issues, pull requests** (the permission set GitHub documents for Copilot issue
assignment). Then:

shell (PowerShell, B-Intel)
```
gh secret set GH_AGENT_PAT --repo bwedderburn/BM83-ESP32-S3-Nextion
```
(paste the token when prompted)

**`CLAUDE_CODE_OAUTH_TOKEN`** — authenticates the Thursday audit against your Claude
subscription. Generate it with Claude Code, then store it:

shell (PowerShell, B-Intel)
```
claude setup-token
```

shell (PowerShell, B-Intel)
```
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo bwedderburn/BM83-ESP32-S3-Nextion
```

Prefer API billing instead? Set `ANTHROPIC_API_KEY` as the secret and swap the one commented
input line in `weekly-claude-audit.yml`.

### 2. Register the MCP server with the Copilot coding agent

Repo → **Settings → Copilot → Coding agent → MCP configuration** (shown as "MCP servers" in
some UI versions) → paste the contents of `docs/agents/copilot-coding-agent-mcp.json` → save.
The coding agent's firewall and setup steps handle the rest; `copilot-setup-steps.yml`
preinstalls the `mcp` package it needs.

Claude Code and VS Code need nothing — `.mcp.json` and `.vscode/mcp.json` are picked up from
the repo automatically (VS Code will ask once to trust/start the server).

### 3. Validate copilot-setup-steps

The workflow only takes effect from the default branch. After merge:
Actions tab → "Copilot Setup Steps" → Run workflow. Green run = agent sessions get the
toolchain.

### 4. Optional but recommended (Copilot Pro+)

Repo → Settings → Rules (or Branches) → enable **automatic Copilot code review** on pull
requests, so every agent PR gets reviewed without you re-requesting. Your existing
re-request loop (`pulls/N/requested_reviewers` with `copilot-pull-request-reviewer[bot]`)
keeps working for iterations.

## What runs when

| When (Pacific) | What | Output |
|---|---|---|
| Mon ~06:17/07:17 | `weekly-copilot-review.yml` | Issue (label `agent:weekly`) → Copilot session → PR |
| Mon 07:32/08:32 | Codacy scan (pre-existing) | SARIF to code scanning |
| Thu ~06:47/07:47 | `weekly-claude-audit.yml` | `docs/weekly-audit/<date>.md` + PR + `code-health` issues |
| Weekly | Dependabot | Action + pip bump PRs |

Both weekly workflows also support **Run workflow** (workflow_dispatch) from the Actions tab;
the Monday one takes a `focus` override (`deps|robustness|quality|tests`). Merges stay gated
by your existing rules: branch protection, the Python matrix, Copilot/Codex review, and the
hardware-test verdict for anything touching firmware behavior (agents are instructed not to
touch firmware behavior at all).

## Kicking off the one-time extensive review

Three equivalent ways to run `.github/prompts/extensive-review.prompt.md` — pick per session:

1. **Copilot coding agent** (uses Pro+ premium requests): open a new issue titled
   "Extensive code review & modernization audit", body:
   "Read `.github/prompts/extensive-review.prompt.md` and execute it fully, all phases." —
   then assign **Copilot** in the issue sidebar (works from GitHub mobile). Do this *after*
   merging the automation PR so the prompt, MCP server and setup steps are on `main`.
2. **VS Code agent mode**: open the repo, Copilot Chat → type `/extensive-review`, pick a
   Claude model in the model picker (Copilot's built-in Claude, or your BYOK Anthropic key's
   models), let it run in agent mode.
3. **Claude Code in the cloud** (spends the $250 cloud allowance): start a session at
   claude.ai/code on the GitHub repo and prompt:
   "Read .github/prompts/extensive-review.prompt.md and execute it fully, all phases."

## Which credential pays for what (as of 2026-10)

| Resource | Covers | Does NOT cover |
|---|---|---|
| Copilot Pro+ premium requests | Coding agent sessions, Copilot code review, Copilot Chat | Claude Code anything |
| BYOK Anthropic key (VS Code "Manage models") | Model choice in VS Code Copilot Chat | Coding agent on github.com, Copilot code review, Actions |
| $250 Claude Code cloud allowance | Claude Code sessions on claude.ai/code (cloud) | The `weekly-claude-audit` Action |
| `CLAUDE_CODE_OAUTH_TOKEN` (subscription) / `ANTHROPIC_API_KEY` | The `weekly-claude-audit` Action | — |

## Levers

- **Cadence**: edit the `cron:` lines (times are UTC; currently Mon 14:17 / Thu 14:47).
- **Pause one bot**:

shell (PowerShell, B-Intel)
```
gh workflow disable "Weekly code improvement (Copilot)" --repo bwedderburn/BM83-ESP32-S3-Nextion
```

- **Scope**: the Monday issue body lives in `.github/agent-tasks/weekly-copilot-body.md`;
  the Thursday brief is the `prompt:` block in `weekly-claude-audit.yml`; the deep-review
  method is `.github/prompts/extensive-review.prompt.md`.

## Troubleshooting

- **Issue created, Copilot never started** — `GH_AGENT_PAT` missing/expired (workflow log
  will show the fallback comment), or the coding agent is disabled for the repo
  (Settings → Copilot). Assigning Copilot by hand in the issue sidebar always works.
- **Claude job fails at auth** — `CLAUDE_CODE_OAUTH_TOKEN` missing/expired; rerun
  `claude setup-token` and reset the secret.
- **repo-health tools missing in a Copilot session** — MCP JSON not saved in repo settings,
  or `copilot-setup-steps` hasn't run green from `main` yet (the `mcp` package would be
  missing). Session logs show MCP server startup under the session's "Copilot" step.
- **CI didn't run on the Thursday audit PR** — the run fell back to `github.token`
  (PRs created with it don't trigger workflows). Set `GH_AGENT_PAT`, or close/reopen the PR.
- **3.9 matrix questions** — 3.9 is EOL; the first `deps`-focus runs will propose the matrix
  bump as a CI diff for you to apply (agents don't edit workflows here).

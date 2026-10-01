## Weekly code improvement — focus: {{FOCUS}}

You are the Copilot coding agent on your weekly improvement pass for this repo.
**Apply only the "{{FOCUS}}" scope section below.** The other sections are listed so you
know what is deliberately out of scope this week.

### Scope: deps — dependencies & toolchain

- Compare current vs latest: GitHub Actions majors across workflows, the Python CI matrix
  (3.9 is past EOL), dev tools (flake8/pytest/bandit), the latest CircuitPython 10.x release
  notes (ESP32-S3 / UART / BLE relevance), and the mpy-cross "latest-grab" in the dist build.
- Put the resulting upgrade matrix (Component | Current | Latest | Risk | Recommendation) in
  the PR description.
- Apply only non-workflow, host-verifiable follow-ups: docs updates, version pins in
  `tools/mcp/repo_health/requirements.txt`, removal of proven-dead compat shims.
- Run the advisory-database check on any pinned version you touch.

### Scope: robustness — protocol & parsing audit (audit-only)

- Audit parsing paths in `firmware/circuitpython/lib/` (bm83 framing/checksum resync,
  Nextion token parser under partial/garbage input, `_sanitize_text` coverage) for
  host-provable weaknesses. Do NOT change firmware code in this scope — parser
  hardening is behavioral and stays behind the hardware gate.
- For each weakness found, file one `code-health` issue containing a failing-test
  sketch that demonstrates the defect and your proposed diff.
- This week's PR carries only the audit notes (and, at most, new tests that pin
  CURRENT behavior without touching firmware).

### Scope: quality — maintainability

- Dead code (with proof it is unreachable), duplicated protocol constants/logic, missing
  docstrings on public helpers, flake8 max-complexity offenders (decompose only with tests
  covering the extracted pieces), TODO/FIXME triage into `code-health` issues.

### Scope: tests — coverage gaps

- Close the highest-risk host-test gaps: power-state contract edges, AUX boot-window
  heuristic, link-state demotion rules, parser fuzz breadth, metadata re-request backoff.
- Host-only and deterministic; no hardware, no sleeps, no timing races.

### Binding rules (every week)

- Read `.github/copilot-instructions.md` — including **Behavioral Contracts** — and
  `CLAUDE.md` before touching anything. Do not re-litigate a listed contract.
- The full review method lives in `.github/prompts/extensive-review.prompt.md`; this issue is
  one focused slice of it.
- One PR, at most ~300 changed lines, host-verifiable only. flake8 strict pass and pytest
  fully green before you finish.
- **No firmware behavior changes.** Anything touching protocol/state-machine behavior becomes
  a `code-health` issue containing your proposed diff instead of a commit.
- `dist/` is generated (never hand-edit); `.github/workflows/` and `Documents/` are
  read-only — propose CI diffs in the PR description instead of editing workflows.
- If `firmware/circuitpython/lib/` changes, note in the PR that `build_mpy.sh` must be rerun.
- If nothing worthwhile exists in scope this week, comment briefly and close this issue —
  do not invent work.

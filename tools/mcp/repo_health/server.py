#!/usr/bin/env python3
"""repo_health_mcp — read-only code-health MCP server for BM83-ESP32-S3-Nextion.

Gives coding agents (Copilot coding agent, Claude Code, VS Code agent mode)
structured, cheap access to the repo-health facts they otherwise burn turns
rediscovering: inventory, TODO debt, churn hotspots, dependency/toolchain
versions, and test/lint status.

Every tool except repo_test_summary is read-only with respect to the working
tree and carries readOnlyHint, so that subset is safe to expose to Copilot
code review. repo_test_summary executes the repository's test code and lets
pytest write its caches, so it is NOT marked read-only — keep it out of any
code-review tool set (see README, "Read-only guarantee").

Run:  python tools/mcp/repo_health/server.py   (stdio transport)
Deps: pip install -r tools/mcp/repo_health/requirements.txt
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # mcp 2.x renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP

mcp = FastMCP("repo_health_mcp")

# --- Repo root resolution ----------------------------------------------------

SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", "dist",
    "recovered_src", "Documents", ".snapshots", "node_modules",
    "pytest-cache-files-fz3be7jp", ".codex", "egg-info",
}
SOURCE_EXTS = {".py", ".md", ".yml", ".yaml", ".sh", ".toml", ".ini", ".json", ".cfg"}
TODO_MARKERS = ("TODO", "FIXME", "HACK", "XXX", "WATCH")
# Only comment/task syntax counts as debt — prose that merely discusses the
# scan (docs, prompts, this constant) must not match.
_MARKER_ALT = "|".join(TODO_MARKERS)
TODO_IN_COMMENT = re.compile(r"(?:#|//|<!--)\s*(?:%s)\b" % _MARKER_ALT)
TODO_TASK_LINE = re.compile(r"^\s*(?:[-*>]\s*)?(?:\[.\]\s*)?(?:%s)[:(]" % _MARKER_ALT)
OUTPUT_CAP = 6000  # chars, keep tool results context-friendly


def _repo_root() -> Path:
    env = os.environ.get("REPO_HEALTH_ROOT")
    if env and Path(env).is_dir():
        return Path(env).resolve()
    out = _run(["git", "rev-parse", "--show-toplevel"], timeout=10)
    if out["code"] == 0 and out["stdout"].strip():
        return Path(out["stdout"].strip()).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return Path.cwd()


def _run(cmd: list[str], timeout: int = 60, cwd: Path | None = None) -> dict:
    """Run a subprocess safely; never raises, always returns code/stdout/stderr."""
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, capture_output=True,
            text=True, errors="replace", timeout=timeout,
        )
        return {"code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    except FileNotFoundError:
        return {"code": 127, "stdout": "", "stderr": f"not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return {"code": 124, "stdout": "", "stderr": f"timeout after {timeout}s: {' '.join(cmd)}"}


def _iter_source_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SOURCE_EXTS:
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in rel.parts):
            continue
        yield path, rel


def _cap(text: str) -> str:
    """Character cap for PLAIN-TEXT tool output only — never JSON."""
    if len(text) <= OUTPUT_CAP:
        return text
    return text[:OUTPUT_CAP] + f"\n... [truncated at {OUTPUT_CAP} chars]"


def _json(data: dict) -> str:
    """Serialize to JSON, truncating structurally so output is ALWAYS valid JSON.

    Oversized results shrink their largest top-level list (halving until the
    dump fits OUTPUT_CAP) and gain "truncated": true plus kept/total counts —
    never a mid-string character cut.
    """
    def dump(d: dict) -> str:
        return json.dumps(d, indent=2, ensure_ascii=False)

    text = dump(data)
    if len(text) <= OUTPUT_CAP:
        return text
    data = dict(data)
    totals = {k: len(v) for k, v in data.items() if isinstance(v, list)}
    while len(text) > OUTPUT_CAP:
        lists = [(k, v) for k, v in data.items() if isinstance(v, list) and len(v) > 1]
        if not lists:
            break  # nothing left to shrink; valid JSON beats the size cap
        key = max(lists, key=lambda kv: len(dump({kv[0]: kv[1]})))[0]
        data[key] = data[key][: max(1, len(data[key]) // 2)]
        data["truncated"] = True
        data["kept"] = {k: f"{len(data[k])} of {totals[k]}" for k in totals}
        text = dump(data)
    return text


ROOT = _repo_root()

# --- Tools --------------------------------------------------------------------


@mcp.tool(
    name="repo_inventory",
    annotations={
        "title": "Repo Inventory", "readOnlyHint": True,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": False,
    },
)
def repo_inventory(top_n: int = 15) -> str:
    """Summarize the repository: line counts by extension, the largest source
    files, and the firmware module layout.

    Args:
        top_n: how many of the largest files to list (1-50, default 15).

    Returns:
        JSON: {"root", "loc_by_ext": {ext: lines}, "files_by_ext": {ext: n},
               "largest_files": [{"path", "lines"}], "firmware_modules": [paths]}
    """
    top_n = max(1, min(int(top_n), 50))
    loc, nfiles, sizes = Counter(), Counter(), []
    for path, rel in _iter_source_files(ROOT):
        try:
            lines = sum(1 for _ in path.open("r", encoding="utf-8", errors="replace"))
        except OSError:
            continue
        loc[path.suffix] += lines
        nfiles[path.suffix] += 1
        sizes.append((lines, str(rel).replace(os.sep, "/")))
    sizes.sort(reverse=True)
    fw = ROOT / "firmware" / "circuitpython"
    modules = []
    if fw.is_dir():
        modules = [
            str(p.relative_to(ROOT)).replace(os.sep, "/")
            for p in sorted(fw.rglob("*.py"))
            if "__pycache__" not in p.parts and "egg-info" not in str(p)
        ]
    return _json({
        "root": str(ROOT),
        "loc_by_ext": dict(loc.most_common()),
        "files_by_ext": dict(nfiles.most_common()),
        "largest_files": [{"path": p, "lines": n} for n, p in sizes[:top_n]],
        "firmware_modules": modules,
    })


@mcp.tool(
    name="repo_todo_scan",
    annotations={
        "title": "TODO/FIXME Scan", "readOnlyHint": True,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": False,
    },
)
def repo_todo_scan() -> str:
    """Find TODO / FIXME / HACK / XXX / WATCH markers written as comment or
    task syntax — the marker directly after a comment leader (hash, //, or
    <!--) or opening a checkbox/task line. Prose that merely mentions the
    words — docs, prompts, and this docstring — is ignored, as are vendor
    docs, dist/, recovered_src/ and caches.

    Returns:
        JSON: {"count", "markers": [{"path", "line", "text"}]} — text trimmed
        to 160 chars per hit.
    """
    hits = []
    for path, rel in _iter_source_files(ROOT):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, 1):
                    if TODO_IN_COMMENT.search(line) or TODO_TASK_LINE.match(line):
                        hits.append({
                            "path": str(rel).replace(os.sep, "/"),
                            "line": lineno,
                            "text": line.strip()[:160],
                        })
        except OSError:
            continue
    return _json({"count": len(hits), "markers": hits})


@mcp.tool(
    name="repo_churn_hotspots",
    annotations={
        "title": "Git Churn Hotspots", "readOnlyHint": True,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": False,
    },
)
def repo_churn_hotspots(days: int = 180, top_n: int = 20) -> str:
    """Rank files by how often they changed recently — churn correlates with
    defect risk and tells a reviewer where to look first.

    Args:
        days: history window in days (1-3650, default 180).
        top_n: how many files to return (1-100, default 20).

    Returns:
        JSON: {"window_days", "commits", "hotspots": [{"path", "changes"}]}
        or an error string if git history is unavailable.
    """
    days = max(1, min(int(days), 3650))
    top_n = max(1, min(int(top_n), 100))
    out = _run(["git", "log", f"--since={days}.days", "--name-only",
                "--pretty=format:--%h"], timeout=60, cwd=ROOT)
    if out["code"] != 0:
        return f"Error: git log failed: {out['stderr'].strip() or out['code']}"
    commits, counts = 0, Counter()
    for line in out["stdout"].splitlines():
        line = line.strip()
        if line.startswith("--"):
            commits += 1
        elif line and not any(part in SKIP_DIRS for part in line.split("/")):
            counts[line] += 1
    return _json({
        "window_days": days,
        "commits": commits,
        "hotspots": [{"path": p, "changes": c} for p, c in counts.most_common(top_n)],
    })


@mcp.tool(
    name="repo_dependency_report",
    annotations={
        "title": "Dependency & Toolchain Report", "readOnlyHint": True,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": False,
    },
)
def repo_dependency_report() -> str:
    """Report everything version-shaped in the repo so an agent can diff it
    against latest upstream: CI Python matrix, GitHub Actions versions, pip
    pins, and CircuitPython version references in docs.

    Returns:
        JSON: {"python_matrix", "actions": {workflow: [uses...]},
               "pip_requirements": {file: [lines]}, "circuitpython_refs",
               "notes"} — compare these against latest releases yourself.
    """
    report: dict = {"python_matrix": [], "actions": {}, "pip_requirements": {},
                    "circuitpython_refs": [], "notes": []}
    wf_dir = ROOT / ".github" / "workflows"
    if wf_dir.is_dir():
        for wf in sorted(wf_dir.glob("*.yml")):
            text = wf.read_text(encoding="utf-8", errors="replace")
            uses = sorted(set(re.findall(r"uses:\s*([^\s#]+)", text)))
            report["actions"][wf.name] = uses
            report["python_matrix"] += re.findall(r'"(3\.\d{1,2})"', text)
    report["python_matrix"] = sorted(set(report["python_matrix"]))
    for req in sorted(ROOT.rglob("requirements*.txt")):
        rel = req.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        lines = [ln.strip() for ln in req.read_text(encoding="utf-8", errors="replace").splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
        report["pip_requirements"][str(rel).replace(os.sep, "/")] = lines
    cp_pat = re.compile(r"[Cc]ircuit[Pp]ython[^\n]{0,40}?(\d+\.\d+(?:\.\d+)?)")
    for name in ("README.md", "DEPLOYMENT.md", "CLAUDE.md", "CODE_REFERENCE.md"):
        f = ROOT / name
        if f.exists():
            for ver in sorted(set(cp_pat.findall(f.read_text(encoding="utf-8", errors="replace")))):
                report["circuitpython_refs"].append({"file": name, "version": ver})
    report["notes"] = [
        "Dev tools (flake8/pytest/bandit) are installed unpinned in CI — resolve 'current' with pip index/PyPI.",
        "mpy-cross is pinned (version + sha256) in tools/mpy_cross_pin.env; it must match the device's CircuitPython.",
        "Python 3.9 reached end-of-life in October 2025.",
    ]
    return _json(report)


@mcp.tool(
    name="repo_test_summary",
    annotations={
        "title": "Run Pytest (summary)", "readOnlyHint": False,
        "destructiveHint": False, "idempotentHint": False, "openWorldHint": False,
    },
)
def repo_test_summary(extra_args: str = "") -> str:
    """Run the host-only pytest suite and return the tail of its output.
    NOT read-only: executes repository test code and lets pytest write its
    caches — keep this tool out of any code-review tool set (see README).
    Requires pytest installed (copilot-setup-steps preinstalls it).

    Args:
        extra_args: optional pytest args, whitespace-separated. Allowed: -k /
                    -m with a following expression word, -x, -q, --maxfail=N,
                    and relative test paths / node ids. Every other option is
                    rejected — options like --basetemp can delete directories.

    Returns:
        Last ~60 lines of pytest output (pass/fail summary included), or an
        "Error: disallowed pytest argument ..." message without running.
    """
    allowed_flags = {"-k", "-m", "-x", "-q"}
    args: list[str] = []
    for tok in extra_args.split():
        if tok in allowed_flags or re.fullmatch(r"--maxfail=\d+", tok):
            args.append(tok)
        elif (not tok.startswith("-") and not tok.startswith("/")
              and ".." not in tok and not re.match(r"^[A-Za-z]:", tok)
              and re.fullmatch(r"[\w./:=\[\]-]+", tok)):
            args.append(tok)  # -k/-m expression word, test path, or node id
        else:
            return (f"Error: disallowed pytest argument {tok!r} — allowed: "
                    "-k/-m <expression>, -x, -q, --maxfail=N, and relative "
                    "test paths or node ids.")
    out = _run([sys.executable, "-m", "pytest", "-q", *args], timeout=600, cwd=ROOT)
    tail = "\n".join((out["stdout"] + "\n" + out["stderr"]).strip().splitlines()[-60:])
    return _cap(f"exit code: {out['code']}\n{tail}")


@mcp.tool(
    name="repo_lint_summary",
    annotations={
        "title": "Run Flake8 (summary)", "readOnlyHint": True,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": False,
    },
)
def repo_lint_summary() -> str:
    """Run both CI flake8 passes (strict errors, then style/complexity) and
    return their tails. Requires flake8 installed.

    Returns:
        Both passes' exit codes with stdout AND stderr, so a failed flake8
        invocation is never reported as clean (style pass incl. C901
        complexity offenders).
    """
    strict = _run([sys.executable, "-m", "flake8", ".", "--count",
                   "--select=E9,F63,F7,F82", "--show-source", "--statistics"],
                  timeout=300, cwd=ROOT)
    style = _run([sys.executable, "-m", "flake8", ".", "--count", "--exit-zero",
                  "--max-complexity=10", "--max-line-length=127", "--statistics"],
                 timeout=300, cwd=ROOT)

    def _both(out: dict) -> str:
        err = out["stderr"].strip()
        return (out["stdout"].strip() + ("\n" + err if err else "")).strip()

    strict_text = _both(strict) or ("clean" if strict["code"] == 0 else "(no output)")
    style_tail = "\n".join(_both(style).splitlines()[-40:])
    return _cap(
        f"strict pass exit code: {strict['code']}\n{strict_text}\n"
        f"\nstyle pass exit code: {style['code']} (run with --exit-zero):\n{style_tail}"
    )


if __name__ == "__main__":
    mcp.run()

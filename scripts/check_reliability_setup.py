#!/usr/bin/env python3
"""Inspect reliability configuration structure and literals; never contact a device."""

import json
from pathlib import Path
import re
import shlex
import sys

import yaml


def step_errors(step):
    errors = []
    action = step.get("uses")
    if action and not re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", action):
        errors.append("action must be pinned to a full commit: " + action)
    if action and action.lower().startswith("actions/checkout@"):
        if step.get("with", {}).get("persist-credentials") is not False:
            errors.append("checkout must not persist credentials")
    return errors


OUT_OF_SCOPE = "# reliability-scope: out-of-scope legacy automation"
PR_EVENTS = ("pull_request", "pull_request_target", "workflow_run")
# Labeled unrelated automation may only run on these non-PR triggers.
OUT_OF_SCOPE_EVENTS = ("schedule", "workflow_dispatch", "push")
# Only the existing Codacy scanner is preserved. Retired automation names must
# not reserve exemptions for workflows that could be added in the future.
OUT_OF_SCOPE_WORKFLOWS = ("codacy.yml",)
REQUIRED_WORKFLOWS = ("python-package.yml", "host-security.yml", "codacy.yml")
PRODUCTION_BANDIT_TARGETS = frozenset({
    "firmware/circuitpython", "addons/universe-badge/apps/bm83_remote", "scripts",
})
EXPECTED_PRODUCTION_BANDIT_COMMAND = (
    "python -m bandit --ini .bandit -r "
    "firmware/circuitpython addons/universe-badge/apps/bm83_remote scripts -ll"
)


def is_out_of_scope(text, name):
    return text.startswith(OUT_OF_SCOPE) and name in OUT_OF_SCOPE_WORKFLOWS


def trigger_errors(data, text, name=""):
    # PyYAML's YAML 1.1 loader treats the GitHub key `on` as True.
    events = data.get("on", data.get(True, {}))
    if isinstance(events, str):
        events = [events]
    # Explicitly labeled unrelated automation is preserved, but never as a PR job.
    if is_out_of_scope(text, name):
        if not events or any(event not in OUT_OF_SCOPE_EVENTS for event in events):
            return ["out-of-scope workflow must not run on pull requests"]
        return []
    if any(event in events for event in ("pull_request_target", "workflow_run")):
        return ["privileged follow-up trigger"]
    return []


def decoded_strings(value):
    # YAML escapes such as \u0073 decode before GitHub evaluates expressions.
    if isinstance(value, dict):
        for key, item in value.items():
            yield from decoded_strings(key)
            yield from decoded_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from decoded_strings(item)
    elif isinstance(value, str):
        yield value


def run_strings(data):
    for job in data.get("jobs", {}).values():
        for step in job.get("steps", []):
            if isinstance(step.get("run"), str):
                yield step["run"]


def reference_errors(data, text):
    decoded = "\n".join([text, *decoded_strings(data)])
    commands = "\n".join([text, *run_strings(data)])
    errors = []
    for pattern, label, scanned in (
            (r"\bsecrets\b", "secrets", decoded),
            (r"anthropics/|@anthropic-ai/claude-code|agent_assignment|copilot-swe-agent",
             "separate/cloud agent", decoded),
            (r"(?:^|\brun:|[;&|])\s*(?:exec\s+)?claude\b", "separate Claude command", commands)):
        if re.search(pattern, scanned, re.IGNORECASE | re.MULTILINE):
            errors.append("forbidden credential/agent reference: " + label)
    return errors


def matches_production_bandit_args(args):
    """Recognize the expected literal argv layout, not general shell semantics."""
    return (args[:6] == ["python", "-m", "bandit", "--ini", ".bandit", "-r"]
            and len(args) == 7 + len(PRODUCTION_BANDIT_TARGETS)
            and args[-1] == "-ll"
            and set(args[6:-1]) == PRODUCTION_BANDIT_TARGETS)


def production_bandit_errors(data, name):
    """Check literal argv and declared skip/error flags; do not execute a workflow."""
    if name != "host-security.yml":
        return []
    job = data.get("jobs", {}).get("host-security", {})
    if job.get("if") is None and job.get("continue-on-error", False) is False:
        for step in job.get("steps", []):
            command = step.get("run")
            if (not isinstance(command, str) or step.get("if") is not None
                    or step.get("continue-on-error", False) is not False):
                continue
            try:
                args = shlex.split(command)
            except ValueError:
                continue
            if matches_production_bandit_args(args):
                return []
    return ["host security must retain literal production Bandit arguments with if/continue-on-error unset"
            + ": expected " + EXPECTED_PRODUCTION_BANDIT_COMMAND]


def workflow_errors(data, text, name=""):
    errors = trigger_errors(data, text, name)
    if is_out_of_scope(text, name):
        return errors
    if text.startswith(OUT_OF_SCOPE):
        errors.append("out-of-scope label is not allowlisted for this workflow")
    errors.extend(reference_errors(data, text))
    for job in data.get("jobs", {}).values():
        if job.get("runs-on") not in ("ubuntu-latest", "macos-26"):
            errors.append("unexpected runner (no hardware/self-hosted runners)")
        permissions = job.get("permissions", data.get("permissions", {}))
        if permissions != {"contents": "read"}:
            errors.append("job must have only contents: read")
        for step in job.get("steps", []):
            errors.extend(step_errors(step))
    errors.extend(production_bandit_errors(data, name))
    return errors


def check_workflows(root):
    workflow_directory = root / ".github/workflows"
    if not workflow_directory.is_dir():
        return ["required workflow directory is missing: .github/workflows"]
    errors = ["required workflow is missing: .github/workflows/" + name
              for name in REQUIRED_WORKFLOWS if not (workflow_directory / name).is_file()]
    paths = workflow_directory.iterdir()
    for path in sorted(path for path in paths
                       if path.is_file() and path.suffix.lower() in (".yml", ".yaml")):
        text = path.read_text()
        errors.extend(str(path.relative_to(root)) + ": " + message
                      for message in workflow_errors(yaml.safe_load(text), text, path.name))
    return errors


def agent_errors(data):
    if (data.get("tools") != ["read", "search"] or data.get("target") != "vscode"
            or data.get("user-invocable") is not True
            or data.get("disable-model-invocation") is not True):
        return ["expected user-invoked VS Code read-only profile"]
    return []


def task_errors(tasks):
    """Check editor task structure and the security task's literal Bandit argv."""
    errors = []
    for task in tasks:
        if task["label"].startswith("BM83:"):
            if (task["type"] != "process"
                    or task["command"] != "${command:python.interpreterPath}"
                    or task.get("runOptions", {}).get("runOn") == "folderOpen"):
                errors.append("BM83 tasks must be explicit selected-Python processes")
    security_tasks = [task for task in tasks if task["label"] == "BM83: security (host only)"]
    if len(security_tasks) != 1:
        errors.append("expected exactly one BM83 security task")
    else:
        args = security_tasks[0].get("args")
        if not isinstance(args, list) or not matches_production_bandit_args(["python", *args]):
            errors.append("BM83 security task must retain literal production Bandit arguments"
                          + ": expected args "
                          + json.dumps(shlex.split(EXPECTED_PRODUCTION_BANDIT_COMMAND)[1:]))
    return errors


def check(root):
    errors = check_workflows(root)
    for name in ("reliability-runtime.agent.md", "reliability-delivery.agent.md"):
        path = root / ".github/agents" / name
        data = yaml.safe_load(path.read_text().split("---", 2)[1])
        errors.extend(name + ": " + message for message in agent_errors(data))
    form = yaml.safe_load((root / ".github/ISSUE_TEMPLATE/reliability.yml").read_text())
    fields = [field for field in form["body"] if field["type"] != "markdown"]
    ids = [field["id"] for field in fields]
    if len(ids) != len(set(ids)) or set(ids) != {
            "owner", "evidence", "reproduction", "experiment", "acceptance", "dependencies"}:
        errors.append("issue form must preserve unique required reliability fields")
    if not all(field.get("validations", {}).get("required") for field in fields):
        errors.append("reliability issue fields must be required")
    tasks = json.loads((root / ".vscode/tasks.json").read_text())
    errors.extend(task_errors(tasks["tasks"]))
    return errors


def main():
    root = Path(__file__).resolve().parents[1]
    try:
        errors = check(root)
    except (OSError, ValueError, KeyError, TypeError, IndexError, yaml.YAMLError) as exc:
        print("FAIL reliability configuration: " + str(exc), file=sys.stderr)
        return 1
    for error in errors:
        print("FAIL " + error, file=sys.stderr)
    if errors:
        return 1
    print("PASS reliability configuration (structural presence and literal-command checks only)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

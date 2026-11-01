#!/usr/bin/env python3
"""Validate repository-only reliability controls; never contact a device."""

import json
from pathlib import Path
import re
import sys

import yaml


def step_errors(step):
    errors = []
    action = step.get("uses")
    if action and not re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", action):
        errors.append("action must be pinned to a full commit: " + action)
    if action and action.startswith("actions/checkout@"):
        if step.get("with", {}).get("persist-credentials") is not False:
            errors.append("checkout must not persist credentials")
    return errors


OUT_OF_SCOPE = "# reliability-scope: out-of-scope legacy automation"
PR_EVENTS = ("pull_request", "pull_request_target", "workflow_run")


def trigger_errors(data, text):
    # PyYAML's YAML 1.1 loader treats the GitHub key `on` as True.
    events = data.get("on", data.get(True, {}))
    if isinstance(events, str):
        events = [events]
    # Explicitly labeled unrelated automation is preserved, but never as a PR job.
    if text.startswith(OUT_OF_SCOPE):
        if any(event in events for event in PR_EVENTS):
            return ["out-of-scope workflow must not run on pull requests"]
        return []
    if any(event in events for event in ("pull_request_target", "workflow_run")):
        return ["privileged follow-up trigger"]
    return []


def workflow_errors(data, text):
    errors = trigger_errors(data, text)
    if text.startswith(OUT_OF_SCOPE):
        return errors
    for pattern, label in (
            (r"\bsecrets\s*[.\[]", "secrets"),
            (r"anthropics/|@anthropic-ai/claude-code|agent_assignment|copilot-swe-agent",
             "separate/cloud agent"),
            (r"(?:^|\brun:|[;&|])\s*(?:exec\s+)?claude\b", "separate Claude command")):
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            errors.append("forbidden credential/agent reference: " + label)
    for job in data.get("jobs", {}).values():
        if job.get("runs-on") not in ("ubuntu-latest", "macos-26"):
            errors.append("unexpected runner (no hardware/self-hosted runners)")
        permissions = job.get("permissions", data.get("permissions", {}))
        if permissions != {"contents": "read"}:
            errors.append("job must have only contents: read")
        for step in job.get("steps", []):
            errors.extend(step_errors(step))
    return errors


def check_workflows(root):
    errors = []
    paths = (root / ".github/workflows").iterdir()
    for path in sorted(path for path in paths
                       if path.is_file() and path.suffix.lower() in (".yml", ".yaml")):
        text = path.read_text()
        errors.extend(str(path.relative_to(root)) + ": " + message
                      for message in workflow_errors(yaml.safe_load(text), text))
    return errors


def agent_errors(data):
    if (data.get("tools") != ["read", "search"] or data.get("target") != "vscode"
            or data.get("user-invocable") is not True
            or data.get("disable-model-invocation") is not True):
        return ["expected user-invoked VS Code read-only profile"]
    return []


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
    for task in tasks["tasks"]:
        if task["label"].startswith("BM83:"):
            if (task["type"] != "process"
                    or task["command"] != "${command:python.interpreterPath}"
                    or task.get("runOptions", {}).get("runOn") == "folderOpen"):
                errors.append("BM83 tasks must be explicit selected-Python processes")
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
    print("PASS reliability configuration (host-only structural checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

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


def workflow_errors(data, text):
    errors = []
    # PyYAML's YAML 1.1 loader treats the GitHub key `on` as True.
    events = data.get("on", data.get(True, {}))
    if isinstance(events, str):
        events = [events]
    if any(event in events for event in ("pull_request_target", "workflow_run")):
        errors.append("privileged follow-up trigger")
    for pattern, label in (
            (r"\bsecrets\s*[.\[]", "secrets"),
            (r"claude|anthropics/|agent_assignment|copilot-swe-agent", "cloud/Claude agent")):
        if re.search(pattern, text, re.IGNORECASE):
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


def check(root):
    errors = check_workflows(root)
    for path in sorted((root / ".github/agents").glob("reliability-*.agent.md")):
        text = path.read_text()
        data = yaml.safe_load(text.split("---", 2)[1])
        if (data.get("tools") != ["read", "search"] or data.get("target") != "vscode"
                or not str(data.get("model", "")).lower().startswith("gpt-")
                or data.get("disable-model-invocation") is not True):
            errors.append(path.name + ": expected explicit local GPT read-only profile")
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

"""Policy failures must remain visible, without requiring GitHub or hardware."""

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "reliability_setup", ROOT / "scripts/check_reliability_setup.py")
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


class ReliabilityPolicyTests(unittest.TestCase):
    def workflow(self):
        return {
            "on": {"pull_request": None},
            "permissions": {"contents": "read"},
            "jobs": {"test": {
                "runs-on": "ubuntu-latest",
                "steps": [{
                    "uses": "actions/checkout@" + "a" * 40,
                    "with": {"persist-credentials": False},
                }],
            }},
        }

    def test_safe_workflow(self):
        self.assertEqual(POLICY.workflow_errors(self.workflow(), ""), [])

    def agent(self):
        return {
            "target": "vscode", "tools": ["read", "search"],
            "user-invocable": True, "disable-model-invocation": True,
        }

    def test_agent_uses_picker_without_model_pin(self):
        self.assertEqual(POLICY.agent_errors(self.agent()), [])
        for name in ("runtime", "delivery"):
            path = ROOT / ".github/agents" / ("reliability-" + name + ".agent.md")
            data = yaml.safe_load(path.read_text().split("---", 2)[1])
            self.assertNotIn("model", data)

    def test_agent_policy_does_not_exclude_copilot_model_families(self):
        data = self.agent()
        for model in ("Claude model inside Copilot", "GPT model inside Copilot"):
            with self.subTest(model=model):
                data["model"] = model
                self.assertEqual(POLICY.agent_errors(data), [])
        self.assertEqual(POLICY.workflow_errors(
            self.workflow(), "# A Claude model offered inside Copilot is allowed."), [])

    def test_agent_still_requires_read_only_tools_and_picker_visibility(self):
        for field, value in (
                ("tools", ["read", "search", "execute"]), ("target", "github-copilot"),
                ("user-invocable", False), ("disable-model-invocation", False)):
            with self.subTest(field=field):
                data = self.agent()
                data[field] = value
                self.assertEqual(POLICY.agent_errors(data), [
                    "expected user-invoked VS Code read-only profile"])

    def test_privileged_trigger(self):
        data = self.workflow()
        data["on"] = {"pull_request_target": None}
        self.assertTrue(POLICY.workflow_errors(data, ""))

    def test_secrets_and_cloud_assignment(self):
        for text in ("${{ secrets.TOKEN }}", "${{ secrets['TOKEN'] }}",
                     "agent_assignment", "anthropics/action", "run: CLAUDE --print",
                     "  claude --print", "npx @anthropic-ai/claude-code"):
            with self.subTest(text=text):
                self.assertTrue(POLICY.workflow_errors(self.workflow(), text))

    def test_labeled_unrelated_automation_is_preserved_but_not_on_prs(self):
        label = POLICY.OUT_OF_SCOPE + "\nrun: claude --print ${{ secrets.TOKEN }}\n"
        data = self.workflow()
        data["on"] = {"schedule": [{"cron": "0 0 * * 1"}]}
        self.assertEqual(POLICY.workflow_errors(data, label), [])
        for event in POLICY.PR_EVENTS:
            with self.subTest(event=event):
                data["on"] = {event: None}
                self.assertEqual(POLICY.workflow_errors(data, label), [
                    "out-of-scope workflow must not run on pull requests"])
        data["on"] = {"schedule": None}
        unlabeled = "# out-of-scope\nrun: claude --print\n"
        self.assertIn("forbidden credential/agent reference: separate Claude command",
                      POLICY.workflow_errors(data, unlabeled))

    def test_mutable_action_and_credentials(self):
        data = self.workflow()
        data["jobs"]["test"]["steps"] = [{"uses": "actions/checkout@v7"}]
        self.assertEqual(set(POLICY.workflow_errors(data, "")), {
            "action must be pinned to a full commit: actions/checkout@v7",
            "checkout must not persist credentials",
        })

    def test_write_permissions_and_hardware_runner(self):
        data = self.workflow()
        data["jobs"]["test"]["permissions"] = {"contents": "write"}
        data["jobs"]["test"]["runs-on"] = "self-hosted"
        self.assertEqual(set(POLICY.workflow_errors(data, "")), {
            "job must have only contents: read",
            "unexpected runner (no hardware/self-hosted runners)",
        })

    def test_yaml_extension_is_checked(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workflows = root / ".github/workflows"
            workflows.mkdir(parents=True)
            data = self.workflow()
            data["on"] = {"pull_request_target": None}
            (workflows / "unsafe.yaml").write_text(yaml.safe_dump(data))
            self.assertEqual(POLICY.check_workflows(root), [
                ".github/workflows/unsafe.yaml: privileged follow-up trigger"])

    def test_repository_configuration(self):
        self.assertEqual(POLICY.check(ROOT), [])


if __name__ == "__main__":
    unittest.main()

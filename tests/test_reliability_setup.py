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
                     "${{ toJSON(secrets) }}", "secrets: inherit",
                     "agent_assignment", "anthropics/action", "run: CLAUDE --print",
                     "  claude --print", "npx @anthropic-ai/claude-code"):
            with self.subTest(text=text):
                self.assertTrue(POLICY.workflow_errors(self.workflow(), text))

    def test_yaml_escapes_cannot_hide_secrets_or_agents(self):
        for escaped, expected in (
                (r'env: {TOKEN: "${{ \u0073ecrets.TOKEN }}"}', "secrets"),
                (r'env: {TOKEN: "${{ \x73ecrets.TOKEN }}"}', "secrets"),
                (r'env: {TOKEN: "${{ \U00000073ecrets.TOKEN }}"}', "secrets"),
                (r'with: {a: "\u0061gent_assignment"}', "separate/cloud agent"),
                (r'run: "\u0063laude --print"', "separate Claude command")):
            with self.subTest(escaped=escaped):
                text = "jobs: {test: {runs-on: ubuntu-latest, steps: [{" + escaped + "}]}}\n"
                self.assertIn("forbidden credential/agent reference: " + expected,
                              POLICY.workflow_errors(yaml.safe_load(text), text))
        with TemporaryDirectory() as directory:
            workflows = Path(directory) / ".github/workflows"
            workflows.mkdir(parents=True)
            text = yaml.safe_dump(self.workflow()) + 'env:\n  TOKEN: "${{ \\u0073ecrets.T }}"\n'
            (workflows / "escaped.yml").write_text(text)
            self.assertEqual(POLICY.check_workflows(Path(directory)), [
                ".github/workflows/escaped.yml: forbidden credential/agent reference: secrets"])

    def test_decoded_step_names_are_not_claude_commands(self):
        data = self.workflow()
        data["jobs"]["test"]["steps"][0]["name"] = "Claude model offered inside Copilot"
        self.assertEqual(POLICY.workflow_errors(data, yaml.safe_dump(data)), [])

    def test_labeled_unrelated_automation_is_preserved_but_not_on_prs(self):
        label = POLICY.OUT_OF_SCOPE + "\nrun: claude --print ${{ secrets.TOKEN }}\n"
        data = self.workflow()
        data["on"] = {"schedule": [{"cron": "0 0 * * 1"}]}
        self.assertEqual(POLICY.workflow_errors(data, label, "codacy.yml"), [])
        for event in POLICY.PR_EVENTS + ("pull_request_review", "issue_comment",
                                         "merge_group", "pull_request_review_comment"):
            with self.subTest(event=event):
                data["on"] = {event: None}
                self.assertEqual(POLICY.workflow_errors(data, label, "codacy.yml"), [
                    "out-of-scope workflow must not run on pull requests"])
        parsed = yaml.safe_load("on: [schedule, issue_comment]\njobs: {}\n")
        self.assertEqual(POLICY.workflow_errors(parsed, label, "codacy.yml"), [
            "out-of-scope workflow must not run on pull requests"])
        data["on"] = {"schedule": None}
        unlabeled = "# out-of-scope\nrun: claude --print\n"
        self.assertIn("forbidden credential/agent reference: separate Claude command",
                      POLICY.workflow_errors(data, unlabeled))

    def test_out_of_scope_label_cannot_exempt_unlisted_workflow(self):
        label = POLICY.OUT_OF_SCOPE + "\nrun: claude --print ${{ secrets.TOKEN }}\n"
        data = self.workflow()
        data["on"] = {"push": None}
        data["jobs"]["test"]["permissions"] = {"contents": "write"}
        self.assertEqual(set(POLICY.workflow_errors(data, label, "new-bypass.yml")), {
            "out-of-scope label is not allowlisted for this workflow",
            "forbidden credential/agent reference: secrets",
            "forbidden credential/agent reference: separate Claude command",
            "job must have only contents: read",
        })
        with TemporaryDirectory() as directory:
            workflows = Path(directory) / ".github/workflows"
            workflows.mkdir(parents=True)
            (workflows / "new-bypass.yml").write_text(label + yaml.safe_dump(data))
            self.assertIn(
                ".github/workflows/new-bypass.yml: forbidden credential/agent reference: secrets",
                POLICY.check_workflows(Path(directory)))

    def test_mutable_action_and_credentials(self):
        data = self.workflow()
        data["jobs"]["test"]["steps"] = [{"uses": "actions/checkout@v7"}]
        self.assertEqual(set(POLICY.workflow_errors(data, "")), {
            "action must be pinned to a full commit: actions/checkout@v7",
            "checkout must not persist credentials",
        })

    def test_checkout_credentials_check_ignores_repository_case(self):
        for action in ("Actions/checkout", "actions/Checkout", "ACTIONS/CHECKOUT"):
            with self.subTest(action=action):
                data = self.workflow()
                data["jobs"]["test"]["steps"] = [{"uses": action + "@" + "a" * 40}]
                self.assertEqual(POLICY.workflow_errors(data, ""), [
                    "checkout must not persist credentials"])
                data["jobs"]["test"]["steps"][0]["with"] = {"persist-credentials": False}
                self.assertEqual(POLICY.workflow_errors(data, ""), [])

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

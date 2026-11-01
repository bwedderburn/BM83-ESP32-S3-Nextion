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

    def test_privileged_trigger(self):
        data = self.workflow()
        data["on"] = {"pull_request_target": None}
        self.assertTrue(POLICY.workflow_errors(data, ""))

    def test_secrets_and_cloud_assignment(self):
        for text in ("${{ secrets.TOKEN }}", "${{ secrets['TOKEN'] }}",
                     "agent_assignment", "anthropics/action", "run: CLAUDE --print"):
            with self.subTest(text=text):
                self.assertTrue(POLICY.workflow_errors(self.workflow(), text))

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

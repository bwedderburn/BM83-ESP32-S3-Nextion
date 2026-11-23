"""The shared VS Code workspace, dev container and setup scripts stay consistent."""

import json
import re
from pathlib import Path

import yaml
from flake8.plugins.pyflakes import FLAKE8_PYFLAKES_CODES

ROOT = Path(__file__).resolve().parents[1]
STRICT_JSON = (
    ".vscode/extensions.json",
    ".vscode/settings.json",
    ".vscode/launch.json",
    ".vscode/tasks.json",
    ".devcontainer/devcontainer.json",
)
# Recommendations that need the host's USB ports or the local VS Code UI.
HOST_ONLY_EXTENSIONS = {
    "platformio.platformio-ide",
    "ms-vscode.vscode-serial-monitor",
    "ms-vscode-remote.remote-containers",
}
CI_GATE_PREFIXES = ("E9", "F63", "F7", "F82")


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def recommendations():
    return [item.lower() for item in load(".vscode/extensions.json")["recommendations"]]


def mpy_cross_version():
    for line in (
        (ROOT / "tools/mpy_cross_pin.env").read_text(encoding="utf-8").splitlines()
    ):
        if line.startswith("MPY_CROSS_VERSION="):
            return line.split("=", 1)[1].strip()
    raise AssertionError("MPY_CROSS_VERSION is missing from tools/mpy_cross_pin.env")


def test_shared_editor_files_are_strict_json():
    for relative in STRICT_JSON:
        assert isinstance(load(relative), dict), relative


def test_recommended_extensions_are_unique_and_cover_the_toolchain():
    names = recommendations()
    assert len(names) == len(set(names))
    for required in (
        "ms-python.python",
        "ms-python.vscode-pylance",
        "ms-python.flake8",
        "ms-vscode.vscode-serial-monitor",
        "platformio.platformio-ide",
    ):
        assert required in names, required


def test_dev_container_installs_every_recommendation_that_works_without_usb():
    container = load(".devcontainer/devcontainer.json")
    installed = {
        item.lower() for item in container["customizations"]["vscode"]["extensions"]
    }
    assert installed == set(recommendations()) - HOST_ONLY_EXTENSIONS
    assert container["postCreateCommand"].endswith(
        "bash scripts/setup-dev.sh --no-extensions"
    )


def test_editor_stubs_match_the_device_circuitpython():
    lines = [
        line.strip()
        for line in (ROOT / "requirements-dev.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert "-r requirements-reliability.txt" in lines
    assert [line for line in lines if line.startswith("circuitpython-stubs")] == [
        "circuitpython-stubs==" + mpy_cross_version()
    ]


def test_dependabot_leaves_the_stub_pin_to_firmware_bumps():
    config = yaml.safe_load(
        (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
    )
    root_pip = [
        update
        for update in config["updates"]
        if update["package-ecosystem"] == "pip" and update["directory"] == "/"
    ]
    assert len(root_pip) == 1
    assert {"dependency-name": "circuitpython-stubs"} in root_pip[0].get("ignore", [])


def test_setup_scripts_share_their_defaults_and_inputs():
    shell = (ROOT / "scripts/setup-dev.sh").read_text(encoding="utf-8")
    powershell = (ROOT / "scripts/setup-dev.ps1").read_text(encoding="utf-8")
    for shell_pattern, powershell_pattern in (
        (r'BOARD="\$\{BOARD:-([^}]+)\}"', r"\[string\]\$Board = '([^']+)'"),
        (
            r'PYTHON_VERSION="\$\{PYTHON_VERSION:-([^}]+)\}"',
            r"\[string\]\$Python = '([^']+)'",
        ),
    ):
        assert re.search(shell_pattern, shell).group(1) == re.search(
            powershell_pattern, powershell
        ).group(1)
    for script in (shell, powershell):
        for needle in (
            "requirements-dev.txt",
            "repo_health",
            "circuitpython_setboard",
            "extensions.json",
        ):
            assert needle in script, needle


def test_powershell_setup_stays_ascii_for_windows_powershell():
    # Windows PowerShell 5.1 reads BOM-less scripts in the ANSI code page.
    (ROOT / "scripts/setup-dev.ps1").read_bytes().decode("ascii")


def test_shared_workspace_files_are_tracked_not_ignored():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for name in ("tasks.json", "extensions.json", "settings.json", "launch.json"):
        assert "!.vscode/" + name in lines, name


def test_workspace_settings_never_rewrite_files_on_save():
    settings = load(".vscode/settings.json")
    for scope in [settings] + [
        value for key, value in settings.items() if key.startswith("[")
    ]:
        for key in (
            "editor.formatOnSave",
            "editor.codeActionsOnSave",
            "files.trimTrailingWhitespace",
            "files.insertFinalNewline",
            "files.trimFinalNewlines",
        ):
            assert scope.get(key) in (None, False), key
    assert settings["[diff]"]["files.trimTrailingWhitespace"] is False


def test_flake8_editor_errors_are_exactly_the_ci_merge_gate():
    gate = {
        code
        for code in set(FLAKE8_PYFLAKES_CODES.values())
        if code.startswith(CI_GATE_PREFIXES)
    }
    gate |= {"E901", "E902", "E999"}
    severity = load(".vscode/settings.json")["flake8.severity"]
    assert {code for code, level in severity.items() if level == "Error"} == gate
    assert {key for key in severity if len(key) == 1} >= {"E", "W", "C", "F"}


def test_tasks_reference_real_scripts_inputs_and_dependencies():
    tasks = load(".vscode/tasks.json")
    labels = [task["label"] for task in tasks["tasks"]]
    inputs = {item["id"] for item in tasks.get("inputs", [])}
    assert len(labels) == len(set(labels))
    for task in tasks["tasks"]:
        assert task.get("runOptions", {}).get("runOn") != "folderOpen", task["label"]
        for dependency in task.get("dependsOn", []):
            assert dependency in labels, dependency
        for argument in task.get("args", []) + task.get("windows", {}).get("args", []):
            for name in re.findall(r"\$\{input:([^}]+)\}", argument):
                assert name in inputs, name
            if re.match(r"^scripts[\\/].+\.(?:py|sh|ps1)$", argument):
                assert (ROOT / argument.replace("\\", "/")).is_file(), argument


def test_no_task_deploys_or_flashes():
    for task in load(".vscode/tasks.json")["tasks"]:
        words = " ".join([task.get("command", "")] + task.get("args", [])).lower()
        assert "upload" not in words and "deploy" not in words, task["label"]

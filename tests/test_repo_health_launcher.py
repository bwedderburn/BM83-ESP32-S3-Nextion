"""Local launcher fixtures; never open real devices or call a remote model."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "tools/mcp/repo_health/launch.mjs"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is unavailable")


def fixture_launcher(tmp_path):
    root = tmp_path / "checkout with spaces"
    directory = root / "tools/mcp/repo_health"
    directory.mkdir(parents=True)
    launcher = directory / "launch.mjs"
    shutil.copyfile(LAUNCHER, launcher)
    return root, launcher, directory / "server.py"


def run_launcher(launcher, **kwargs):
    # Node is absolute and PATH deliberately cannot supply a global Python.
    env = dict(os.environ, PATH="", VIRTUAL_ENV="", PYTHONPATH="")
    return subprocess.run([NODE, str(launcher)], env=env, capture_output=True,
                          text=True, timeout=15, **kwargs)


def test_missing_local_venv_fails_with_setup_guidance(tmp_path):
    _root, launcher, server = fixture_launcher(tmp_path)
    server.write_text("raise RuntimeError('must not start')\n")
    result = run_launcher(launcher)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "-m venv .venv" in result.stderr
    assert "-m pip install -r tools/mcp/repo_health/requirements.txt" in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fixture; Windows layout tested separately")
def test_local_venv_runs_fixed_server_with_stdio_and_exit_code(tmp_path):
    root, launcher, server = fixture_launcher(tmp_path)
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    server.write_text("import os, sys\nprint('echo:' + input(), flush=True)\n"
                      "print('cwd:' + os.getcwd(), flush=True)\n"
                      "print('argv:' + repr(sys.argv[1:]), flush=True)\n"
                      "print('fixture stderr', file=sys.stderr)\nraise SystemExit(7)\n")
    result = run_launcher(launcher, input="hello MCP\n", cwd=tmp_path)
    assert result.returncode == 7
    assert result.stdout.splitlines() == ["echo:hello MCP", "cwd:" + str(root), "argv:[]"]
    assert result.stderr == "fixture stderr\n"


def test_platform_runtime_layout_is_repo_local(tmp_path):
    for platform, relative in (("win32", ".venv/Scripts/python.exe"),
                               ("darwin", ".venv/bin/python"),
                               ("linux", ".venv/bin/python")):
        code = ("import { runtimePaths } from " + json.dumps(LAUNCHER.as_uri()) + ";"
                "console.log(JSON.stringify(runtimePaths(" + json.dumps(str(tmp_path)) + ","
                + json.dumps(platform) + ")));")
        result = subprocess.run([NODE, "--input-type=module", "-e", code],
                                capture_output=True, text=True, timeout=15, check=True)
        paths = json.loads(result.stdout)
        assert Path(paths["python"]) == tmp_path / relative
        assert Path(paths["server"]) == tmp_path / "tools/mcp/repo_health/server.py"


def test_registration_uses_launcher_and_cannot_select_another_script(tmp_path):
    entry = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]["repo-health"]
    assert entry["command"] == "node"
    assert entry["args"] == ["tools/mcp/repo_health/launch.mjs"]
    _root, launcher, _server = fixture_launcher(tmp_path)
    result = subprocess.run([NODE, str(launcher), "other.py"], capture_output=True,
                            text=True, timeout=15)
    assert result.returncode == 1
    assert "accepts no arguments" in result.stderr

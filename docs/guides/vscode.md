# VS Code workspace

The repository ships a shared VS Code workspace in `.vscode/` (tasks, settings,
debug configurations and extension recommendations) and a Linux dev container in
`.devcontainer/`. Personal preferences stay in your user settings. The shared
settings never reformat or rewrite files on save, because several files here
(patches, upstream C sources, vendor packages) must keep their exact bytes.

## One-time setup

Run this from the repository root. Re-running it is safe; it reuses an existing
`.venv`.

Windows (PowerShell)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup-dev.ps1
```

Linux, macOS or WSL (bash)

```bash
bash scripts/setup-dev.sh
```

The script:

1. creates `.venv` with Python 3.13 (uv when available, otherwise `py` or `python3`);
2. installs `requirements-dev.txt` (the pinned CI toolchain plus CircuitPython
   10.3.1 type stubs), the repo-health MCP dependency and the editable package,
   as CI does;
3. selects the ESP32-S3 DevKitC-1 N8R8 board stubs, so `board.IO17` and the other
   pins resolve in the editor;
4. installs any recommended VS Code extensions that are missing.

Options: `-SkipExtensions` / `--no-extensions`, `-Recreate` / `--recreate`,
`-Python 3.12` / `--python 3.12` and `-Board <id>` / `--board <id>`. The same
setup runs inside VS Code as the task **Setup: dev environment**.

Confirm that VS Code uses the repository's `.venv` under Command Palette >
**Python: Select Interpreter**.

## Extensions

| Extension | Purpose |
| --- | --- |
| Python, Pylance, Python Debugger | Interpreter, CircuitPython IntelliSense, and Test Explorer with debugging and coverage |
| Flake8 | Lints with `.flake8` and the pinned flake8 in `.venv`. Advisory style findings appear as information and the codes that fail CI appear as errors. The workspace uses Flake8 for Python linting and turns off Ruff lint diagnostics |
| Serial Monitor | CircuitPython console on the ESP32-S3 (see below) |
| PlatformIO IDE, C/C++ | CrowPanel firmware in `firmware/crowpanel-remote/` and the native C test sources |
| Dev Containers | Reopens the repository in the Linux container described below |
| GitHub Actions, YAML, Even Better TOML, ShellCheck | Workflows, issue forms, `settings.toml`/`pyproject.toml` and the shell scripts |
| GitHub Copilot Chat, Claude Code, Codex | AI assistants; they read `.github/copilot-instructions.md`, `CLAUDE.md` with `.mcp.json`, and `AGENTS.md` |

## Tasks

Terminal > Run Task. The Python tasks use the interpreter selected in VS Code.

| Task | What it runs |
| --- | --- |
| BM83: host tests | `pytest -q`; the default test task |
| BM83: test current file | `pytest -q` on the open test file |
| CircuitPython: verify .mpy packaging (Linux x64) | Fetches the SHA-256-verified compiler and runs the real packaging tests in temporary directories |
| BM83: lint gate (CI flake8) | The flake8 selection that fails CI; findings go to Problems |
| BM83: lint advisory (CI flake8 report) | The advisory report CI prints but never fails on |
| BM83: reliability policy | `scripts/check_reliability_setup.py` |
| BM83: security (host only) | Bandit over the production Python, exactly as host-security CI runs it |
| BM83: frozen toolchain advisory audit | pip-audit of the pinned native-build requirements |
| Quick checks: BM83 lint and reliability policy | Lint gate and reliability policy. Run with **Ctrl+Shift+B** on Windows or Linux |
| CI parity: lint gate, host tests, policy | The three merge gates, in order |
| CrowPanel: build firmware (PlatformIO, no upload) | A compile check of the CrowPanel firmware |
| Setup: dev environment | The setup script for your operating system |
| Template: initialize new project | Only in a repository created from this template; see the [template guide](template.md) |

There is deliberately no deploy or flash task. An installed controller can carry
a qualified compiled payload, so deployment follows the
[deployment guide](deployment.md), with a backup and hash verification.

## Test Explorer

The Testing view discovers the host suite under `tests/`. Use **Debug Test** on an
individual test to step into repository code and its fixtures, or **Run with
Coverage** to show which lines your selected tests exercised. Re-run developer
setup in an existing environment to install the pinned coverage plugin.

Run the full host suite under Linux. Windows can run individual compatible tests
and the quick lint and policy checks. Linux also runs the C and C++ host fixtures
when the toolchain is installed.

## WSL

Clone into the Linux filesystem (for example `~/src`) and run Bash setup there.
From the Linux checkout, `code .` opens the VS Code window with the WSL extension
host. Select `.venv/bin/python` and install the Python, Pylance, Python Debugger
and Flake8 extensions in WSL if the Extensions view shows them only as local.
Use `build-essential`, `rsync` and `zip` for the Linux host fixtures. `repo-health`
needs Linux Node on the VS Code server's PATH. For a user-local Node install,
see [VS Code's server environment setup](https://code.visualstudio.com/docs/remote/wsl#_advanced-environment-setup-script).

## Dev container and Codespaces

`.devcontainer/devcontainer.json` provides Python 3.13 on Debian, a pinned Node
feature, and the image's C/C++ toolchain, `rsync` and `zip`. It installs the
project tooling and stores the container's `.venv` in a Docker volume, separate
from a virtual environment in the host checkout.

For a fast, isolated checkout on Windows, choose **Dev Containers: Clone
Repository in Container Volume**. To share source files with an existing WSL
checkout, use **Dev Containers: Reopen in Container** from its WSL window. A
GitHub Codespace can use the same project configuration. Use these environments
for host tests, lint and coverage. Use the host operating system for physical
controller and CrowPanel work.

## CircuitPython serial console

1. Open the **Serial Monitor** panel, choose the ESP32-S3's CircuitPython port
   (USB `303A:7003`) and 115200 baud.
2. In the monitor's settings (gear icon), enable **DTR**. CircuitPython discards
   console output while DTR is low.
3. Stop monitoring before flashing, or before a host tool needs the same port.

The CrowPanel's CH340 (`1A86:7523`) is a different port; see the
[CrowPanel guide](../../firmware/crowpanel-remote/README.md).

## CrowPanel firmware

PlatformIO IDE picks up a project from the root of an opened folder, so open
`firmware/crowpanel-remote` in its own window (`code firmware/crowpanel-remote`)
for its IntelliSense, toolbar and monitor. From the main window, the
**CrowPanel: build firmware** task compiles without uploading. Flash only by
the procedure in the CrowPanel guide.

## AI assistants and MCP

`.mcp.json` provides `repo-health` for the VS Code MCP client and Claude Code. In
VS Code, use **MCP: List Servers** to start the server for the active workspace.
Keep the assistant in the same Linux checkout as the tests and source being
reviewed. The server uses that checkout's `.venv`. See the
[tool list](../../tools/mcp/repo_health/README.md) before selecting agent tools.
`repo_test_summary` executes local pytest. Use the inventory, TODO, churn,
dependency and lint tools for read-only review.

Open the repo root in Codex or start its CLI there. Trusted Codex projects load
`.codex/config.toml`, which exposes the five read-only tools. Codex takes project
instructions from `AGENTS.md`. Claude Code uses `CLAUDE.md` and prompts for
approval of the project MCP registration. Copilot instructions remain in
`.github/copilot-instructions.md`. The
[maintenance handoff](../reliability/DIRECT-MAINTENANCE.md) records the pause on
Copilot requests.

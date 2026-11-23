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

```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup-dev.ps1
```

Linux, macOS or WSL (bash)

```
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

Then choose the interpreter once: Command Palette > **Python: Select
Interpreter** > `.venv`.

## Extensions

| Extension | Purpose |
| --- | --- |
| Python, Pylance, Python Debugger | Interpreter, IntelliSense with the CircuitPython stubs, debugging host code and tests |
| Flake8 | Lints with `.flake8` and the pinned flake8 in `.venv`. Advisory style findings appear as information; the codes that fail CI appear as errors |
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
| BM83: lint gate (CI flake8) | The flake8 selection that fails CI; findings go to Problems |
| BM83: lint advisory (CI flake8 report) | The advisory report CI prints but never fails on |
| BM83: reliability policy | `scripts/check_reliability_setup.py` |
| BM83: security (host only) | Bandit over the production Python, exactly as host-security CI runs it |
| BM83: frozen toolchain advisory audit | pip-audit of the pinned native-build requirements |
| CI parity: lint gate, host tests, policy | The three merge gates, in order |
| CrowPanel: build firmware (PlatformIO, no upload) | A compile check of the CrowPanel firmware |
| Setup: dev environment | The setup script for your operating system |
| Template: initialize new project | Only in a repository created from this template; see the [template guide](template.md) |

There is deliberately no deploy or flash task. An installed controller can carry
a qualified compiled payload, so deployment follows the
[deployment guide](deployment.md), with a backup and hash verification.

## Tests on Windows

The Testing view discovers the same suite as `pytest -q`. The complete host suite
targets Linux: on Windows, tests that assume POSIX permissions, paths or tools
fail or skip, as they do on `main`. Use the dev container or WSL for a complete,
green run, and treat a Windows run as a partial check.

## Dev container and Codespaces

`.devcontainer/devcontainer.json` provides Python 3.13 on Debian with Node.js, a
C/C++ toolchain and `rsync`, then runs `scripts/setup-dev.sh --no-extensions`.
Choose **Dev Containers: Reopen in Container**, or open the repository in a
GitHub Codespace. The container has no USB access, so use it for host tests,
linting and documentation, and use the host operating system for the controller
and the CrowPanel.

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

`.mcp.json` registers the repository's `repo-health` MCP server, which runs from
`.venv`; the setup script installs its dependency. Agent instructions live in
`AGENTS.md`, `CLAUDE.md` and `.github/copilot-instructions.md`.

#!/usr/bin/env bash
# One-time, re-runnable development setup for Linux, macOS, WSL and the dev container.
#
# Creates .venv (uv when available, otherwise python3 -m venv), installs
# requirements-dev.txt, the repo-health MCP dependency and the editable package
# the way CI does, selects the CircuitPython board stubs, then installs the VS Code
# extensions recommended in .vscode/extensions.json. It never touches a board.
#
#   bash scripts/setup-dev.sh                  # normal setup
#   bash scripts/setup-dev.sh --no-extensions  # skip VS Code extensions
#   bash scripts/setup-dev.sh --recreate       # rebuild .venv from scratch
set -euo pipefail

PYTHON_VERSION="${PYTHON_VERSION:-3.13}"
BOARD="${BOARD:-espressif_esp32s3_devkitc_1_n8r8}"
INSTALL_EXTENSIONS=1
RECREATE=0

usage() {
    cat <<'EOF'
Usage: bash scripts/setup-dev.sh [--python X.Y] [--board BOARD_ID] [--no-extensions] [--recreate]

  --python X.Y       Python for a new .venv (default 3.13, the newest version CI tests)
  --board BOARD_ID   CircuitPython board stubs (default espressif_esp32s3_devkitc_1_n8r8)
  --no-extensions    Do not install VS Code extensions
  --recreate         Delete and rebuild .venv
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --python) PYTHON_VERSION="${2:?--python needs a version}"; shift ;;
        --board) BOARD="${2:?--board needs a board id}"; shift ;;
        --no-extensions) INSTALL_EXTENSIONS=0 ;;
        --recreate) RECREATE=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
HAVE_UV=0
if command -v uv >/dev/null 2>&1; then
    HAVE_UV=1
fi

if [ "$RECREATE" -eq 1 ] && [ -d "$VENV" ]; then
    echo "Removing existing .venv (--recreate)"
    rm -rf "$VENV"
fi

if [ ! -x "$PY" ]; then
    echo "Creating .venv with Python $PYTHON_VERSION"
    if [ "$HAVE_UV" -eq 1 ]; then
        uv venv --seed --python "$PYTHON_VERSION" "$VENV"
    else
        BASE=""
        for candidate in "python$PYTHON_VERSION" python3; do
            if command -v "$candidate" >/dev/null 2>&1; then
                BASE="$candidate"
                break
            fi
        done
        if [ -z "$BASE" ]; then
            echo "Python $PYTHON_VERSION was not found. Install it (or uv) and re-run." >&2
            exit 1
        fi
        "$BASE" -m venv "$VENV"
    fi
else
    echo "Reusing existing .venv"
fi

VERSION="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
echo "Python $VERSION at $PY"
case "$VERSION" in
    3.11|3.12|3.13) ;;
    *) echo "Note: CI tests Python 3.11-3.13; run with --recreate to rebuild .venv on $PYTHON_VERSION." ;;
esac

if [ "$HAVE_UV" -eq 1 ]; then
    uv pip install --python "$PY" -r requirements-dev.txt -r tools/mcp/repo_health/requirements.txt
    uv pip install --python "$PY" -e .
else
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install -r requirements-dev.txt -r tools/mcp/repo_health/requirements.txt
    "$PY" -m pip install -e .
fi

"$VENV/bin/circuitpython_setboard" "$BOARD"

if [ "$INSTALL_EXTENSIONS" -eq 1 ]; then
    if command -v code >/dev/null 2>&1; then
        INSTALLED="$(code --list-extensions 2>/dev/null | tr '[:upper:]' '[:lower:]' || true)"
        WANTED="$("$PY" -c 'import json; print("\n".join(json.load(open(".vscode/extensions.json"))["recommendations"]))')"
        while IFS= read -r extension; do
            [ -n "$extension" ] || continue
            lower="$(printf '%s' "$extension" | tr '[:upper:]' '[:lower:]')"
            if printf '%s\n' "$INSTALLED" | grep -qxF "$lower"; then
                echo "  installed  $extension"
            elif code --install-extension "$extension" >/dev/null 2>&1; then
                echo "  added      $extension"
            else
                echo "  WARNING    could not install $extension (it may be built into your VS Code)" >&2
            fi
        done <<EOF
$WANTED
EOF
    else
        echo "VS Code's 'code' command was not found; open the folder in VS Code and accept the"
        echo "recommended extensions instead (Extensions view > Recommended)."
    fi
fi

cat <<'EOF'

Setup complete. In VS Code:
  1. Command Palette > "Python: Select Interpreter" > .venv (if it is not already selected)
  2. Terminal > Run Task > "BM83: host tests" (or "CI parity: lint gate, host tests, policy")
EOF

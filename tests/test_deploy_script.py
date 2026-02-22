import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = REPO_ROOT / "deploy.sh"


def _require_shell_tools():
    if not shutil.which("bash"):
        pytest.skip("bash not available")
    if not shutil.which("rsync"):
        pytest.skip("rsync not available")


def test_deploy_script_creates_backup_and_deploys(tmp_path):
    """deploy.sh should snapshot device files before copying new firmware."""
    _require_shell_tools()
    circuitpy_path = tmp_path / "CIRCUITPY"
    source_dir = tmp_path / "source"
    backups_dir = tmp_path / "backups"
    circuitpy_path.mkdir()
    source_dir.mkdir()

    (circuitpy_path / "lib").mkdir()
    (circuitpy_path / "lib" / "old.mpy").write_bytes(b"old")
    (source_dir / "main.py").write_text("print('new firmware')\n", encoding="utf-8")
    (source_dir / "lib").mkdir()
    (source_dir / "lib" / "new.mpy").write_bytes(b"new")

    env = os.environ.copy()
    env["CIRCUITPY_PATH"] = str(circuitpy_path)
    env["SOURCE_DIR"] = str(source_dir)
    env["BACKUP_ROOT"] = str(backups_dir)

    subprocess.run(["bash", str(DEPLOY_SCRIPT)], check=True, cwd=REPO_ROOT, env=env)

    backups = sorted(backups_dir.glob("circuitpy-*"))
    assert backups, "Expected at least one backup folder"
    assert (backups[-1] / "lib" / "old.mpy").read_bytes() == b"old"
    assert (circuitpy_path / "main.py").read_text(encoding="utf-8") == "print('new firmware')\n"
    assert (circuitpy_path / "lib" / "new.mpy").read_bytes() == b"new"


def test_deploy_script_backup_only_does_not_overwrite_files(tmp_path):
    """--backup-only should capture a snapshot without deploying source files."""
    _require_shell_tools()
    circuitpy_path = tmp_path / "CIRCUITPY"
    source_dir = tmp_path / "source"
    backups_dir = tmp_path / "backups"
    circuitpy_path.mkdir()
    source_dir.mkdir()

    (circuitpy_path / "main.py").write_text("print('old firmware')\n", encoding="utf-8")
    (source_dir / "main.py").write_text("print('new firmware')\n", encoding="utf-8")

    env = os.environ.copy()
    env["CIRCUITPY_PATH"] = str(circuitpy_path)
    env["SOURCE_DIR"] = str(source_dir)
    env["BACKUP_ROOT"] = str(backups_dir)

    subprocess.run(["bash", str(DEPLOY_SCRIPT), "--backup-only"], check=True, cwd=REPO_ROOT, env=env)

    backups = sorted(backups_dir.glob("circuitpy-*"))
    assert backups, "Expected at least one backup folder"
    assert (backups[-1] / "main.py").read_text(encoding="utf-8") == "print('old firmware')\n"
    assert (circuitpy_path / "main.py").read_text(encoding="utf-8") == "print('old firmware')\n"

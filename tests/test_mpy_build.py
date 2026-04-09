import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "firmware" / "circuitpython"
SRC_LIB_DIR = SRC_DIR / "lib"
DIST_DIR = REPO_ROOT / "dist" / "circuitpython"
DIST_LIB_DIR = DIST_DIR / "lib"


def _mpy_cross_path():
    return os.environ.get("MPY_CROSS") or shutil.which("mpy-cross")


def test_plain_python_module_path_smoke():
    """Always-on CI lane: imports directly from source .py modules."""
    import bm83
    import nextion
    import utils

    assert hasattr(utils, "sanitize_text")
    assert hasattr(nextion, "Nextion")
    assert hasattr(bm83, "Bm83")


@pytest.mark.mpy
def test_build_mpy_outputs():
    """Build .mpy files and verify expected outputs when mpy-cross is available."""
    if os.environ.get("RUN_MPY_TESTS") != "1":
        pytest.skip("Skipped by CI toggle: set RUN_MPY_TESTS=1 to enable .mpy build verification")

    mpy_cross = _mpy_cross_path()
    if not mpy_cross:
        pytest.skip("mpy-cross not available; skipping .mpy build test")

    build_script = REPO_ROOT / "build_mpy.sh"
    if not build_script.exists():
        pytest.skip("build_mpy.sh not found; skipping .mpy build test")

    env = os.environ.copy()
    env["MPY_CROSS"] = mpy_cross
    subprocess.run(["bash", str(build_script)], check=True, env=env, cwd=REPO_ROOT)

    assert DIST_DIR.exists(), "dist/circuitpython not created"
    assert (DIST_DIR / "main.py").exists(), "main.py should remain as .py in dist"
    assert DIST_LIB_DIR.exists(), "dist/circuitpython/lib not created"

    # Every library .py should have a .mpy in dist/lib
    for py_file in SRC_LIB_DIR.rglob("*.py"):
        rel = py_file.relative_to(SRC_LIB_DIR)
        out = DIST_LIB_DIR / rel.with_suffix(".mpy")
        assert out.exists(), f"Missing compiled file: {out}"

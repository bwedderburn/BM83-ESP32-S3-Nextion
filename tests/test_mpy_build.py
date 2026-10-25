import os
import shutil
import subprocess
import sys
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX build-script asset-copy branches")
@pytest.mark.parametrize("with_rsync", [False, True])
def test_private_wifi_profile_is_never_packaged(tmp_path, with_rsync):
    """Exercise both real asset-copy paths without using device credentials."""
    bash = shutil.which("bash")
    rsync = shutil.which("rsync")
    if not bash or (with_rsync and not rsync):
        pytest.skip("required POSIX copy tool is unavailable")
    script = tmp_path / "build_mpy.sh"
    shutil.copyfile(REPO_ROOT / "build_mpy.sh", script)
    pin_file = REPO_ROOT / "tools/mpy_cross_pin.env"
    (tmp_path / "tools").mkdir()
    shutil.copyfile(pin_file, tmp_path / "tools/mpy_cross_pin.env")
    version = next(line.partition("=")[2] for line in pin_file.read_text().splitlines()
                   if line.startswith("MPY_CROSS_VERSION="))
    source = tmp_path / "firmware/circuitpython"
    (source / "lib").mkdir(parents=True)
    (source / "assets").mkdir()
    (source / "main.py").write_text("pass\n")
    (source / "lib/example.py").write_text("VALUE = 1\n")
    (source / "assets/public.txt").write_text("keep this asset\n")
    for parent in (source, source / "assets"):
        (parent / ".artwork_wifi.json").write_text('{"password":"synthetic-fixture"}\n')
        (parent / ".metadata_bridge.json").write_text('{"token":"synthetic-fixture"}\n')
    compiler = tmp_path / "fake-mpy"
    compiler.write_text("#!" + sys.executable + "\nimport sys\nfrom pathlib import Path\n"
                        "if sys.argv[1:] == ['--version']:\n"
                        "    print('CircuitPython %s on fixture; mpy-cross emitting mpy v6.3')\n"
                        "    raise SystemExit(0)\n"
                        "Path(sys.argv[sys.argv.index('-o') + 1]).write_bytes(b'test-mpy')\n" % version)
    compiler.chmod(0o755)
    executables = tmp_path / "bin"
    executables.mkdir()
    for name in ("dirname", "rm", "mkdir", "cp", "find", "sed", "head"):
        executable = shutil.which(name)
        assert executable, name
        (executables / name).symlink_to(executable)
    if with_rsync:
        (executables / "rsync").symlink_to(rsync)
    env = dict(os.environ, PATH=str(executables), MPY_CROSS=str(compiler))
    env.pop("MPY_CROSS_ALLOW_UNPINNED", None)
    result = subprocess.run(  # nosec B603 - fixed repository script and isolated test argv
        [bash, str(script)], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    package = tmp_path / "dist/circuitpython"
    assert not list(package.rglob(".artwork_wifi.json"))
    assert not list(package.rglob(".metadata_bridge.json"))
    assert (package / "assets/public.txt").read_text() == "keep this asset\n"
    assert (package / "lib/example.mpy").read_bytes() == b"test-mpy"

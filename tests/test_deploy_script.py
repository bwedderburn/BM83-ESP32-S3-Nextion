"""Exercise deployment with isolated repository and CIRCUITPY directories."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX deploy helper")


def fixture_repo(tmp_path, with_rsync):
    bash = shutil.which("bash")
    rsync = shutil.which("rsync")
    if not bash or (with_rsync and not rsync):
        pytest.skip("required POSIX copy tool is unavailable")
    script = tmp_path / "deploy.sh"
    shutil.copyfile(ROOT / "deploy.sh", script)
    sources = {}
    for mode, relative in (("src", "firmware/circuitpython"),
                           ("mpy", "dist/circuitpython")):
        source = tmp_path / relative
        (source / "lib/example/__pycache__").mkdir(parents=True)
        (source / "boot.py").write_text("# %s startup\n" % mode)
        (source / "main.py").write_text("# %s main\n" % mode)
        module = "module.py" if mode == "src" else "module.mpy"
        (source / "lib/example" / module).write_bytes(mode.encode("ascii"))
        (source / "lib/example/__pycache__/module.pyc").write_bytes(b"skip cache")
        for name in ("settings.toml", ".artwork_wifi.json", ".metadata_bridge.json",
                     "ble_counter.txt"):
            (source / name).write_text("do not replace device-local " + name)
        sources[mode] = source
    destination = tmp_path / "mock CIRCUITPY"
    (destination / "lib/adafruit_ble").mkdir(parents=True)
    (destination / "lib/adafruit_ble/__init__.mpy").write_bytes(b"keep dependency")
    (destination / "boot.py").write_text("old startup\n")
    (destination / "main.py").write_text("old main\n")
    for name in ("settings.toml", ".artwork_wifi.json", ".metadata_bridge.json",
                 "ble_counter.txt"):
        (destination / name).write_text("existing private " + name)
    executables = tmp_path / "bin"
    executables.mkdir()
    for name in ("dirname", "cp", "mkdir", "find", "rm"):
        executable = shutil.which(name)
        assert executable, name
        (executables / name).symlink_to(executable)
    if with_rsync:
        (executables / "rsync").symlink_to(rsync)
    env = dict(os.environ, PATH=str(executables), CIRCUITPY_PATH=str(destination))
    return bash, script, sources, destination, env


@pytest.mark.parametrize("mode", ["src", "mpy"])
@pytest.mark.parametrize("with_rsync", [False, True])
def test_deploy_includes_source_boot_and_preserves_local_configuration(
        tmp_path, mode, with_rsync):
    bash, script, sources, destination, env = fixture_repo(tmp_path, with_rsync)
    private_names = ("settings.toml", ".artwork_wifi.json", ".metadata_bridge.json",
                     "ble_counter.txt")
    before = {name: (destination / name).read_bytes() for name in private_names}
    args = ["--mpy"] if mode == "mpy" else []
    result = subprocess.run(  # nosec B603 - fixed script in an isolated fixture
        [bash, str(script)] + args, cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    for entrypoint in ("boot.py", "main.py"):
        assert (destination / entrypoint).read_bytes() == (sources[mode] / entrypoint).read_bytes()
    assert not (destination / "boot.mpy").exists()
    module = "module.py" if mode == "src" else "module.mpy"
    assert (destination / "lib/example" / module).read_bytes() == mode.encode("ascii")
    assert not list(destination.rglob("__pycache__"))
    assert (destination / "lib/adafruit_ble/__init__.mpy").read_bytes() == b"keep dependency"
    assert {name: (destination / name).read_bytes() for name in private_names} == before


@pytest.mark.parametrize("mode", ["src", "mpy"])
def test_missing_boot_fails_before_overwriting_existing_application(tmp_path, mode):
    bash, script, sources, destination, env = fixture_repo(tmp_path, False)
    (sources[mode] / "boot.py").unlink()
    before = {p.relative_to(destination): p.read_bytes()
              for p in destination.rglob("*") if p.is_file()}
    args = ["--mpy"] if mode == "mpy" else []
    result = subprocess.run(  # nosec B603 - fixed script in an isolated fixture
        [bash, str(script)] + args, cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert "missing" in result.stderr.lower()
    assert {p.relative_to(destination): p.read_bytes()
            for p in destination.rglob("*") if p.is_file()} == before

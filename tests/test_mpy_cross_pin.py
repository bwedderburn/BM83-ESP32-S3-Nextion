"""The mpy-cross used for dist builds is pinned (issue #148).

These run without a real mpy-cross: build_mpy.sh is exercised against a stub
compiler in a temporary copy of the source tree, so the tracked dist/ is never
touched.
"""

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PIN_FILE = REPO_ROOT / "tools" / "mpy_cross_pin.env"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-circuitpython-dist.yml"

BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="bash not available")


def _read_pin():
    pin = {}
    for line in PIN_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            pin[key] = value
    return pin


def test_pin_is_an_exact_stable_release_with_checksum():
    pin = _read_pin()
    version = pin["MPY_CROSS_VERSION"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), "pin a stable release, not a pre-release or git build"
    assert pin["MPY_CROSS_LINUX_AMD64_KEY"] == (
        "bin/mpy-cross/linux-amd64/mpy-cross-linux-amd64-%s.static" % version
    )
    assert re.fullmatch(r"[0-9a-f]{64}", pin["MPY_CROSS_LINUX_AMD64_SHA256"])


def test_workflow_uses_pin_not_latest_listing():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/fetch_mpy_cross.sh" in text
    assert "sort -V" not in text
    assert "?prefix=" not in text


def _stub_tree(tmp_path, reported_version, stub_path=None, fail_compile=False):
    root = tmp_path / "repo"
    # build_mpy.sh only reads firmware/circuitpython; copying all of firmware/
    # would also drag in gitignored build output such as crowpanel-remote/.pio.
    shutil.copytree(
        REPO_ROOT / "firmware" / "circuitpython",
        root / "firmware" / "circuitpython",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (root / "tools").mkdir()
    shutil.copy2(PIN_FILE, root / "tools" / PIN_FILE.name)
    shutil.copy2(REPO_ROOT / "build_mpy.sh", root / "build_mpy.sh")

    stub = stub_path or tmp_path / "mpy-cross"
    stub.parent.mkdir(parents=True, exist_ok=True)
    # The stub writes the -s (embedded source name) argument into the -o file,
    # so tests can check what a real mpy-cross would bake into each .mpy.
    compile_body = (
        'echo "simulated compile error" >&2; exit 1\n'
        if fail_compile
        else (
            'src=""; out=""\n'
            "while [[ $# -gt 0 ]]; do\n"
            '  case "$1" in -s) shift; src="$1" ;; -o) shift; out="$1" ;; esac\n'
            "  shift\n"
            "done\n"
            'printf "%s" "$src" > "$out"\n'
        )
    )
    # write_bytes, not write_text: keep LF line endings on Windows too.
    stub.write_bytes(
        (
            "#!/bin/bash\n"
            'if [[ "$1" == "--version" ]]; then\n'
            '  echo "CircuitPython %s on 2025-10-18; mpy-cross emitting mpy v6.3"; exit 0\n'
            "fi\n" % reported_version
            + compile_body
        ).encode("utf-8")
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return root, stub


def _run_build(root, stub, **extra_env):
    env = os.environ.copy()
    env.pop("MPY_CROSS_ALLOW_UNPINNED", None)
    env.pop("MPY_CROSS", None)
    if stub is not None:
        env["MPY_CROSS"] = str(stub)
    env.update(**extra_env)
    return subprocess.run(
        [BASH, str(root / "build_mpy.sh")], cwd=root, env=env, capture_output=True, text=True
    )


@needs_bash
def test_build_accepts_pinned_version_and_records_it(tmp_path):
    version = _read_pin()["MPY_CROSS_VERSION"]
    root, stub = _stub_tree(tmp_path, version)

    result = _run_build(root, stub)

    assert result.returncode == 0, result.stderr
    info = (root / "dist" / "BUILD_INFO.txt").read_text(encoding="utf-8")
    assert "mpy_cross_pinned=%s\n" % version in info
    assert "CircuitPython %s on" % version in info
    assert not (root / "dist" / "circuitpython" / "BUILD_INFO.txt").exists()
    assert (root / "dist" / "circuitpython" / "main.py").read_bytes() == (
        root / "firmware" / "circuitpython" / "main.py"
    ).read_bytes()


@needs_bash
def test_build_embeds_checkout_independent_source_names(tmp_path):
    # mpy-cross bakes the source filename into each .mpy. Passing the absolute
    # path made every .mpy depend on where the repo was checked out (CI runner
    # vs WSL), so the same source + pinned compiler gave different bytes.
    version = _read_pin()["MPY_CROSS_VERSION"]
    root, stub = _stub_tree(tmp_path, version)

    result = _run_build(root, stub)

    assert result.returncode == 0, result.stderr
    lib = root / "dist" / "circuitpython" / "lib"
    compiled = sorted(lib.rglob("*.mpy"))
    assert compiled
    for out in compiled:
        expected = "lib/" + out.relative_to(lib).with_suffix(".py").as_posix()
        assert out.read_text(encoding="utf-8") == expected


@needs_bash
def test_build_rejects_unpinned_version(tmp_path):
    root, stub = _stub_tree(tmp_path, "99.0.0-alpha.1")

    result = _run_build(root, stub)

    assert result.returncode != 0
    assert "version mismatch" in result.stderr
    assert not (root / "dist").exists()


@needs_bash
def test_build_unpinned_override_warns_and_continues(tmp_path):
    root, stub = _stub_tree(tmp_path, "99.0.0-alpha.1")

    result = _run_build(root, stub, MPY_CROSS_ALLOW_UNPINNED="1")

    assert result.returncode == 0, result.stderr
    assert "unpinned" in result.stderr


@needs_bash
def test_build_defaults_to_fetched_compiler(tmp_path):
    """With MPY_CROSS unset, build_mpy.sh uses what fetch_mpy_cross.sh installed."""
    version = _read_pin()["MPY_CROSS_VERSION"]
    root, _ = _stub_tree(
        tmp_path, version, stub_path=tmp_path / "repo" / "tools" / "mpy-cross" / "mpy-cross"
    )

    result = _run_build(root, None)

    assert result.returncode == 0, result.stderr
    info = (root / "dist" / "BUILD_INFO.txt").read_text(encoding="utf-8")
    assert "mpy_cross_version=CircuitPython %s on" % version in info


@needs_bash
def test_failed_build_does_not_leave_stale_build_info(tmp_path):
    version = _read_pin()["MPY_CROSS_VERSION"]
    root, stub = _stub_tree(tmp_path, version, fail_compile=True)
    (root / "dist").mkdir()
    (root / "dist" / "BUILD_INFO.txt").write_text("mpy_cross_pinned=stale\n", encoding="utf-8")

    result = _run_build(root, stub)

    assert result.returncode != 0
    assert not (root / "dist" / "BUILD_INFO.txt").exists()

"""The mpy-cross used for dist builds is pinned (issue #148).

These run without a real mpy-cross: build_mpy.sh is exercised against a stub
compiler in a temporary copy of the source tree, so the tracked dist/ is never
touched.
"""

import hashlib
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


GIT = shutil.which("git")


@needs_bash
@pytest.mark.skipif(GIT is None, reason="git not available")
def test_build_info_marks_uncommitted_firmware_sources(tmp_path):
    """source_commit gets -dirty when firmware/circuitpython has local edits."""
    version = _read_pin()["MPY_CROSS_VERSION"]
    root, stub = _stub_tree(tmp_path, version)
    git = [GIT, "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(git + ["init", "-q"], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "base"], check=True)
    head = subprocess.run(
        git + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    info = root / "dist" / "BUILD_INFO.txt"

    assert _run_build(root, stub).returncode == 0
    assert "source_commit=%s\n" % head in info.read_text(encoding="utf-8")

    with (root / "firmware" / "circuitpython" / "main.py").open("a", encoding="utf-8") as f:
        f.write("# local edit\n")
    assert _run_build(root, stub).returncode == 0
    assert "source_commit=%s-dirty\n" % head in info.read_text(encoding="utf-8")


SHA256SUM = shutil.which("sha256sum")
FAKE_KEY = "bin/mpy-cross/linux-amd64/mpy-cross-linux-amd64-0.0.0.static"
FAKE_PAYLOAD = b"#!/bin/bash\necho 'CircuitPython 0.0.0 fake mpy-cross'\n"


def _fetch_tree(tmp_path, pinned_sha):
    """Copy fetch_mpy_cross.sh beside a pin file, with curl/uname stubbed on PATH."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "tools").mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "fetch_mpy_cross.sh", root / "scripts" / "fetch_mpy_cross.sh")
    (root / "tools" / PIN_FILE.name).write_bytes(
        (
            "MPY_CROSS_VERSION=0.0.0\n"
            "MPY_CROSS_LINUX_AMD64_KEY=%s\n"
            "MPY_CROSS_LINUX_AMD64_SHA256=%s\n" % (FAKE_KEY, pinned_sha)
        ).encode("utf-8")
    )
    payload = tmp_path / "payload"
    payload.write_bytes(FAKE_PAYLOAD)

    shims = tmp_path / "shims"
    shims.mkdir()
    # Offline: curl records the URL and writes the payload to its -o target.
    # uname reports linux-amd64 so the platform gate passes on any host.
    for name, body in (
        (
            "curl",
            'out=""; url=""\n'
            "while [[ $# -gt 0 ]]; do\n"
            '  case "$1" in -o) shift; out="$1" ;; -*) ;; *) url="$1" ;; esac\n'
            "  shift\n"
            "done\n"
            'printf "%s" "$url" > "' + str(tmp_path / "curl_url") + '"\n'
            'cat "' + str(payload) + '" > "$out"\n',
        ),
        ("uname", 'case "$1" in -s) echo Linux ;; -m) echo x86_64 ;; esac\n'),
    ):
        shim = shims / name
        shim.write_bytes(("#!/bin/bash\n" + body).encode("utf-8"))
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return root, shims


def _run_fetch(root, shims, out):
    env = os.environ.copy()
    env["PATH"] = str(shims) + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [BASH, str(root / "scripts" / "fetch_mpy_cross.sh"), str(out)],
        cwd=root, env=env, capture_output=True, text=True,
    )


@needs_bash
@pytest.mark.skipif(SHA256SUM is None, reason="sha256sum not available")
def test_fetch_installs_download_when_sha256_matches(tmp_path):
    root, shims = _fetch_tree(tmp_path, hashlib.sha256(FAKE_PAYLOAD).hexdigest())
    out = tmp_path / "bin" / "mpy-cross"

    result = _run_fetch(root, shims, out)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "curl_url").read_text(encoding="utf-8").endswith("/" + FAKE_KEY)
    assert out.read_bytes() == FAKE_PAYLOAD
    assert os.access(out, os.X_OK)
    assert sorted(p.name for p in out.parent.iterdir()) == ["mpy-cross"]


@needs_bash
@pytest.mark.skipif(SHA256SUM is None, reason="sha256sum not available")
def test_fetch_rejects_sha256_mismatch_without_touching_target(tmp_path):
    root, shims = _fetch_tree(tmp_path, hashlib.sha256(b"something else").hexdigest())
    out = tmp_path / "bin" / "mpy-cross"
    out.parent.mkdir()
    out.write_bytes(b"previously installed compiler\n")

    result = _run_fetch(root, shims, out)

    assert result.returncode != 0
    assert "sha256 mismatch" in result.stderr
    assert out.read_bytes() == b"previously installed compiler\n"
    assert sorted(p.name for p in out.parent.iterdir()) == ["mpy-cross"]

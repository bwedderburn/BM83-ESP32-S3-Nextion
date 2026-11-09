"""Exercise the real build/packaging scripts in disposable, host-only Git repos.

The default compiler is an explicitly pinned deterministic fixture, not evidence
of valid CircuitPython bytecode. RUN_MPY_TESTS=1 also enables the real compiler
lane when MPY_CROSS identifies the repository-pinned Linux executable.
"""

import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import zipfile

import pytest

from tests.release_fixture_support import git_environment, set_hostile_git_environment


REPO = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
GIT = shutil.which("git")
VERSION = "v1.0.0-rc.1"
PREFIX = "BM83-Remote-" + VERSION + "/"
SOURCE_ZIP = "bm83-controller-badge-" + VERSION + "-source.zip"
COMPILED_ZIP = "bm83-controller-" + VERSION + "-mpy.zip"
ASSETS = {SOURCE_ZIP, COMPILED_ZIP, "MANIFEST.json", "SHA256SUMS.txt"}
pytestmark = pytest.mark.skipif(
    os.name == "nt" or BASH is None or GIT is None,
    reason="Requires POSIX Bash and Git for the actual host build script",
)


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _run(arguments, repo, environment, *, check=True):
    result = subprocess.run(arguments, cwd=repo, env=environment, capture_output=True,
                            text=True, timeout=60)
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def _git(repo, environment, *arguments):
    return _run([GIT, *arguments], repo, environment).stdout.strip()


def _fixture_compiler(path, version):
    path.parent.mkdir(parents=True)
    path.write_bytes((
        "#!" + sys.executable + "\n"
        "import hashlib, json, sys\n"
        "from pathlib import Path\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('CircuitPython " + version + " on fixture; mpy-cross emitting mpy v6.3')\n"
        "    raise SystemExit(0)\n"
        "assert len(sys.argv) == 7, sys.argv\n"
        "assert sys.argv[2] == '-s' and sys.argv[4] == '-o', sys.argv\n"
        "record = {'optimization': sys.argv[1], 'source': sys.argv[3],\n"
        "          'sha256': hashlib.sha256(Path(sys.argv[6]).read_bytes()).hexdigest()}\n"
        "Path(sys.argv[5]).write_bytes(json.dumps(record, sort_keys=True).encode() + b'\\n')\n"
    ).encode("utf-8"))
    path.chmod(0o755)
    return path


def _make_tree(tmp_path, real_compiler=None):
    # Read allowlist declarations only. Production APIs/globals are never mocked;
    # both scripts below run in their own processes against a real committed tree.
    declaration = runpy.run_path(str(REPO / "scripts/package_source_release.py"))
    source_root = declaration["SOURCE_ROOT"]
    paths = (declaration["RC_FIXED_FILES"] | {"RELEASE_NOTES-" + VERSION + ".md"}
             | {source_root + name for name in declaration["APPLICATION_SOURCES"]}
             | {declaration["BADGE_ROOT"] + name for name in declaration["BADGE_SOURCES"]})
    repo = tmp_path / "repository with spaces"
    repo.mkdir()
    environment = git_environment()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for name in ("MPY_CROSS", "MPY_CROSS_OPT_LEVEL", "MPY_CROSS_ALLOW_UNPINNED", "BASH_ENV"):
        environment.pop(name, None)
    template = tmp_path / "empty-git-template"
    hooks = tmp_path / "disabled-hooks"
    template.mkdir()
    hooks.mkdir()
    _git(repo, environment, "init", "-q", "--template=" + str(template))
    for name, value in (("user.name", "Release E2E"), ("user.email", "e2e@example.invalid"),
                        ("commit.gpgsign", "false"), ("tag.gpgsign", "false"),
                        ("core.hooksPath", str(hooks)), ("core.autocrlf", "false"),
                        ("core.excludesFile", os.devnull), ("core.attributesFile", os.devnull),
                        ("core.fsmonitor", "false")):
        _git(repo, environment, "config", name, value)
    committed = {}
    for name in sorted(paths):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        committed[name] = (("VALUE = " + repr(name) + "\n").encode("utf-8")
                           if name.endswith(".py") else ("Public fixture: " + name + "\n").encode("utf-8"))
        path.write_bytes(committed[name])
    for name in ("build_mpy.sh", "scripts/package_source_release.py", "scripts/fetch_mpy_cross.sh"):
        committed[name] = (REPO / name).read_bytes()
        (repo / name).write_bytes(committed[name])
        (repo / name).chmod(0o755)
    pin_bytes = (REPO / "tools/mpy_cross_pin.env").read_bytes()
    pins = dict(line.split("=", 1) for line in pin_bytes.decode().splitlines()
                if line and not line.startswith("#"))
    compiler = real_compiler or _fixture_compiler(
        tmp_path / "compiler tools" / "mpy-cross", pins["MPY_CROSS_VERSION"])
    compiler_hash = _digest(compiler.read_bytes())
    pin_bytes = pin_bytes.replace(pins["MPY_CROSS_LINUX_AMD64_SHA256"].encode(), compiler_hash.encode())
    committed["tools/mpy_cross_pin.env"] = pin_bytes
    (repo / "tools/mpy_cross_pin.env").write_bytes(pin_bytes)
    (repo / ".gitignore").write_bytes(b"dist/\n.badge_remote.json\n")
    _git(repo, environment, "add", ".")
    _git(repo, environment, "commit", "-qm", "Synthetic committed release inputs")
    commit = _git(repo, environment, "rev-parse", "HEAD")
    # Ignored fixture credentials exercise the real copy/allowlist boundaries.
    (repo / source_root / ".badge_remote.json").write_bytes(b"DO-NOT-PACKAGE-PRIVATE-FIXTURE")
    environment["MPY_CROSS"] = str(compiler)
    compiler_version = _run([str(compiler), "--version"], repo, environment,
                            check=False).stdout.strip()
    return {"repo": repo, "env": environment, "commit": commit, "compiler": compiler,
            "compiler_hash": compiler_hash, "compiler_version": compiler_version,
            "version": pins["MPY_CROSS_VERSION"], "committed": committed,
            "source_root": source_root}


@pytest.fixture
def release_tree(tmp_path):
    return _make_tree(tmp_path)


def _build(tree, **overrides):
    return _run([BASH, str(tree["repo"] / "build_mpy.sh")], tree["repo"],
                dict(tree["env"], **overrides))


def _package(tree, output, *, revision=None, check=True):
    result = _run([
        sys.executable, str(tree["repo"] / "scripts/package_source_release.py"),
        "--revision", revision or tree["commit"], "--version", VERSION,
        "--scope", "controller-badge-source", "--include-mpy",
        "--compiler", str(tree["compiler"]), "--compiler-sha256", tree["compiler_hash"],
        "--output", str(output),
    ], tree["repo"], tree["env"], check=check)
    return result


def _read_archive(path, commit, scope):
    with zipfile.ZipFile(path) as bundle:
        assert bundle.testzip() is None
        assert len(bundle.namelist()) == len(set(bundle.namelist()))
        assert all(name.startswith(PREFIX) for name in bundle.namelist())
        payload = {name[len(PREFIX):]: bundle.read(name) for name in bundle.namelist()}
        manifest_bytes = payload.pop("MANIFEST.json")
        manifest = json.loads(manifest_bytes)
        assert manifest["source_commit"] == commit
        assert manifest["version"] == VERSION
        assert manifest["scope"] == scope
        assert manifest["hardware_validation"] == "not-run-by-packaging"
        members = {member["path"]: member for member in manifest["members"]}
        assert set(members) == set(payload)
        for name, data in payload.items():
            assert members[name]["bytes"] == len(data)
            assert members[name]["sha256"] == _digest(data)
            info = bundle.getinfo(PREFIX + name)
            assert info.external_attr >> 16 == int(members[name]["mode"], 8)
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.compress_type == zipfile.ZIP_STORED
    return payload, manifest, manifest_bytes


def _verify_pipeline(tree, tmp_path, *, synthetic_compiler):
    _build(tree)
    info_bytes = (tree["repo"] / "dist/BUILD_INFO.txt").read_bytes()
    info_lines = info_bytes.decode().splitlines()
    assert len(info_lines) == 4
    assert dict(line.split("=", 1) for line in info_lines) == {
        "mpy_cross_pinned": tree["version"], "mpy_cross_version": tree["compiler_version"],
        "mpy_cross_opt_level": "2", "source_commit": tree["commit"],
    }
    # A local documentation edit must not substitute for its committed source.
    (tree["repo"] / "README.md").write_bytes(b"LOCAL-UNCOMMITTED-DRAFT")
    first, second = tmp_path / "first assets", tmp_path / "second assets"
    for output in (first, second):
        result = json.loads(_package(tree, output).stdout)
        assert result["source_commit"] == tree["commit"]
        assert {path.name for path in output.iterdir()} == ASSETS
        assert {record["file"] for record in result["artifacts"]} == {SOURCE_ZIP, COMPILED_ZIP}
        checksums = dict(line.split("  ", 1)[::-1]
                         for line in (output / "SHA256SUMS.txt").read_text().splitlines())
        assert set(checksums) == ASSETS - {"SHA256SUMS.txt"}
        for name, digest in checksums.items():
            assert _digest((output / name).read_bytes()) == digest
    assert all((first / name).read_bytes() == (second / name).read_bytes() for name in ASSETS)
    source, _, source_manifest = _read_archive(
        first / SOURCE_ZIP, tree["commit"], "controller-badge-source")
    assert source == tree["committed"]
    assert source_manifest == (first / "MANIFEST.json").read_bytes()
    compiled, manifest, _ = _read_archive(
        first / COMPILED_ZIP, tree["commit"], "compiled-controller-only")
    assert manifest["compiler_sha256"] == tree["compiler_hash"]
    assert compiled.pop("BUILD_INFO.txt") == info_bytes
    assert compiled.pop("LICENSE") == tree["committed"]["LICENSE"]
    generated = tree["repo"] / "dist/circuitpython"
    assert compiled == {"circuitpython/" + path.relative_to(generated).as_posix(): path.read_bytes()
                        for path in generated.rglob("*") if path.is_file()}
    for name, data in tree["committed"].items():
        if not name.startswith(tree["source_root"]):
            continue
        relative = name[len(tree["source_root"]):]
        if relative.startswith("lib/") and relative.endswith(".py"):
            compiled_bytes = compiled["circuitpython/" + relative[:-3] + ".mpy"]
            assert compiled_bytes
            if synthetic_compiler:
                assert json.loads(compiled_bytes) == {
                    "optimization": "-O2", "source": relative, "sha256": _digest(data)}
        else:
            assert compiled["circuitpython/" + relative] == data
    for payload in (source, compiled):
        assert not any(b"DO-NOT-PACKAGE-PRIVATE-FIXTURE" in data for data in payload.values())
    assert not (generated / "BUILD_INFO.txt").exists()


def test_real_build_and_rc_cli_produce_reproducible_four_asset_release(release_tree, tmp_path):
    _verify_pipeline(release_tree, tmp_path, synthetic_compiler=True)


def test_end_to_end_fixture_ignores_hostile_git_configuration(tmp_path, monkeypatch):
    unused = set_hostile_git_environment(tmp_path, monkeypatch)
    tree = _make_tree(tmp_path)
    assert _git(tree["repo"], tree["env"], "show", "-s", "--format=%an <%ae>|%cn <%ce>", tree["commit"]) == (
        "Release E2E <e2e@example.invalid>|Release E2E <e2e@example.invalid>"
    )
    assert _git(tree["repo"], tree["env"], "config", "--get", "commit.gpgsign") == "false"
    assert not (tree["repo"] / ".git/hostile-template-marker").exists()
    _verify_pipeline(tree, tmp_path, synthetic_compiler=True)
    assert all(not path.exists() for path in unused.values())


@pytest.mark.parametrize("scenario,error", [
    ("dirty-firmware", "exact committed RC revision"),
    ("later-commit", "exact committed RC revision"),
    ("unreviewed-optimization", "reviewed -O2 build"),
])
def test_build_info_writer_and_reader_enforce_revision_and_optimization(
        release_tree, tmp_path, scenario, error):
    tree = release_tree
    if scenario == "dirty-firmware":
        (tree["repo"] / tree["source_root"] / "main.py").write_bytes(b"VALUE = 'local edit'\n")
    _build(tree, **({"MPY_CROSS_OPT_LEVEL": "0"} if scenario == "unreviewed-optimization" else {}))
    revision = tree["commit"]
    info = (tree["repo"] / "dist/BUILD_INFO.txt").read_text()
    if scenario == "dirty-firmware":
        assert "source_commit=" + revision + "-dirty\n" in info
    elif scenario == "later-commit":
        (tree["repo"] / "README.md").write_bytes(b"A later committed documentation revision\n")
        _git(tree["repo"], tree["env"], "add", "README.md")
        _git(tree["repo"], tree["env"], "commit", "-qm", "Later revision after build")
        revision = _git(tree["repo"], tree["env"], "rev-parse", "HEAD")
        assert "source_commit=" + tree["commit"] + "\n" in info
    else:
        assert "mpy_cross_opt_level=0\n" in info
    output = tmp_path / "refused assets"
    result = _package(tree, output, revision=revision, check=False)
    assert result.returncode != 0
    assert error in result.stderr
    assert not output.exists()


@pytest.mark.mpy
def test_real_pinned_compiler_build_and_rc_packaging(tmp_path):
    if os.environ.get("RUN_MPY_TESTS") != "1":
        pytest.skip("Set RUN_MPY_TESTS=1 and MPY_CROSS for the real pinned compiler lane")
    candidate = os.environ.get("MPY_CROSS") or shutil.which("mpy-cross")
    if not candidate:
        pytest.skip("The actual pinned mpy-cross executable is unavailable")
    compiler = Path(candidate).resolve(strict=True)
    pins = dict(line.split("=", 1) for line in (REPO / "tools/mpy_cross_pin.env").read_text().splitlines()
                if line and not line.startswith("#"))
    assert _digest(compiler.read_bytes()) == pins["MPY_CROSS_LINUX_AMD64_SHA256"]
    _verify_pipeline(_make_tree(tmp_path, compiler), tmp_path, synthetic_compiler=False)

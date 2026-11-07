"""Exercise the public release CLI and reject ambiguous packaging requests."""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/package_source_release.py"
SPEC = importlib.util.spec_from_file_location("source_release_cli", SCRIPT)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


@pytest.mark.parametrize("missing", ["--scope", "--version"])
def test_cli_requires_explicit_scope_and_version(tmp_path, monkeypatch, capsys, missing):
    output = tmp_path / "output"
    arguments = ["package_source_release.py", "--revision", "HEAD", "--output", str(output)]
    arguments += ["--version", "v1.0.0-rc.1"] if missing == "--scope" else ["--scope", "application-source"]
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(release, "package", lambda *args, **kwargs: pytest.fail("Parser accepted an omitted required flag"))
    with pytest.raises(SystemExit) as error:
        release.main()
    assert error.value.code == 2
    assert missing in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize("scope", ["application-source", "controller-badge-source"])
@pytest.mark.parametrize("compiler_fields", [
    {"compiler": Path("missing-mpy-cross")},
    {"compiler_sha256": "0" * 64},
    {"compiler": "", "compiler_sha256": ""},
])
def test_api_refuses_orphan_compiler_fields_before_git_or_output(tmp_path, monkeypatch, scope, compiler_fields):
    output = tmp_path / "output"
    monkeypatch.setattr(release, "git", lambda *args: pytest.fail("Git read before rejecting compiler-only request"))
    with pytest.raises(ValueError, match="--include-mpy"):
        release.package("HEAD", "v1.0.0-rc.1", output, scope=scope, **compiler_fields)
    assert not output.exists()


@pytest.mark.parametrize("compiler_arguments", [
    ["--compiler", "missing-mpy-cross"],
    ["--compiler-sha256", "0" * 64],
    ["--compiler", "missing-mpy-cross", "--compiler-sha256", "0" * 64],
])
def test_cli_refuses_orphan_compiler_fields_before_package_or_output(tmp_path, monkeypatch, capsys, compiler_arguments):
    output = tmp_path / "output"
    monkeypatch.setattr(sys, "argv", [
        "package_source_release.py", "--revision", "HEAD", "--version", "v1.0.0-rc.1",
        "--scope", "controller-badge-source", "--output", str(output), *compiler_arguments,
    ])
    monkeypatch.setattr(release, "package", lambda *args, **kwargs: pytest.fail("Parser accepted orphan compiler flags"))
    with pytest.raises(SystemExit) as error:
        release.main()
    assert error.value.code == 2
    assert "--include-mpy" in capsys.readouterr().err
    assert not output.exists()


def test_only_canonical_release_entry_point_is_shipped():
    assert not (REPO / "scripts/prepare_release.py").exists()
    assert "scripts/prepare_release.py" not in release.RC_FIXED_FILES
    assert "scripts/package_source_release.py" in release.RC_FIXED_FILES


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, stdin=subprocess.DEVNULL
    ).stdout


@pytest.fixture
def cli_repository(tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Release CLI Test")
    git(repo, "config", "user.email", "release-cli-test@example.invalid")
    selected = (release.RC_FIXED_FILES | {"RELEASE_NOTES-v1.0.0-rc.1.md"}
                | {release.SOURCE_ROOT + name for name in release.APPLICATION_SOURCES}
                | {release.BADGE_ROOT + name for name in release.BADGE_SOURCES})
    for name in selected:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"# committed public CLI fixture\n")
    shutil.copyfile(SCRIPT, repo / "scripts/package_source_release.py")
    git(repo, "add", "--all")
    git(repo, "commit", "-m", "committed CLI fixture")
    commit = git(repo, "rev-parse", "HEAD").decode().strip()
    (repo / release.SOURCE_ROOT / "main.py").write_bytes(b"uncommitted change must not enter archive\n")
    return repo, commit


def invoke_cli(repo, output, *, scope="application-source", revision="HEAD", version="v1.0.0-rc.1"):
    return subprocess.run(
        [sys.executable, str(repo / "scripts/package_source_release.py"),
         "--revision", revision, "--scope", scope, "--version", version, "--output", str(output)],
        cwd=repo, capture_output=True, stdin=subprocess.DEVNULL,
    )


@pytest.mark.parametrize("scope", ["application-source", "controller-badge-source"])
def test_real_source_cli_reads_committed_fixture_and_writes_verifiable_assets(cli_repository, tmp_path, scope):
    repo, commit = cli_repository
    output = tmp_path / "output"
    process = invoke_cli(repo, output, scope=scope, revision=commit)
    assert process.returncode == 0, process.stderr.decode()
    result = json.loads(process.stdout)
    assert result["source_commit"] == commit
    archive = Path(result["archive"])
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == result["sha256"]
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        prefix = "BM83-Remote-v1.0.0-rc.1/"
        assert all(name.startswith(prefix) for name in bundle.namelist())
        manifest_bytes = bundle.read(prefix + "MANIFEST.json")
        assert manifest_bytes == Path(result["manifest"]).read_bytes()
        manifest = json.loads(manifest_bytes)
        assert manifest["source_commit"] == commit and manifest["version"] == "v1.0.0-rc.1"
        main_path = "application/main.py" if scope == "application-source" else release.SOURCE_ROOT + "main.py"
        assert bundle.read(prefix + main_path) == b"# committed public CLI fixture\n"
    for line in Path(result["checksums"]).read_text().splitlines():
        expected, name = line.split("  ", 1)
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == expected
    assert (repo / release.SOURCE_ROOT / "main.py").read_bytes().startswith(b"uncommitted change")


@pytest.mark.parametrize("arguments", [
    {"revision": "HEAD-does-not-exist"},
    {"version": "../invalid-version"},
    {"scope": "unsupported-scope"},
])
def test_real_cli_refusals_leave_no_output_directory(cli_repository, tmp_path, arguments):
    repo, _ = cli_repository
    output = tmp_path / "output"
    process = invoke_cli(repo, output, **arguments)
    assert process.returncode != 0
    assert not output.exists()


@pytest.mark.parametrize("compiler_fields", [
    {"compiler": Path("missing-mpy-cross")},
    {"compiler_sha256": "0" * 64},
    {"compiler": "", "compiler_sha256": ""},
])
def test_controller_badge_api_refuses_orphan_compiler_fields_before_source_reads(tmp_path, monkeypatch, compiler_fields):
    output = tmp_path / "output"
    monkeypatch.setattr(release, "git", lambda *args: pytest.fail("Git read before rejecting compiler-only request"))
    with pytest.raises(ValueError, match="--include-mpy"):
        release.package_controller_badge("a" * 40, "v1.0.0-rc.1", output, **compiler_fields)
    assert not output.exists()

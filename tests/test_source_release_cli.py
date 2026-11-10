"""Exercise the public release CLI and reject ambiguous packaging requests."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

from tests.release_fixture_support import (
    HOSTILE_DEFAULT_BRANCH, HOSTILE_GIT_CONFIG_NAME, git_environment, set_hostile_git_environment,
)

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
        ["git", *args], cwd=repo, check=True, capture_output=True, stdin=subprocess.DEVNULL, env=git_environment()
    ).stdout


def make_cli_repository(tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    template = tmp_path / "empty-git-template"
    hooks = tmp_path / "disabled-hooks"
    template.mkdir()
    hooks.mkdir()
    git(repo, "init", "--template=" + str(template))
    for name, value in (("user.name", "Release CLI Test"), ("user.email", "release-cli-test@example.invalid"),
                        ("commit.gpgsign", "false"), ("tag.gpgsign", "false"),
                        ("core.hooksPath", str(hooks)), ("core.autocrlf", "false"),
                        ("core.excludesFile", os.devnull), ("core.attributesFile", os.devnull),
                        ("core.fsmonitor", "false")):
        git(repo, "config", name, value)
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


@pytest.fixture
def cli_repository(tmp_path):
    return make_cli_repository(tmp_path)


def invoke_cli(repo, output, *, scope="application-source", revision="HEAD", version="v1.0.0-rc.1", environment=None):
    return subprocess.run(
        [sys.executable, str(repo / "scripts/package_source_release.py"),
         "--revision", revision, "--scope", scope, "--version", version, "--output", str(output)],
        cwd=repo, capture_output=True, stdin=subprocess.DEVNULL, env=environment or git_environment(),
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


@pytest.mark.parametrize("arguments,status", [
    ({"revision": "HEAD-does-not-exist"}, 1),
    ({"version": "../invalid-version"}, 1),
    ({"scope": "unsupported-scope"}, 2),
])
def test_real_cli_refusals_leave_no_output_directory(cli_repository, tmp_path, arguments, status):
    repo, _ = cli_repository
    output = tmp_path / "output"
    process = invoke_cli(repo, output, **arguments)
    assert b"Traceback" not in process.stderr
    assert process.returncode == status
    assert not output.exists()


CLI_ERROR = b"package_source_release.py: error: "


def assert_one_error_line(process, *fragments):
    """A refusal is one argparse-style stderr line and exit status 1, never a traceback or JSON."""
    assert b"Traceback" not in process.stderr
    lines = process.stderr.splitlines()
    assert len(lines) == 1 and lines[0].startswith(CLI_ERROR), process.stderr.decode(errors="replace")
    assert all(fragment in lines[0] for fragment in fragments), lines[0]
    assert process.returncode == 1
    assert process.stdout == b""


@pytest.mark.parametrize("case", [
    "unknown-revision", "tree-revision", "invalid-version", "mismatched-tag", "truncated-tag", "dangling-tag",
])
def test_real_cli_refusal_is_one_error_line_without_output(cli_repository, tmp_path, case):
    repo, commit = cli_repository
    arguments, fragments = {"revision": commit}, []
    if case in ("unknown-revision", "tree-revision"):
        # Git may explain this on several stderr lines; the CLI names the command on one.
        arguments["revision"] = "HEAD-does-not-exist" if case == "unknown-revision" else "HEAD^{tree}"
        # The program is named by basename: "git" here, "git.EXE" from shutil.which on Windows.
        fragments = [CLI_ERROR + b"git", b" rev-parse ", arguments["revision"].encode()]
    elif case == "invalid-version":
        arguments["version"] = "../invalid-version"
        fragments = [b"Version must be a v-prefixed semantic version"]
    elif case == "mismatched-tag":
        git(repo, "tag", "v1.0.0-rc.1", commit)
        git(repo, "commit", "--allow-empty", "-m", "later candidate")
        arguments["revision"] = "HEAD"
        fragments = [b"Version tag refs/tags/v1.0.0-rc.1 resolves to " + commit.encode(),
                     b"not requested commit " + git(repo, "rev-parse", "HEAD").strip()]
    else:
        tag = repo / ".git/refs/tags/v1.0.0-rc.1"
        tag.parent.mkdir(parents=True, exist_ok=True)
        tag.write_bytes(b"deadbeef\n" if case == "truncated-tag" else b"ref: refs/tags/missing-fixture-tag\n")
        fragments = [b"Version tag refs/tags/v1.0.0-rc.1 "]
        if case == "dangling-tag":
            fragments.append(b"does not resolve to a commit")
    output = tmp_path / "output"
    assert_one_error_line(invoke_cli(repo, output, **arguments), *fragments)
    assert not output.exists()


def test_real_cli_existing_output_refusal_is_one_error_line(cli_repository, tmp_path):
    repo, commit = cli_repository
    output = tmp_path / "output"
    output.mkdir()
    (output / "unrelated.txt").write_bytes(b"existing host file\n")
    assert_one_error_line(invoke_cli(repo, output, revision=commit))
    assert [path.name for path in output.iterdir()] == ["unrelated.txt"]
    assert (output / "unrelated.txt").read_bytes() == b"existing host file\n"


def test_real_cli_without_git_is_one_error_line(cli_repository, tmp_path):
    repo, commit = cli_repository
    search_path = tmp_path / "path-without-git"
    search_path.mkdir()
    output = tmp_path / "output"
    process = invoke_cli(repo, output, revision=commit, environment=dict(git_environment(), PATH=str(search_path)))
    assert_one_error_line(process, b"Git is required to read committed release source")
    assert not output.exists()


def test_real_cli_closed_stdout_after_success_is_not_reported_as_refusal(cli_repository, tmp_path):
    repo, commit = cli_repository
    output = tmp_path / "output"
    reader, writer = os.pipe()
    os.close(reader)
    try:
        process = subprocess.run(
            [sys.executable, str(repo / "scripts/package_source_release.py"), "--revision", commit,
             "--scope", "application-source", "--version", "v1.0.0-rc.1", "--output", str(output)],
            # Unbuffered, so the JSON write itself meets the closed pipe after package() returns.
            cwd=repo, stdout=writer, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            env=dict(git_environment(), PYTHONUNBUFFERED="1"),
        )
    finally:
        os.close(writer)
    assert output.is_dir()
    assert CLI_ERROR not in process.stderr


def run_main_with_failure(monkeypatch, tmp_path, failure):
    monkeypatch.setattr(sys, "argv", [
        "package_source_release.py", "--revision", "HEAD", "--version", "v1.0.0-rc.1",
        "--scope", "application-source", "--output", str(tmp_path / "output"),
    ])

    def refuse(*args, **kwargs):
        raise failure

    monkeypatch.setattr(release, "package", refuse)
    release.main()


@pytest.mark.parametrize("failure,message", [
    (subprocess.CalledProcessError(128, ["/fixture/bin/git", "--no-pager", "rev-parse", "x^{commit}"],
                                   stderr=b"error: first fixture line\n\n\tfatal: second fixture line\n"),
     "git --no-pager rev-parse x^{commit} failed with exit status 128: error: first fixture line; fatal: second fixture line"),
    (subprocess.CalledProcessError(3, ["/fixture/tools/mpy-cross", "-O2", "-s", "lib/module.py"], stderr=None),
     "mpy-cross -O2 -s lib/module.py failed with exit status 3"),
    (ValueError("first fixture reason\nsecond fixture reason"), "first fixture reason; second fixture reason"),
    (FileExistsError(17, "File exists", "fixture-output"), "[Errno 17] File exists: 'fixture-output'"),
    (subprocess.CalledProcessError(128, ["/fixture/bin/git", "--no-pager", "rev-parse", "x^{commit}"],
                                   stderr=b"fatal: bad revision 'caf\xe9'\n"),
     "git --no-pager rev-parse x^{commit} failed with exit status 128: fatal: bad revision 'caf\ufffd'"),
    (ValueError(), "ValueError"),
], ids=["git-multiline-stderr", "compiler-without-stderr", "multiline-refusal", "existing-output",
        "git-undecodable-stderr", "empty-refusal"])
def test_cli_reports_refusals_and_failed_commands_on_one_line(tmp_path, monkeypatch, capsys, failure, message):
    with pytest.raises(SystemExit) as error:
        run_main_with_failure(monkeypatch, tmp_path, failure)
    assert error.value.code == 1
    # Python 3.14 derives prog from __main__.__spec__ ("python -m pytest" under python -m pytest).
    prog = argparse.ArgumentParser().prog
    assert capsys.readouterr() == ("", prog + ": error: " + message + "\n")


@pytest.mark.parametrize("failure", [
    KeyError("MPY_CROSS_LINUX_AMD64_SHA256"), TypeError("fixture defect"), RuntimeError("fixture defect"),
    UnicodeDecodeError("utf-8", b"\xe9", 0, 1, "invalid continuation byte"),
], ids=["KeyError", "TypeError", "RuntimeError-with-git", "UnicodeDecodeError"])
def test_cli_keeps_tracebacks_for_unexpected_errors(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(release, "GIT_EXECUTABLE", "/fixture/bin/git")
    with pytest.raises(type(failure)) as error:
        run_main_with_failure(monkeypatch, tmp_path, failure)
    assert error.value is failure


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


@pytest.mark.parametrize("compiler_arguments", [
    [], ["--compiler", "missing-mpy-cross"], ["--compiler-sha256", "0" * 64],
    ["--compiler", "missing-mpy-cross", "--compiler-sha256", "invalid"],
])
def test_cli_requires_complete_compiler_options_before_package(tmp_path, monkeypatch, capsys, compiler_arguments):
    output = tmp_path / "output"
    monkeypatch.setattr(sys, "argv", [
        "package_source_release.py", "--revision", "HEAD", "--version", "v1.0.0-rc.1",
        "--scope", "controller-badge-source", "--output", str(output), "--include-mpy", *compiler_arguments,
    ])
    monkeypatch.setattr(release, "package", lambda *args, **kwargs: pytest.fail("Package reached before compiler validation"))
    with pytest.raises(SystemExit) as error:
        release.main()
    assert error.value.code == 2
    assert "--include-mpy requires" in capsys.readouterr().err
    assert not output.exists()


def test_git_environment_retains_only_its_four_safe_git_variables(tmp_path, monkeypatch):
    set_hostile_git_environment(tmp_path, monkeypatch)
    environment = git_environment()
    assert {name: value for name, value in environment.items() if name.upper().startswith("GIT_")} == {
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
    }


def test_cli_fixture_ignores_hostile_git_configuration(tmp_path, monkeypatch):
    unused = set_hostile_git_environment(tmp_path, monkeypatch)
    repo, commit = make_cli_repository(tmp_path)
    assert git(repo, "show", "-s", "--format=%an <%ae>|%cn <%ce>", commit).strip() == (
        b"Release CLI Test <release-cli-test@example.invalid>|Release CLI Test <release-cli-test@example.invalid>"
    )
    assert git(repo, "config", "--get", "commit.gpgsign").strip() == b"false"
    assert git(repo, "symbolic-ref", "--short", "HEAD").decode().strip() != HOSTILE_DEFAULT_BRANCH
    assert HOSTILE_GIT_CONFIG_NAME.encode() not in git(repo, "config", "--list", "--show-origin")
    assert not (repo / ".git/hostile-template-marker").exists()
    process = invoke_cli(repo, tmp_path / "output", revision=commit)
    assert process.returncode == 0, process.stderr.decode()
    assert all(not path.exists() for path in unused.values())

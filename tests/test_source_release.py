"""Release privacy boundaries, committed-byte provenance and reproducibility."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

from tests.release_fixture_support import git_environment, set_hostile_git_environment

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("source_release", REPO / "scripts/package_source_release.py")
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def git(repo, *args, input_bytes=None):
    environment = git_environment()
    return subprocess.run(
        ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false",
         "-c", "core.attributesFile=" + os.devnull, "-c", "core.excludesFile=" + os.devnull, *args],
        cwd=repo, check=True, capture_output=True, input=input_bytes, env=environment,
    ).stdout


@pytest.fixture
def isolated_git_environment(monkeypatch):
    environment = git_environment()
    for key in list(os.environ):
        if key.upper().startswith("GIT_"):
            monkeypatch.delenv(key)
    for key, value in environment.items():
        if key.upper().startswith("GIT_"):
            monkeypatch.setenv(key, value)


@pytest.fixture
def committed_source(tmp_path, monkeypatch, isolated_git_environment):
    repo = tmp_path / "repository"
    repo.mkdir()

    git(repo, "init")
    git(repo, "config", "user.name", "Release Test")
    git(repo, "config", "user.email", "release-test@example.invalid")
    for name in release.APPLICATION_SOURCES:
        path = repo / release.SOURCE_ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# committed example\n", encoding="utf-8")
    (repo / "LICENSE").write_text("MIT test fixture\n", encoding="utf-8")
    script = repo / "scripts/package_source_release.py"
    script.parent.mkdir()
    script.write_bytes((REPO / "scripts/package_source_release.py").read_bytes())
    private_paths = ["settings.toml", "secrets.py", ".artwork_wifi.json", ".badge_remote.json",
                     ".badge_windows_launch.key", ".bm83_windows_companion.json", ".bm83_windows_receiver.json",
                     "lib/secrets.py", "lib/remote/private_profile.py"]
    for name in private_paths:
        (repo / release.SOURCE_ROOT / name).write_text("DO-NOT-PACKAGE-PRIVATE-DATA", encoding="utf-8")
    git(repo, "add", "LICENSE", "firmware", "scripts/package_source_release.py")
    git(repo, "commit", "-m", "release fixture")
    commit = git(repo, "rev-parse", "HEAD").decode().strip()
    # A working copy modification must never enter the asset for this commit.
    (repo / release.SOURCE_ROOT / "main.py").write_text("UNCOMMITTED-PRIVATE-DATA", encoding="utf-8")
    monkeypatch.setattr(release, "REPO", repo)
    return repo, commit


def test_committed_source_excludes_private_files_and_is_reproducible(committed_source, tmp_path):
    repo, commit = committed_source
    first = release.package(commit, "v0.1.0", tmp_path / "first")
    second = release.package(commit, "v0.1.0", tmp_path / "second")
    archive = Path(first["archive"])
    assert archive.read_bytes() == Path(second["archive"]).read_bytes()
    assert first["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert all(name.startswith("BM83-Remote-v0.1.0/") for name in bundle.namelist())
        assert not any(b"PRIVATE-DATA" in bundle.read(name) for name in bundle.namelist())
        assert not any(name.endswith("/settings.toml") or "/secrets.py" in name for name in bundle.namelist())
        assert "BM83-Remote-v0.1.0/examples/settings.example.toml" in bundle.namelist()
        manifest = json.loads(bundle.read("BM83-Remote-v0.1.0/MANIFEST.json"))
        assert manifest["source_commit"] == commit
        assert len(manifest["inputs"]) == len(release.APPLICATION_SOURCES)
        for info in bundle.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.create_system == 3
            assert info.external_attr >> 16 == 0o100644
            assert info.compress_type == zipfile.ZIP_STORED
        for member in manifest["members"]:
            data = bundle.read("BM83-Remote-v0.1.0/" + member["path"])
            assert hashlib.sha256(data).hexdigest() == member["sha256"]
            assert len(data) == member["bytes"]
    assert (repo / release.SOURCE_ROOT / "main.py").read_text() == "UNCOMMITTED-PRIVATE-DATA"


def test_preview_supports_revisions_before_host_management(committed_source, tmp_path):
    repo, _ = committed_source
    git(repo, "rm", "--cached", "--", *(release.SOURCE_ROOT + name for name in release.HOST_MANAGEMENT_SOURCES))
    git(repo, "commit", "-m", "legacy source preview")
    result = release.package("HEAD", "v0.1.0", tmp_path / "legacy")
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert {item["source"] for item in manifest["inputs"]} == {
        release.SOURCE_ROOT + name for name in release.BASE_APPLICATION_SOURCES
    }


@pytest.mark.parametrize("path", ["LICENSE", release.SOURCE_ROOT + "lib/bm83/bm83.py"])
def test_incomplete_application_or_license_refused(committed_source, tmp_path, path):
    repo, _ = committed_source
    git(repo, "rm", "--cached", "--", path)
    git(repo, "commit", "-m", "incomplete source")
    destination = tmp_path / "output"
    with pytest.raises(ValueError, match="missing required release source"):
        release.package("HEAD", "v0.1.0", destination)
    assert not destination.exists()


@pytest.mark.parametrize("path", ["LICENSE", release.SOURCE_ROOT + "main.py"])
def test_committed_symlink_refused_without_following_target(committed_source, tmp_path, path):
    repo, _ = committed_source
    # Construct a real Git symlink even on Windows without symlink privileges.
    target = git(repo, "hash-object", "-w", "--stdin", input_bytes=b"../../private-key").decode().strip()
    git(repo, "update-index", "--cacheinfo", "120000," + target + "," + path)
    git(repo, "commit", "-m", "symlink source")
    destination = tmp_path / "output"
    with pytest.raises(ValueError, match="ordinary committed files"):
        release.package("HEAD", "v0.1.0", destination)
    assert not destination.exists()


def test_existing_outputs_not_overwritten(committed_source, tmp_path):
    _, commit = committed_source
    destination = tmp_path / "existing"
    destination.mkdir()
    preserved = destination / "BM83-Remote-v0.1.0-application-source.zip"
    preserved.write_bytes(b"unrelated existing artifact")
    with pytest.raises(FileExistsError):
        release.package(commit, "v0.1.0", destination)
    assert preserved.read_bytes() == b"unrelated existing artifact"
    assert not (destination / "MANIFEST.json").exists()


def test_replaced_git_commit_cannot_change_declared_source(committed_source, tmp_path):
    repo, commit = committed_source
    original = release.package(commit, "v0.1.0", tmp_path / "original")
    git(repo, "add", "firmware/circuitpython/main.py")
    git(repo, "commit", "-m", "different source")
    replacement = git(repo, "rev-parse", "HEAD").decode().strip()
    git(repo, "replace", commit, replacement)
    actual = release.package(commit, "v0.1.0", tmp_path / "after-replace")
    assert Path(original["archive"]).read_bytes() == Path(actual["archive"]).read_bytes()


def test_checkout_line_endings_do_not_change_committed_asset(committed_source, tmp_path):
    repo, commit = committed_source
    first = release.package(commit, "v0.1.0", tmp_path / "lf")
    git(repo, "config", "core.autocrlf", "true")
    for name in release.APPLICATION_SOURCES:
        (repo / release.SOURCE_ROOT / name).write_bytes(b"# working copy with CRLF\r\n")
    second = release.package(commit, "v0.1.0", tmp_path / "crlf")
    assert Path(first["archive"]).read_bytes() == Path(second["archive"]).read_bytes()


@pytest.mark.parametrize("version", ["../release", "v0.1.0/../../escape", "v0.1.0\n", "latest"])
def test_invalid_version_rejected_without_writing(tmp_path, version):
    destination = tmp_path / "output"
    with pytest.raises(ValueError, match="semantic version"):
        release.package("HEAD", version, destination)
    assert not destination.exists()


@pytest.fixture
def committed_rc(committed_source):
    repo, _ = committed_source
    git(repo, "checkout", "--", release.SOURCE_ROOT + "main.py")
    paths = (release.RC_FIXED_FILES | {"RELEASE_NOTES-v1.0.0-rc.1.md"}
             | {release.BADGE_ROOT + name for name in release.BADGE_SOURCES})
    for name in paths:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name != "scripts/package_source_release.py":
            path.write_bytes(b"public committed release fixture\n")
    private = repo / release.BADGE_ROOT / "apps/bm83_remote/.bm83_windows_receiver.json"
    private.write_bytes(b"DO-NOT-PACKAGE-PRIVATE-DATA")
    unexpected = repo / release.BADGE_ROOT / "apps/bm83_remote/new_unreviewed.py"
    unexpected.write_bytes(b"DO-NOT-PACKAGE-PRIVATE-DATA")
    git(repo, "add", "--all")
    git(repo, "commit", "-m", "controller and badge RC fixture")
    return repo, git(repo, "rev-parse", "HEAD").decode().strip()


def test_rc_explicit_allowlist_preserves_committed_bytes_and_modes(committed_rc, tmp_path):
    repo, _ = committed_rc
    git(repo, "update-index", "--chmod=+x", "build_mpy.sh")
    git(repo, "commit", "-m", "executable build helper")
    commit = git(repo, "rev-parse", "HEAD").decode().strip()
    (repo / "README.md").write_text("UNCOMMITTED-PRIVATE-DATA", encoding="utf-8")
    first = release.package(commit, "v1.0.0-rc.1", tmp_path / "first", scope="controller-badge-source")
    second = release.package(commit, "v1.0.0-rc.1", tmp_path / "second", scope="controller-badge-source")
    assert Path(first["archive"]).read_bytes() == Path(second["archive"]).read_bytes()
    prefix = "BM83-Remote-v1.0.0-rc.1/"
    with zipfile.ZipFile(first["archive"]) as bundle:
        assert bundle.testzip() is None
        assert all(name.startswith(prefix) for name in bundle.namelist())
        assert all(b"PRIVATE-DATA" not in bundle.read(name) for name in bundle.namelist())
        assert prefix + "tools/bm83-windows-volume-host.py" in bundle.namelist()
        assert prefix + "tools/windows_volume_app_receiver.py" in bundle.namelist()
        assert prefix + "firmware/circuitpython/lib/utils/phase1_metrics.py" in bundle.namelist()
        assert bundle.getinfo(prefix + "build_mpy.sh").external_attr >> 16 == 0o100755
        manifest = json.loads(bundle.read(prefix + "MANIFEST.json"))
        assert manifest["source_commit"] == commit
        assert manifest["scope"] == "controller-badge-source"
        assert Path(first["manifest"]).read_bytes() == bundle.read(prefix + "MANIFEST.json")
        for member in manifest["members"]:
            assert hashlib.sha256(bundle.read(prefix + member["path"])).hexdigest() == member["sha256"]
    assert (repo / "README.md").read_text() == "UNCOMMITTED-PRIVATE-DATA"


@pytest.mark.parametrize("path", ["tools/windows_volume_app_receiver.py", "addons/universe-badge/apps/bm83_remote/models.py"])
def test_rc_missing_selected_inputs_refused(committed_rc, tmp_path, path):
    repo, _ = committed_rc
    git(repo, "rm", "--cached", "--", path)
    git(repo, "commit", "-m", "incomplete RC")
    with pytest.raises(ValueError, match="missing required release source"):
        release.package("HEAD", "v1.0.0-rc.1", tmp_path / "output", scope="controller-badge-source")
    assert not (tmp_path / "output").exists()


def test_rc_committed_symlink_refused(committed_rc, tmp_path):
    repo, _ = committed_rc
    target = git(repo, "hash-object", "-w", "--stdin", input_bytes=b"../../private-key").decode().strip()
    git(repo, "update-index", "--cacheinfo", "120000," + target + ",README.md")
    git(repo, "commit", "-m", "RC symlink")
    with pytest.raises(ValueError, match="ordinary committed files"):
        release.package("HEAD", "v1.0.0-rc.1", tmp_path / "output", scope="controller-badge-source")
    assert not (tmp_path / "output").exists()


def test_rc_replacement_objects_and_existing_outputs_refused(committed_rc, tmp_path):
    repo, commit = committed_rc
    first = release.package(commit, "v1.0.0-rc.1", tmp_path / "first", scope="controller-badge-source")
    (repo / "README.md").write_text("UNCOMMITTED-PRIVATE-DATA", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "different RC source")
    git(repo, "replace", commit, git(repo, "rev-parse", "HEAD").decode().strip())
    second = release.package(commit, "v1.0.0-rc.1", tmp_path / "second", scope="controller-badge-source")
    assert Path(first["archive"]).read_bytes() == Path(second["archive"]).read_bytes()
    with pytest.raises(FileExistsError):
        release.package(commit, "v1.0.0-rc.1", tmp_path / "first", scope="controller-badge-source")
    assert Path(first["archive"]).read_bytes() == Path(second["archive"]).read_bytes()


@pytest.mark.parametrize("path", ["../private", "C:/private", "lib\\secrets.py", ".env",
                                 ".badge_windows_launch.key", ".bm83_windows_companion.json",
                                 ".bm83_windows_receiver.json", "nested/SETTINGS.TOML"])
def test_private_or_unsafe_archive_paths_rejected(path):
    with pytest.raises(ValueError, match="private or unsafe"):
        release.checked(path, b"public bytes")


@pytest.mark.parametrize("header", [b"-----BEGIN PRIVATE KEY-----", b"-----BEGIN RSA PRIVATE KEY-----",
                                   b"-----BEGIN ENCRYPTED PRIVATE KEY-----"])
def test_private_key_blocks_rejected(header):
    with pytest.raises(ValueError, match="private-key content"):
        release.checked("README.md", b"public text\n" + header + b"\nprivate")


@pytest.fixture
def compiled_tree(tmp_path, monkeypatch):
    repo = tmp_path / "repository"
    directory = repo / "dist/circuitpython/lib"
    directory.mkdir(parents=True)
    monkeypatch.setattr(release, "REPO", repo)
    compiler = tmp_path / "mpy-cross"
    compiler.write_bytes(b"fixture compiler binary")
    compiler_hash = hashlib.sha256(compiler.read_bytes()).hexdigest()
    commit = "a" * 40
    source = {
        "LICENSE": b"MIT fixture\n",
        "tools/mpy_cross_pin.env": (
            "MPY_CROSS_VERSION=10.3.1\nMPY_CROSS_LINUX_AMD64_SHA256=" + compiler_hash + "\n"
        ).encode(),
        release.SOURCE_ROOT + "main.py": b"# source entrypoint\n",
        release.SOURCE_ROOT + "boot.py": b"# early settings\n",
        release.SOURCE_ROOT + "settings.example.toml": b"# inactive settings\n",
        release.SOURCE_ROOT + "lib/module.py": b"print('committed module')\n",
    }
    for name in ("main.py", "boot.py", "settings.example.toml"):
        (directory.parent / name).write_bytes(source[release.SOURCE_ROOT + name])
    (directory / "module.mpy").write_bytes(b"compiled:" + source[release.SOURCE_ROOT + "lib/module.py"])
    version = "CircuitPython 10.3.1 on 2026-09-14; mpy-cross emitting mpy v6.3"
    metadata = {
        "mpy_cross_pinned": "10.3.1", "mpy_cross_version": version,
        "mpy_cross_opt_level": "2", "source_commit": commit,
    }
    info_path = repo / "dist/BUILD_INFO.txt"
    info_path.write_text("".join(key + "=" + value + "\n" for key, value in metadata.items()), encoding="utf-8")

    def run_compiler(args, **kwargs):
        assert args[0] == str(compiler.resolve())
        if args[1:] == ["--version"]:
            return subprocess.CompletedProcess(args, 0, stdout=version.encode())
        assert args[1:4] == ["-O2", "-s", "lib/module.py"]
        Path(args[5]).write_bytes(b"compiled:" + Path(args[6]).read_bytes())
        return subprocess.CompletedProcess(args, 0, stdout=b"")

    monkeypatch.setattr(release.subprocess, "run", run_compiler)
    return repo, commit, source, compiler, compiler_hash, metadata


def test_compiled_release_recompiles_exact_committed_sources(compiled_tree):
    repo, commit, source, compiler, compiler_hash, _ = compiled_tree
    result = release.compiled_files(commit, source, compiler, compiler_hash)
    assert result["circuitpython/lib/module.mpy"] == b"compiled:" + source[release.SOURCE_ROOT + "lib/module.py"]
    assert result["circuitpython/main.py"] == source[release.SOURCE_ROOT + "main.py"]
    assert b"source_commit=" + commit.encode() in result["BUILD_INFO.txt"]
    assert not any(name.endswith("settings.toml") for name in result)


@pytest.mark.parametrize("field,value,message", [
    ("source_commit", "b" * 40, "exact committed RC revision"),
    ("mpy_cross_pinned", "11.0.0", "pinned CircuitPython compiler"),
    ("mpy_cross_version", "forged metadata", "pinned CircuitPython compiler"),
    ("mpy_cross_opt_level", "0", "reviewed -O2"),
])
def test_compiled_release_requires_exact_build_metadata(compiled_tree, field, value, message):
    repo, commit, source, compiler, compiler_hash, metadata = compiled_tree
    metadata[field] = value
    (repo / "dist/BUILD_INFO.txt").write_text(
        "".join(key + "=" + value + "\n" for key, value in metadata.items()), encoding="utf-8"
    )
    with pytest.raises(ValueError, match=message):
        release.compiled_files(commit, source, compiler, compiler_hash)


def test_compiled_release_rejects_unpinned_and_substituted_compilers(compiled_tree):
    _, commit, source, compiler, compiler_hash, _ = compiled_tree
    with pytest.raises(ValueError, match="pinned Linux amd64 compiler"):
        release.compiled_files(commit, source, compiler, "0" * 64)
    compiler.write_bytes(b"changed executable")
    with pytest.raises(ValueError, match="observed SHA-256"):
        release.compiled_files(commit, source, compiler, compiler_hash)


@pytest.mark.parametrize("path,data,message", [
    ("main.py", b"different entrypoint", "Entrypoint or asset differs"),
    ("lib/module.mpy", b"different compiled code", "Compiled module differs"),
    ("lib/module.mpy", b"", "Compiled module differs"),
    ("settings.toml", b"private", "exact allowlisted source file set"),
    (".bm83_windows_receiver.json", b"private", "exact allowlisted source file set"),
])
def test_compiled_release_rejects_changed_or_private_payloads(compiled_tree, path, data, message):
    repo, commit, source, compiler, compiler_hash, _ = compiled_tree
    (repo / "dist/circuitpython" / path).write_bytes(data)
    with pytest.raises(ValueError, match=message):
        release.compiled_files(commit, source, compiler, compiler_hash)


def test_application_profile_refuses_compiled_assets(committed_source, tmp_path):
    _, commit = committed_source
    with pytest.raises(ValueError, match="controller-badge-source scope"):
        release.package(commit, "v1.0.0-rc.1", tmp_path / "output", include_mpy=True)
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("extra", ["wifi_password=private\n", "source_commit=" + "a" * 40 + "\n", "private comment\n"])
def test_compiled_release_refuses_unexpected_build_metadata(compiled_tree, extra):
    repo, commit, source, compiler, compiler_hash, _ = compiled_tree
    info = repo / "dist/BUILD_INFO.txt"
    info.write_bytes(info.read_bytes() + extra.encode())
    with pytest.raises(ValueError, match="Unexpected compiled build metadata fields"):
        release.compiled_files(commit, source, compiler, compiler_hash)


def load_executing_packager(path, repo):
    spec = importlib.util.spec_from_file_location("fixture_executing_release", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.REPO = repo
    return module


@pytest.mark.parametrize("entry_point", ["package", "package_controller_badge"])
@pytest.mark.parametrize("compiler_fields", [
    {}, {"compiler": Path("missing-mpy-cross")}, {"compiler_sha256": "0" * 64},
    {"compiler": Path("missing-mpy-cross"), "compiler_sha256": "not-a-digest"},
])
def test_compiled_options_required_before_any_git_or_source_reads(tmp_path, monkeypatch, entry_point, compiler_fields):
    output = tmp_path / "output"
    monkeypatch.setattr(release, "git", lambda *args: pytest.fail("Git accessed before compiler arguments were validated"))
    options = {"scope": "controller-badge-source"} if entry_point == "package" else {}
    with pytest.raises(ValueError, match="--include-mpy requires"):
        getattr(release, entry_point)("a" * 40, "v1.0.0-rc.1", output, include_mpy=True,
                                      **options, **compiler_fields)
    assert not output.exists()


@pytest.mark.parametrize("entry_point", ["package", "package_controller_badge"])
@pytest.mark.parametrize("source_kind", ["missing", "symlink"])
def test_release_ref_requires_ordinary_committed_packager(committed_source, tmp_path, entry_point, source_kind):
    repo, _ = committed_source
    path = "scripts/package_source_release.py"
    if source_kind == "missing":
        git(repo, "rm", "--cached", "--", path)
    else:
        target = git(repo, "hash-object", "-w", "--stdin", input_bytes=b"../../private-tool").decode().strip()
        git(repo, "update-index", "--cacheinfo", "120000," + target + "," + path)
    git(repo, "commit", "-m", "invalid packager provenance")
    commit = git(repo, "rev-parse", "HEAD").decode().strip()
    output = tmp_path / "output"
    options = {"scope": "controller-badge-source"} if entry_point == "package" else {}
    with pytest.raises(ValueError, match="committed packager"):
        getattr(release, entry_point)(commit, "v1.0.0-rc.1", output, **options)
    assert not output.exists()


def test_changed_historical_allowlist_requires_its_own_tagged_tool(committed_rc, tmp_path):
    repo, _ = committed_rc
    script = repo / "scripts/package_source_release.py"
    current = script.read_bytes()
    historical = current.replace(b'    "tools/mpy_cross_pin.env",',
                                 b'    "scripts/prepare_release.py", "tools/mpy_cross_pin.env",', 1)
    assert historical != current
    script.write_bytes(historical)
    (repo / "scripts/prepare_release.py").write_bytes(b"# historical compatibility entry point\n")
    git(repo, "add", "scripts")
    git(repo, "commit", "-m", "historical tag with compatibility entry point in allowlist")
    git(repo, "tag", "fixture-historical-release")
    commit = git(repo, "rev-parse", "HEAD").decode().strip()
    output = tmp_path / "new-tool-output"
    with pytest.raises(ValueError, match="Executing packager differs"):
        release.package("fixture-historical-release", "v1.0.0-rc.1", output, scope="controller-badge-source")
    assert not output.exists()
    historical_tool = load_executing_packager(script, repo)
    first = historical_tool.package(commit, "v1.0.0-rc.1", tmp_path / "own-tag-first", scope="controller-badge-source")
    second = historical_tool.package(commit, "v1.0.0-rc.1", tmp_path / "own-tag-second", scope="controller-badge-source")
    assert Path(first["archive"]).read_bytes() == Path(second["archive"]).read_bytes()
    with zipfile.ZipFile(first["archive"]) as bundle:
        assert "BM83-Remote-v1.0.0-rc.1/scripts/prepare_release.py" in bundle.namelist()


def test_actual_executing_module_must_match_even_when_repo_script_matches_ref(committed_source, tmp_path):
    repo, commit = committed_source
    script = tmp_path / "different-executing-tool.py"
    canonical = (repo / "scripts/package_source_release.py").read_bytes()
    changed = canonical.replace(b"APPLICATION_SOURCES = BASE_APPLICATION_SOURCES | HOST_MANAGEMENT_SOURCES",
                                b'APPLICATION_SOURCES = BASE_APPLICATION_SOURCES | HOST_MANAGEMENT_SOURCES | {"new.py"}', 1)
    assert changed != canonical
    script.write_bytes(changed)
    module = load_executing_packager(script, repo)
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="Executing packager differs"):
        module.package(commit, "v0.1.0", output)
    assert not output.exists()


@pytest.mark.parametrize("scope", ["application-source", "controller-badge-source"])
def test_crlf_checkout_of_matching_tagged_packager_preserves_archive_bytes(committed_rc, tmp_path, scope):
    repo, commit = committed_rc
    first = release.package(commit, "v1.0.0-rc.1", tmp_path / "lf", scope=scope)
    script = tmp_path / "crlf-executing-tool.py"
    canonical = (repo / "scripts/package_source_release.py").read_bytes().replace(b"\r\n", b"\n")
    script.write_bytes(canonical.replace(b"\n", b"\r\n"))
    module = load_executing_packager(script, repo)
    second = module.package(commit, "v1.0.0-rc.1", tmp_path / "crlf", scope=scope)
    assert Path(first["archive"]).read_bytes() == Path(second["archive"]).read_bytes()


@pytest.mark.parametrize("entry_point,scope", [
    ("package", "application-source"), ("package", "controller-badge-source"),
    ("package_controller_badge", None),
])
@pytest.mark.parametrize("annotated", [False, True])
def test_existing_version_tag_must_peel_to_requested_commit(committed_rc, tmp_path, entry_point, scope, annotated):
    repo, commit = committed_rc
    version = "v1.0.0-rc.1"
    if annotated:
        git(repo, "tag", "-a", version, "-m", "annotated release fixture", commit)
        assert git(repo, "rev-parse", "refs/tags/" + version).decode().strip() != commit
    else:
        git(repo, "tag", version, commit)
    options = {"scope": scope} if scope is not None else {}
    result = getattr(release, entry_point)("HEAD", version, tmp_path / "output", **options)
    assert result["source_commit"] == commit
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["source_commit"] == commit and manifest["version"] == version


@pytest.mark.parametrize("entry_point,scope", [
    ("package", "application-source"), ("package", "controller-badge-source"),
    ("package_controller_badge", None),
])
@pytest.mark.parametrize("annotated", [False, True])
@pytest.mark.parametrize("legacy_git", [False, True])
def test_existing_version_tag_mismatch_refused_before_source_or_output(committed_rc, tmp_path, monkeypatch,
                                                                     entry_point, scope, annotated, legacy_git):
    repo, tagged_commit = committed_rc
    version = "v1.0.0-rc.1"
    if annotated:
        git(repo, "tag", "-a", version, "-m", "annotated release fixture", tagged_commit)
    else:
        git(repo, "tag", version, tagged_commit)
    (repo / "release-context.txt").write_bytes(b"different committed context\n")
    git(repo, "add", "release-context.txt")
    git(repo, "commit", "-m", "different candidate commit")
    requested_commit = git(repo, "rev-parse", "HEAD").decode().strip()
    original_git = release.git

    def references_only(*arguments):
        if arguments[0] not in ("rev-parse", "show-ref"):
            pytest.fail("Source read before refusing a mismatched version tag")
        if legacy_git and arguments[:2] == ("show-ref", "--exists"):
            raise subprocess.CalledProcessError(129, arguments, stderr=b"unknown option exists")
        return original_git(*arguments)

    monkeypatch.setattr(release, "git", references_only)
    output = tmp_path / "output"
    options = {"scope": scope} if scope is not None else {}
    with pytest.raises(ValueError, match="Version tag .*not requested commit") as error:
        getattr(release, entry_point)("HEAD", version, output, **options)
    assert "refs/tags/" + version in str(error.value)
    assert tagged_commit in str(error.value) and requested_commit in str(error.value)
    assert not output.exists()


@pytest.mark.parametrize("entry_point,scope", [
    ("package", "application-source"), ("package", "controller-badge-source"),
    ("package_controller_badge", None),
])
def test_untagged_version_allowed_even_when_same_named_branch_differs(committed_rc, tmp_path, entry_point, scope):
    repo, commit = committed_rc
    version = "v1.0.0-rc.1"
    git(repo, "branch", version, "HEAD^")
    options = {"scope": scope} if scope is not None else {}
    result = getattr(release, entry_point)("HEAD", version, tmp_path / "output", **options)
    assert result["source_commit"] == commit
    assert Path(result["archive"]).is_file()


@pytest.mark.parametrize("include_mpy", [False, True])
def test_unknown_scope_has_its_own_diagnostic_before_git(tmp_path, monkeypatch, include_mpy):
    monkeypatch.setattr(release, "git", lambda *args: pytest.fail("Git accessed for an unknown release scope"))
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="Unknown release scope") as error:
        release.package("HEAD", "v1.0.0-rc.1", output, scope="unknown-scope", include_mpy=include_mpy)
    message = str(error.value)
    assert "unknown-scope" in message
    assert "application-source" in message and "controller-badge-source" in message
    assert "Compiled assets" not in message
    assert not output.exists()


@pytest.mark.parametrize("entry_point,scope", [
    ("package", "application-source"), ("package", "controller-badge-source"),
    ("package_controller_badge", None),
])
@pytest.mark.parametrize("returncode", [1, 128])
def test_tag_probe_errors_are_not_treated_as_untagged(committed_rc, tmp_path, monkeypatch,
                                                   entry_point, scope, returncode):
    _, commit = committed_rc
    original_git = release.git
    probes = []

    def failed_tag_probe(*arguments):
        if arguments[0] == "show-ref":
            probes.append(arguments)
            raise subprocess.CalledProcessError(returncode, arguments, stderr=b"fixture tag-probe error")
        if arguments[0] != "rev-parse":
            pytest.fail("Source read after a failed tag probe")
        return original_git(*arguments)

    monkeypatch.setattr(release, "git", failed_tag_probe)
    output = tmp_path / "output"
    options = {"scope": scope} if scope is not None else {}
    with pytest.raises(ValueError, match="Version tag .* probe failed") as error:
        getattr(release, entry_point)(commit, "v1.0.0-rc.1", output, **options)
    assert "refs/tags/v1.0.0-rc.1" in str(error.value)
    assert "fixture tag-probe error" in str(error.value)
    assert probes == [("show-ref", "--exists", "refs/tags/v1.0.0-rc.1")]
    assert not output.exists()


@pytest.mark.parametrize("entry_point,scope", [
    ("package", "application-source"), ("package", "controller-badge-source"),
    ("package_controller_badge", None),
])
@pytest.mark.parametrize("present", [False, True])
def test_exists_probe_present_and_missing_results(committed_rc, tmp_path, monkeypatch,
                                                 entry_point, scope, present):
    _, commit = committed_rc
    tag_ref = "refs/tags/v1.0.0-rc.1"
    original_git = release.git
    probes = []

    def modern_probe(*arguments):
        if arguments[0] == "show-ref":
            probes.append(arguments)
            if arguments[1] == "--exists":
                if not present:
                    raise subprocess.CalledProcessError(2, arguments, stderr=b"")
                return b""
        return original_git(*arguments)

    monkeypatch.setattr(release, "git", modern_probe)
    output = tmp_path / "output"
    options = {"scope": scope} if scope is not None else {}
    if present:
        # No file names the tag, so only the probe's answer sends it to the exact peel.
        with pytest.raises(ValueError, match="Version tag refs/tags/v1.0.0-rc.1 does not resolve to a commit: "):
            getattr(release, entry_point)(commit, "v1.0.0-rc.1", output, **options)
        assert probes == [("show-ref", "--exists", tag_ref), ("show-ref", "--verify", "--hash", tag_ref)]
        assert not output.exists()
    else:
        result = getattr(release, entry_point)(commit, "v1.0.0-rc.1", output, **options)
        assert result["source_commit"] == commit and Path(result["archive"]).is_file()
        assert set(probes) == {("show-ref", "--exists", tag_ref)}


@pytest.mark.parametrize("entry_point,scope", [
    ("package", "application-source"), ("package", "controller-badge-source"),
    ("package_controller_badge", None),
])
def test_legacy_probe_error_retains_git_stderr(committed_rc, tmp_path, monkeypatch, entry_point, scope):
    _, commit = committed_rc
    original_git = release.git
    probes = []

    def failing_legacy_probe(*arguments):
        if arguments[0] == "show-ref":
            probes.append(arguments)
            if arguments[1] == "--exists":
                raise subprocess.CalledProcessError(129, arguments, stderr=b"unknown option exists")
            raise subprocess.CalledProcessError(128, arguments, stderr=b"fixture legacy-probe error")
        if arguments[0] != "rev-parse":
            pytest.fail("Source read after a legacy tag probe error")
        return original_git(*arguments)

    monkeypatch.setattr(release, "git", failing_legacy_probe)
    output = tmp_path / "output"
    options = {"scope": scope} if scope is not None else {}
    with pytest.raises(ValueError, match="Version tag refs/tags/v1.0.0-rc.1 probe failed") as error:
        getattr(release, entry_point)(commit, "v1.0.0-rc.1", output, **options)
    assert "fixture legacy-probe error" in str(error.value)
    assert probes == [("show-ref", "--exists", "refs/tags/v1.0.0-rc.1"),
                      ("show-ref", "--verify", "--quiet", "refs/tags/v1.0.0-rc.1")]
    assert not output.exists()


@pytest.mark.parametrize("entry_point,scope", [
    ("package", "application-source"), ("package", "controller-badge-source"),
    ("package_controller_badge", None),
])
@pytest.mark.parametrize("legacy_git", [False, True])
@pytest.mark.parametrize("ref_kind", [
    "truncated", "garbage", "dangling-symbolic", "missing-object", "lightweight-tree", "annotated-tree", "blob",
])
def test_broken_or_noncommit_version_tags_refused_before_source_or_output(
        committed_rc, tmp_path, monkeypatch, entry_point, scope, legacy_git, ref_kind):
    repo, commit = committed_rc
    version = "v1.0.0-rc.1"
    tag_ref = "refs/tags/" + version
    tag_path = repo / ".git" / tag_ref
    tag_path.parent.mkdir(parents=True, exist_ok=True)
    if ref_kind == "annotated-tree":
        tree = git(repo, "rev-parse", "HEAD^{tree}").decode().strip()
        git(repo, "tag", "-a", version, "-m", "tree is not a release commit", tree)
    else:
        if ref_kind == "lightweight-tree":
            contents = git(repo, "rev-parse", "HEAD^{tree}")
        elif ref_kind == "blob":
            contents = git(repo, "hash-object", "-w", "--stdin", input_bytes=b"not a release commit\n")
        else:
            contents = {
                "truncated": b"deadbeef\n", "garbage": b"not-an-object-id\n",
                "dangling-symbolic": b"ref: refs/tags/missing-fixture-tag\n",
                "missing-object": b"f" * 40 + b"\n",
            }[ref_kind]
        tag_path.write_bytes(contents)
    original_git = release.git
    probes = []

    def references_only(*arguments):
        if arguments[0] not in ("rev-parse", "show-ref"):
            pytest.fail("Source blob read before refusing an invalid version tag")
        if arguments[:2] == ("show-ref", "--exists"):
            probes.append(arguments)
            if legacy_git:
                raise subprocess.CalledProcessError(129, arguments, stderr=b"unknown option exists")
            try:
                return original_git(*arguments)
            except subprocess.CalledProcessError as exc:
                if exc.returncode != 129:
                    raise
                # Older hosts lack --exists: emulate only its known-fixture
                # lookup result; the actual malformed ref and commit peel stay real.
                if ref_kind in ("truncated", "garbage"):
                    raise subprocess.CalledProcessError(1, arguments, stderr=b"invalid fixture ref format") from exc
                return b""
        return original_git(*arguments)

    monkeypatch.setattr(release, "git", references_only)
    output = tmp_path / "output"
    options = {"scope": scope} if scope is not None else {}
    with pytest.raises(ValueError, match="Version tag refs/tags/v1.0.0-rc.1") as error:
        getattr(release, entry_point)(commit, version, output, **options)
    if not legacy_git and ref_kind in ("truncated", "garbage"):
        assert "probe failed" in str(error.value)
    elif not legacy_git or ref_kind in ("lightweight-tree", "annotated-tree", "blob"):
        assert "does not resolve to a commit" in str(error.value)
    else:
        assert "probe failed" in str(error.value) or "does not resolve to a commit" in str(error.value)
    assert probes == [("show-ref", "--exists", tag_ref)]
    assert not output.exists()


@pytest.mark.parametrize("entry_point,scope", [
    ("package", "application-source"), ("package", "controller-badge-source"),
    ("package_controller_badge", None),
])
@pytest.mark.parametrize("storage", ["loose", "packed"])
@pytest.mark.parametrize("legacy_git", [False, True])
def test_missing_probe_cannot_hide_existing_unresolvable_tag(
        committed_rc, tmp_path, monkeypatch, entry_point, scope, storage, legacy_git):
    repo, commit = committed_rc
    version = "v1.0.0-rc.1"
    tag_ref = "refs/tags/" + version
    if storage == "loose":
        path = repo / ".git" / tag_ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ref: refs/tags/missing-fixture-tag\n")
    else:
        (repo / ".git/packed-refs").write_bytes(
            b"# pack-refs with: peeled fully-peeled sorted\n" + b"f" * 40 + b" " + tag_ref.encode() + b"\n"
        )
    original_git = release.git
    probes = []

    def ambiguous_probe(*arguments):
        if arguments[0] == "show-ref":
            probes.append(arguments)
            code = (129 if legacy_git else 2) if arguments[1] == "--exists" else 1
            raise subprocess.CalledProcessError(code, arguments, stderr=b"")
        if arguments[0] != "rev-parse":
            pytest.fail("Source blob read after an unresolved tag")
        return original_git(*arguments)

    monkeypatch.setattr(release, "git", ambiguous_probe)
    output = tmp_path / "output"
    options = {"scope": scope} if scope is not None else {}
    with pytest.raises(ValueError, match="Version tag .* does not resolve to a commit"):
        getattr(release, entry_point)(commit, version, output, **options)
    legacy_probe = [("show-ref", "--verify", "--quiet", tag_ref)] if legacy_git else []
    assert probes == [("show-ref", "--exists", tag_ref), *legacy_probe, ("show-ref", "--verify", "--hash", tag_ref)]
    assert not output.exists()


@pytest.mark.parametrize("entry_point,scope", [
    ("package", "application-source"), ("package", "controller-badge-source"),
    ("package_controller_badge", None),
])
@pytest.mark.parametrize("tagged", [False, True])
def test_legacy_git_fallback_allows_only_absent_or_matching_commit_tags(
        committed_rc, tmp_path, monkeypatch, entry_point, scope, tagged):
    repo, commit = committed_rc
    version = "v1.0.0-rc.1"
    if tagged:
        git(repo, "tag", "-a", version, "-m", "matching annotated commit", commit)
    original_git = release.git
    probes = []

    def legacy_probe(*arguments):
        if arguments[0] == "show-ref":
            probes.append(arguments)
        if arguments[:2] == ("show-ref", "--exists"):
            raise subprocess.CalledProcessError(129, arguments, stderr=b"unknown option exists")
        return original_git(*arguments)

    monkeypatch.setattr(release, "git", legacy_probe)
    options = {"scope": scope} if scope is not None else {}
    result = getattr(release, entry_point)(commit, version, tmp_path / "output", **options)
    assert result["source_commit"] == commit and Path(result["archive"]).is_file()
    assert ("show-ref", "--verify", "--quiet", "refs/tags/" + version) in probes


@pytest.mark.parametrize("fixture_name", ["committed_source", "committed_rc"])
def test_inprocess_tag_checks_use_fixture_git_environment(tmp_path, monkeypatch, request, fixture_name):
    unused = set_hostile_git_environment(tmp_path, monkeypatch)
    repo, commit = request.getfixturevalue(fixture_name)
    assert {key: value for key, value in os.environ.items() if key.upper().startswith("GIT_")} == {
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
    }
    git(repo, "tag", "-a", "v1.0.0-rc.1", "-m", "isolated in-process tag", commit)
    original_git = release.git
    probes = []

    def observe_tag_probe(*arguments):
        if arguments[:2] == ("show-ref", "--exists"):
            probes.append(arguments)
        return original_git(*arguments)

    monkeypatch.setattr(release, "git", observe_tag_probe)
    scope = "controller-badge-source" if fixture_name == "committed_rc" else "application-source"
    result = release.package(commit, "v1.0.0-rc.1", tmp_path / "output", scope=scope)
    assert result["source_commit"] == commit and probes
    assert all(not path.exists() for path in unused.values())


def route_tag_probe(monkeypatch, legacy_git, *, source_reads=False):
    """Run the packager's own git(), answering `show-ref --exists` as Git before 2.43 when asked."""
    original_git = release.git
    calls = []

    def probe(*arguments):
        calls.append(arguments)
        if not source_reads and arguments[0] not in ("rev-parse", "show-ref"):
            pytest.fail("Source read before refusing a version tag")
        if legacy_git and arguments[:2] == ("show-ref", "--exists"):
            raise subprocess.CalledProcessError(129, arguments, stderr=b"unknown option exists")
        return original_git(*arguments)

    monkeypatch.setattr(release, "git", probe)
    return calls


def write_packed_refs(repo, *entries):
    """Write packed-refs lines in the given order under a header that claims sorted order."""
    (repo / ".git/packed-refs").write_bytes(b"# pack-refs with: peeled fully-peeled sorted \n" + b"".join(
        object_id.encode() + b" " + name.encode() + b"\n" for object_id, name in entries))


@pytest.mark.parametrize("legacy_git", [False, True])
@pytest.mark.parametrize("stray_ref", [
    "refs/tags/refs/tags/v1.0.0-rc.1", "refs/heads/refs/tags/v1.0.0-rc.1",
    "refs/refs/tags/v1.0.0-rc.1", "refs/remotes/refs/tags/v1.0.0-rc.1",
])
@pytest.mark.parametrize("target", ["refs/tags/missing-fixture-tag", "refs/tags/v1.0.0-rc.1"],
                         ids=["dangling", "self-loop"])
def test_broken_tag_cannot_borrow_a_stray_ref_at_the_requested_commit(
        committed_rc, tmp_path, monkeypatch, legacy_git, stray_ref, target):
    repo, commit = committed_rc
    # `git tag refs/tags/v1.0.0-rc.1` creates the first stray name; Git's fallback
    # names for an unresolvable refs/tags/v1.0.0-rc.1 include all four.
    git(repo, "update-ref", stray_ref, commit)
    (repo / ".git/refs/tags/v1.0.0-rc.1").write_bytes(b"ref: " + target.encode() + b"\n")
    route_tag_probe(monkeypatch, legacy_git)
    output = tmp_path / "output"
    with pytest.raises(ValueError) as error:
        release.package(commit, "v1.0.0-rc.1", output)
    assert str(error.value).startswith("Version tag refs/tags/v1.0.0-rc.1 does not resolve to a commit: ")
    assert not output.exists()


@pytest.mark.parametrize("legacy_git", [False, True])
def test_out_of_order_packed_tag_at_another_commit_is_refused(committed_rc, tmp_path, monkeypatch, legacy_git):
    repo, commit = committed_rc
    earlier = git(repo, "rev-parse", "HEAD^").decode().strip()
    # The header claims sorted order, so Git 2.43's lookup misses the last line,
    # while `git push --tags` reads every line and would publish the tag.
    write_packed_refs(repo, (earlier, "refs/heads/fixture-one"), (commit, "refs/heads/fixture-two"),
                      (earlier, "refs/tags/v1.0.0-rc.2"), (earlier, "refs/tags/zz-later"),
                      (earlier, "refs/tags/v1.0.0-rc.1"))
    route_tag_probe(monkeypatch, legacy_git)
    output = tmp_path / "output"
    with pytest.raises(ValueError) as error:
        release.package(commit, "v1.0.0-rc.1", output)
    message = str(error.value)
    assert (message.startswith("Version tag refs/tags/v1.0.0-rc.1 does not resolve to a commit: ")
            or message.endswith(" resolves to " + earlier + ", not requested commit " + commit))
    assert not output.exists()


@pytest.mark.parametrize("legacy_git", [False, True])
@pytest.mark.parametrize("suffix", ["\0", "\0fixture", "\0 fixture"], ids=["nul", "nul-text", "nul-space-text"])
def test_packed_tag_name_ended_by_a_nul_byte_is_refused(committed_rc, tmp_path, monkeypatch, legacy_git, suffix):
    repo, commit = committed_rc
    earlier = git(repo, "rev-parse", "HEAD^").decode().strip()
    # Git's lookup misses this line, but Git lists and pushes it as the version tag.
    write_packed_refs(repo, (earlier, "refs/tags/v1.0.0-rc.1" + suffix))
    assert git(repo, "for-each-ref", "--format=%(refname)", "refs/tags/").split() == [b"refs/tags/v1.0.0-rc.1"]
    route_tag_probe(monkeypatch, legacy_git)
    output = tmp_path / "output"
    with pytest.raises(ValueError) as error:
        release.package(commit, "v1.0.0-rc.1", output)
    assert str(error.value).startswith("Version tag refs/tags/v1.0.0-rc.1 does not resolve to a commit: ")
    assert not output.exists()


@pytest.mark.parametrize("legacy_git", [False, True])
def test_loose_tag_in_another_letter_case_is_refused(committed_rc, tmp_path, monkeypatch, legacy_git):
    repo, commit = committed_rc
    if not (repo / ".git/head").exists():
        pytest.skip("Only a case-insensitive file system answers a lookup from another letter case")
    earlier = git(repo, "rev-parse", "HEAD^").decode().strip()
    git(repo, "tag", "v1.0.0-rc.1", earlier)
    git(repo, "pack-refs", "--all")
    # `git push --tags` publishes the packed v1.0.0-rc.1, but Git's lookup reads this loose file.
    (repo / ".git/refs/tags/V1.0.0-RC.1").write_bytes(commit.encode() + b"\n")
    route_tag_probe(monkeypatch, legacy_git)
    output = tmp_path / "output"
    with pytest.raises(ValueError) as error:
        release.package(commit, "v1.0.0-rc.1", output)
    assert str(error.value) == "Version tag refs/tags/v1.0.0-rc.1 has a loose ref in another letter case"
    assert not output.exists()


@pytest.mark.parametrize("legacy_git", [False, True])
def test_loose_tag_listed_in_another_letter_case_is_refused_portably(committed_rc, tmp_path, monkeypatch, legacy_git):
    repo, commit = committed_rc
    earlier = git(repo, "rev-parse", "HEAD^").decode().strip()
    git(repo, "tag", "v1.0.0-rc.1", earlier)
    git(repo, "pack-refs", "--all")
    (repo / ".git/refs/tags/v1.0.0-rc.1").write_bytes(commit.encode() + b"\n")
    tags = (repo / ".git/refs/tags").resolve()
    real_listdir = os.listdir

    def listdir(path):
        # List the loose tag as a case-insensitive file system stores it, without needing one.
        names = real_listdir(path)
        if Path(path).resolve() != tags:
            return names
        return ["V1.0.0-RC.1" if name == "v1.0.0-rc.1" else name for name in names]

    monkeypatch.setattr(release.os, "listdir", listdir)
    route_tag_probe(monkeypatch, legacy_git)
    output = tmp_path / "output"
    with pytest.raises(ValueError) as error:
        release.package(commit, "v1.0.0-rc.1", output)
    assert str(error.value) == "Version tag refs/tags/v1.0.0-rc.1 has a loose ref in another letter case"
    assert not output.exists()


@pytest.mark.parametrize("legacy_git", [False, True])
@pytest.mark.parametrize("fixture_first", [False, True])
def test_duplicate_packed_tag_entries_are_refused(committed_rc, tmp_path, monkeypatch, legacy_git, fixture_first):
    repo, commit = committed_rc
    earlier = git(repo, "rev-parse", "HEAD^").decode().strip()
    entries = [(commit, "refs/tags/v1.0.0-rc.1"), (earlier, "refs/tags/v1.0.0-rc.1")]
    write_packed_refs(repo, *(entries if fixture_first else reversed(entries)))
    # Git's lookup returns one line while `git push --tags` publishes the other. Request the
    # commit the lookup reports, so only the duplicate count can refuse.
    requested = git(repo, "rev-parse", "--verify", "refs/tags/v1.0.0-rc.1^{commit}").decode().strip()
    route_tag_probe(monkeypatch, legacy_git)
    output = tmp_path / "output"
    with pytest.raises(ValueError) as error:
        release.package(requested, "v1.0.0-rc.1", output)
    assert str(error.value) == "Version tag refs/tags/v1.0.0-rc.1 has 2 packed-refs entries"
    assert not output.exists()


@pytest.mark.parametrize("legacy_git", [False, True])
@pytest.mark.parametrize("moved_to_requested", [True, False])
def test_tag_moved_after_pack_refs_follows_its_loose_ref(
        committed_rc, tmp_path, monkeypatch, legacy_git, moved_to_requested):
    repo, commit = committed_rc
    earlier = git(repo, "rev-parse", "HEAD^").decode().strip()
    packed, moved = (earlier, commit) if moved_to_requested else (commit, earlier)
    # One packed line under a loose ref is a normal re-tag, not a duplicate; push publishes the loose value.
    git(repo, "tag", "v1.0.0-rc.1", packed)
    git(repo, "pack-refs", "--all")
    git(repo, "tag", "-f", "v1.0.0-rc.1", moved)
    route_tag_probe(monkeypatch, legacy_git, source_reads=moved_to_requested)
    output = tmp_path / "output"
    if moved_to_requested:
        result = release.package(commit, "v1.0.0-rc.1", output)
        assert result["source_commit"] == commit and Path(result["archive"]).is_file()
    else:
        with pytest.raises(ValueError) as error:
            release.package(commit, "v1.0.0-rc.1", output)
        assert str(error.value) == ("Version tag refs/tags/v1.0.0-rc.1 resolves to " + earlier
                                    + ", not requested commit " + commit)
        assert not output.exists()


@pytest.mark.parametrize("variable", ["GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"])
def test_caller_object_store_cannot_supply_the_requested_commit(committed_rc, tmp_path, monkeypatch, variable):
    repo, commit = committed_rc
    other = tmp_path / "other-object-store"
    git(tmp_path, "clone", "--quiet", "--no-checkout", str(repo), str(other))
    git(other, "-c", "user.name=Release Test", "-c", "user.email=release-test@example.invalid",
        "commit", "--allow-empty", "-m", "commit outside the packaged repository")
    outside = git(other, "rev-parse", "HEAD").decode().strip()
    monkeypatch.setenv(variable, str(other / ".git/objects"))
    result = release.package(commit, "v1.0.0-rc.1", tmp_path / "output")
    assert result["source_commit"] == commit
    # Only REPO's own object store is read, so a commit found only through the caller's store is unknown.
    with pytest.raises(subprocess.CalledProcessError):
        release.package(outside, "v1.0.0-rc.1", tmp_path / "outside-output")
    assert not (tmp_path / "outside-output").exists()


@pytest.mark.parametrize("legacy_git", [False, True])
def test_caller_git_dir_cannot_hide_a_mismatched_tag(committed_rc, tmp_path, monkeypatch, legacy_git):
    repo, commit = committed_rc
    untagged = tmp_path / "untagged-clone"
    git(tmp_path, "clone", "--quiet", "--no-checkout", str(repo), str(untagged))
    earlier = git(repo, "rev-parse", "HEAD^").decode().strip()
    git(repo, "tag", "v1.0.0-rc.1", earlier)
    # Git hooks export GIT_DIR; the packager must still read its own repository.
    monkeypatch.setenv("GIT_DIR", str(untagged / ".git"))
    route_tag_probe(monkeypatch, legacy_git)
    output = tmp_path / "output"
    with pytest.raises(ValueError) as error:
        release.package(commit, "v1.0.0-rc.1", output)
    assert str(error.value) == ("Version tag refs/tags/v1.0.0-rc.1 resolves to " + earlier
                                + ", not requested commit " + commit)
    assert not output.exists()


def test_forced_fallback_caller_git_common_dir_cannot_hide_a_truncated_tag(committed_rc, tmp_path, monkeypatch):
    repo, commit = committed_rc
    untagged = shutil.copytree(repo / ".git", tmp_path / "untagged-common-dir")
    (repo / ".git/refs/tags/v1.0.0-rc.1").write_bytes(b"deadbeef\n")
    monkeypatch.setenv("GIT_COMMON_DIR", str(untagged))
    route_tag_probe(monkeypatch, legacy_git=True)
    output = tmp_path / "output"
    with pytest.raises(ValueError) as error:
        release.package(commit, "v1.0.0-rc.1", output)
    assert str(error.value).startswith("Version tag refs/tags/v1.0.0-rc.1 does not resolve to a commit: ")
    assert not output.exists()


@pytest.mark.parametrize("tag_state", ["absent", "truncated"])
def test_forced_fallback_trace_output_neither_refuses_nor_hides_a_tag(committed_rc, tmp_path, monkeypatch, tag_state):
    repo, commit = committed_rc
    if tag_state == "truncated":
        (repo / ".git/refs/tags/v1.0.0-rc.1").write_bytes(b"deadbeef\n")
    monkeypatch.setenv("GIT_TRACE", "1")
    with pytest.raises(subprocess.CalledProcessError) as noisy:
        release.git("show-ref", "--verify", "--quiet", "refs/tags/v1.0.0-rc.1")
    assert noisy.value.returncode == 1 and noisy.value.stderr.strip()
    calls = route_tag_probe(monkeypatch, legacy_git=True, source_reads=tag_state == "absent")
    output = tmp_path / "output"
    if tag_state == "absent":
        result = release.package(commit, "v1.0.0-rc.1", output)
        assert result["source_commit"] == commit and Path(result["archive"]).is_file()
    else:
        with pytest.raises(ValueError) as error:
            release.package(commit, "v1.0.0-rc.1", output)
        assert str(error.value).startswith("Version tag refs/tags/v1.0.0-rc.1 does not resolve to a commit: ")
        assert not output.exists()
    assert ("show-ref", "--verify", "--quiet", "refs/tags/v1.0.0-rc.1") in calls


def unreadable_tag_metadata(tmp_path, trigger):
    """Return the loose and packed-refs paths Git reports, making one unreadable as asked."""
    loose, packed = tmp_path / "tags" / "v1.0.0-rc.1", tmp_path / "packed-refs"
    if trigger == "packed-refs-directory":
        packed.mkdir()
    elif trigger == "loose-path-below-file":
        loose.parent.write_bytes(b"not a directory\n")
    return {"refs/tags/v1.0.0-rc.1": loose, "packed-refs": packed}


@pytest.mark.parametrize("exists_code", [0, 2, 129], ids=["present", "missing", "legacy-missing"])
@pytest.mark.parametrize("trigger", [
    "git-path-failure", "packed-refs-directory",
    pytest.param("loose-path-below-file", marks=pytest.mark.skipif(
        os.name == "nt", reason="Windows reports a path below a regular file as missing")),
])
def test_unreadable_tag_metadata_is_refused_before_source_or_output(
        committed_rc, tmp_path, monkeypatch, exists_code, trigger):
    _, commit = committed_rc
    git_paths = unreadable_tag_metadata(tmp_path, trigger)
    original_git = release.git

    def unreadable_metadata(*arguments):
        if arguments[0] == "show-ref":
            code = exists_code if arguments[1] == "--exists" else 1
            if code:
                raise subprocess.CalledProcessError(code, arguments, stderr=b"")
            return b""
        if arguments[:2] == ("rev-parse", "--git-path"):
            if trigger == "git-path-failure":
                raise subprocess.CalledProcessError(128, arguments, stderr=b"fixture git-path error\n")
            return os.fsencode(git_paths[arguments[2]]) + b"\n"
        if arguments[0] != "rev-parse":
            pytest.fail("Source read after unreadable tag metadata")
        return original_git(*arguments)

    monkeypatch.setattr(release, "git", unreadable_metadata)
    output = tmp_path / "output"
    with pytest.raises(ValueError) as error:
        release.package(commit, "v1.0.0-rc.1", output)
    cause = error.value.__cause__
    reason = "fixture git-path error" if trigger == "git-path-failure" else str(cause)
    assert str(error.value) == "Version tag refs/tags/v1.0.0-rc.1 metadata check failed: " + reason
    assert trigger == "git-path-failure" or (isinstance(cause, OSError) and not isinstance(cause, FileNotFoundError))
    assert not output.exists()


@pytest.mark.skipif(os.name == "nt", reason="Windows file names are Unicode, so a non-UTF-8 path cannot exist")
@pytest.mark.parametrize("legacy_git", [False, True])
@pytest.mark.parametrize("tag_state", ["absent", "matching", "truncated"])
def test_linked_worktree_of_a_repository_under_a_non_utf8_path(committed_rc, tmp_path, monkeypatch, legacy_git,
                                                               tag_state):
    repo, commit = committed_rc
    parent = Path(os.fsdecode(os.fsencode(tmp_path) + b"/common-dir-\xff"))
    try:
        parent.mkdir()
    except OSError:
        pytest.skip("The file system refuses a non-UTF-8 directory name")
    repo = repo.rename(parent / "repository")
    # Git prints absolute --git-path results into the non-UTF-8 common directory here.
    worktree = tmp_path / "linked-worktree"
    git(repo, "worktree", "add", "--detach", str(worktree), commit)
    if tag_state == "matching":
        git(repo, "tag", "v1.0.0-rc.1", commit)
    elif tag_state == "truncated":
        (repo / ".git/refs/tags/v1.0.0-rc.1").write_bytes(b"deadbeef\n")
    monkeypatch.setattr(release, "REPO", worktree)
    route_tag_probe(monkeypatch, legacy_git, source_reads=tag_state != "truncated")
    output = tmp_path / "output"
    if tag_state == "truncated":
        with pytest.raises(ValueError, match="^Version tag refs/tags/v1.0.0-rc.1 (probe failed|does not resolve)"):
            release.package(commit, "v1.0.0-rc.1", output)
        assert not output.exists()
    else:
        result = release.package(commit, "v1.0.0-rc.1", output)
        assert result["source_commit"] == commit and Path(result["archive"]).is_file()


@pytest.mark.parametrize("stderr", [b"", b" \n\t\n"], ids=["empty", "whitespace"])
@pytest.mark.parametrize("site", ["exists-probe", "legacy-probe", "git-path", "exact-ref", "peel"])
def test_blank_git_stderr_reports_the_exit_status(committed_rc, tmp_path, monkeypatch, site, stderr):
    repo, commit = committed_rc
    tag_ref = "refs/tags/v1.0.0-rc.1"
    prefix = {"exists-probe": "probe failed", "legacy-probe": "probe failed", "git-path": "metadata check failed",
              "exact-ref": "does not resolve to a commit", "peel": "does not resolve to a commit"}[site]
    failing = {
        "exists-probe": ("show-ref", "--exists", tag_ref),
        "legacy-probe": ("show-ref", "--verify", "--quiet", tag_ref),
        "git-path": ("rev-parse", "--git-path", tag_ref),
        "exact-ref": ("show-ref", "--verify", "--hash", tag_ref),
    }.get(site)
    if site in ("exact-ref", "peel"):
        git(repo, "tag", "-a", "v1.0.0-rc.1", "-m", "matching annotated commit", commit)
    if site == "peel":
        tag_object = git(repo, "rev-parse", tag_ref).decode().strip()
        failing = ("rev-parse", "--verify", "--end-of-options", tag_object + "^{commit}")
    original_git = release.git

    def silent_failure(*arguments):
        if arguments == failing:
            raise subprocess.CalledProcessError(128, arguments, stderr=stderr)
        if site == "legacy-probe" and arguments[:2] == ("show-ref", "--exists"):
            raise subprocess.CalledProcessError(129, arguments, stderr=b"unknown option exists")
        if arguments[0] not in ("rev-parse", "show-ref"):
            pytest.fail("Source read after a failed tag check")
        return original_git(*arguments)

    monkeypatch.setattr(release, "git", silent_failure)
    output = tmp_path / "output"
    with pytest.raises(ValueError) as error:
        release.package(commit, "v1.0.0-rc.1", output)
    assert str(error.value) == "Version tag " + tag_ref + " " + prefix + ": Git exited with status 128"
    assert not output.exists()


def test_exact_peel_requires_a_full_object_id(committed_rc, tmp_path, monkeypatch):
    repo, commit = committed_rc
    git(repo, "tag", "v1.0.0-rc.1", commit)
    original_git = release.git

    def symbolic_hash(*arguments):
        if arguments[:3] == ("show-ref", "--verify", "--hash"):
            return b"HEAD\n"
        if arguments[0] not in ("rev-parse", "show-ref"):
            pytest.fail("Source read after a tag hash that is not an object ID")
        return original_git(*arguments)

    monkeypatch.setattr(release, "git", symbolic_hash)
    output = tmp_path / "output"
    with pytest.raises(ValueError) as error:
        release.package(commit, "v1.0.0-rc.1", output)
    assert str(error.value) == ("Version tag refs/tags/v1.0.0-rc.1 does not resolve to a commit: "
                                "show-ref printed no full object ID")
    assert not output.exists()

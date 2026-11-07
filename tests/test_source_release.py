"""Release privacy boundaries, committed-byte provenance and reproducibility."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("source_release", REPO / "scripts/package_source_release.py")
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def git(repo, *args, input_bytes=None):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, input=input_bytes
    ).stdout


@pytest.fixture
def committed_source(tmp_path, monkeypatch):
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
    private_paths = ["settings.toml", "secrets.py", ".artwork_wifi.json", ".badge_remote.json",
                     ".badge_windows_launch.key", ".bm83_windows_companion.json", ".bm83_windows_receiver.json",
                     "lib/secrets.py", "lib/remote/private_profile.py"]
    for name in private_paths:
        (repo / release.SOURCE_ROOT / name).write_text("DO-NOT-PACKAGE-PRIVATE-DATA", encoding="utf-8")
    git(repo, "add", "LICENSE", "firmware")
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

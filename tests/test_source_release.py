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

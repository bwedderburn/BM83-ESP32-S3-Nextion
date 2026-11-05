"""Native-build provenance guards using synthetic sources and local files only."""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "tools/circuitpython-runtime/record-build.py"
SPEC = importlib.util.spec_from_file_location("native_runtime_record", SCRIPT)
record = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(record)
BOARD = "ports/espressif/boards/espressif_esp32s3_devkitc_1_n8r8/sdkconfig"
BASE_BOARD = "# synthetic stock board\nCONFIG_REFERENCE=y\n"
BOARD_ADDITIONS = ("CONFIG_BT_NIMBLE_MAX_BONDS=8\nCONFIG_BT_NIMBLE_MAX_CCCDS=24\n"
                   "CONFIG_BT_NIMBLE_ENABLE_CONN_REATTEMPT=n\n")
WEB_TOOL = "tools/gen_web_workflow_static.py"
BASE_WEB_TOOL = "import gzip\n\ndef compress(uncompressed):\n    return gzip.compress(uncompressed)\n"
PATCHED_WEB_TOOL = BASE_WEB_TOOL.replace("gzip.compress(uncompressed)", "gzip.compress(uncompressed, mtime=0)")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(folder, *args):
    result = subprocess.run(["git", "-C", str(folder), *args], capture_output=True,
                            text=True, timeout=15, check=True)
    return result.stdout.strip()


def init_repo(folder):
    folder.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(folder)], check=True, capture_output=True, timeout=15)


def commit_all(folder):
    git(folder, "add", ".")
    git(folder, "commit", "-q", "-m", "synthetic source fixture")
    return git(folder, "rev-parse", "HEAD")


@pytest.fixture
def source_tree(tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("Git unavailable for local source fixtures")
    # No global identities, signing helpers, credentials or hooks are needed.
    config = tmp_path / "empty-git-config"
    config.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "0")
    for name in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv("GIT_" + name + "_NAME", "Runtime Fixture")
        monkeypatch.setenv("GIT_" + name + "_EMAIL", "fixture@example.invalid")
        monkeypatch.setenv("GIT_" + name + "_DATE", "2001-01-01T00:00:00+00:00")

    nimble_origin = tmp_path / "nimble-origin"
    init_repo(nimble_origin)
    (nimble_origin / "native.c").write_text("/* synthetic NimBLE input */\n")
    for names in record.NIMBLE_PATCH_FILES.values():
        for name in names:
            source = nimble_origin / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("/* synthetic pinned NimBLE source */\n")
    commit_all(nimble_origin)

    idf_origin = tmp_path / "idf-origin"
    init_repo(idf_origin)
    (idf_origin / "tools").mkdir()
    (idf_origin / "tools/tools.json").write_text('{"synthetic": "toolchain manifest"}\n')
    nimble_relative = "components/bt/host/nimble/nimble"
    git(idf_origin, "-c", "protocol.file.allow=always", "submodule", "add", "-q",
        str(nimble_origin), nimble_relative)
    commit_all(idf_origin)

    root = tmp_path / "circuitpython"
    init_repo(root)
    board = root / BOARD
    board.parent.mkdir(parents=True)
    board.write_text(BASE_BOARD)
    web_tool = root / WEB_TOOL
    web_tool.parent.mkdir(parents=True)
    web_tool.write_text(BASE_WEB_TOOL)
    (root / "native.c").write_text("/* synthetic reviewed source */\n")
    for filename in record.HASHLIB_FILES:
        target = root / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("/* synthetic pinned hash source */\n")
    for filename in record.HOST_POLICY_FILES - {BOARD}:
        target = root / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("/* synthetic pinned host policy source */\n")
    (root / ".gitignore").write_text("build-*/\nmpy-cross/build/\n")
    git(root, "-c", "protocol.file.allow=always", "submodule", "add", "-q",
        str(idf_origin), "ports/espressif/esp-idf")
    commit_all(root)
    git(root, "-c", "protocol.file.allow=always", "submodule", "update", "--init", "--recursive", "-q")
    board.write_text(BASE_BOARD + BOARD_ADDITIONS)
    web_tool.write_text(PATCHED_WEB_TOOL)
    for filename in record.HASHLIB_FILES:
        (root / filename).write_text("/* synthetic exact reviewed hash lifetime source */\n")
    for filename in record.HOST_POLICY_FILES - {BOARD}:
        (root / filename).write_text("/* synthetic exact reviewed native host policy */\n")
    idf = root / "ports/espressif/esp-idf"
    nimble = idf / nimble_relative

    recipe = tmp_path / "recipe"
    recipe.mkdir()
    constraints = b"cryptography>=50.0.0,<50.1\n"
    requirements = b"cryptography==50.0.0\n"
    (recipe / "espidf.constraints.v6.0.txt").write_bytes(constraints)
    (recipe / "requirements-build.txt").write_bytes(requirements)
    web_patch = b"synthetic reviewed build-only gzip mtime patch\n"
    (recipe / "reproducible-web-assets.patch").write_bytes(web_patch)
    native_patch = b"synthetic reviewed native hash lifetime patch\n"
    (recipe / "hashlib-close.patch").write_bytes(native_patch)
    policy_patch = b"synthetic reviewed native host policy patch\n"
    (recipe / "host-policy.patch").write_bytes(policy_patch)
    nimble_patches = {}
    for patch, names in record.NIMBLE_PATCH_FILES.items():
        data = ("synthetic reviewed " + patch + "\n").encode()
        (recipe / patch).write_bytes(data)
        for name in names:
            (nimble / name).write_text("/* synthetic reviewed patched NimBLE source */\n")
        nimble_patches[patch] = {
            "sha256": digest(data),
            "files": {name: digest((nimble / name).read_bytes()) for name in names},
        }
    sources = {name: git(path, "rev-parse", "HEAD") for name, path in (
        ("circuitpython", root), ("esp_idf", idf), ("esp_nimble", idf / nimble_relative))}
    pins = {
        "sources": {name: {"commit": value} for name, value in sources.items()},
        "reference_tools": {
            "idf_tools_json_sha256": digest((idf / "tools/tools.json").read_bytes()),
            # This historical hash intentionally differs from the active snapshot.
            "constraints_sha256": "0" * 64,
        },
        "security_build": {
            "constraints_sha256": digest(constraints),
            "requirements_sha256": digest(requirements),
        },
        "runtime_patches": {"hashlib_close": {
            "sha256": digest(native_patch),
            "files": {name: digest((root / name).read_bytes()) for name in record.HASHLIB_FILES},
        }, "host_policy": {
            "sha256": digest(policy_patch),
            "files": {name: digest((root / name).read_bytes()) for name in record.HOST_POLICY_FILES},
        }},
        "nimble_patches": nimble_patches,
    }
    pins_path = recipe / "source-pins.json"
    pins_path.write_text(json.dumps(pins))
    monkeypatch.setattr(record, "ROOT", root)
    monkeypatch.setattr(record, "IDF", idf)
    monkeypatch.setattr(record, "RECIPE", recipe)
    host_checks = []
    monkeypatch.setattr(record, "check_host_tools", lambda value: host_checks.append(value))
    return SimpleNamespace(root=root, idf=idf, recipe=recipe, board=board, pins=pins,
                           pins_path=pins_path, sources=sources, host_checks=host_checks, web_tool=web_tool)


def test_active_security_hashes_are_used_without_rewriting_historical_reference(source_tree):
    fixture = source_tree
    before = fixture.pins_path.read_bytes()
    assert record.check_sources() == fixture.sources
    assert fixture.host_checks == [fixture.pins]
    assert fixture.pins_path.read_bytes() == before
    assert fixture.pins["reference_tools"]["constraints_sha256"] != digest(
        (fixture.recipe / "espidf.constraints.v6.0.txt").read_bytes())


def test_exact_reviewed_board_patch_remains_allowed_when_staged(source_tree):
    git(source_tree.root, "add", BOARD)
    assert record.check_sources() == source_tree.sources


def test_exact_reviewed_web_tool_patch_remains_allowed_when_staged(source_tree):
    git(source_tree.root, "add", WEB_TOOL)
    assert record.check_sources() == source_tree.sources


@pytest.mark.parametrize("filename", sorted(record.HASHLIB_FILES))
@pytest.mark.parametrize("staged", [False, True])
def test_entire_native_hash_source_must_match_reviewed_output(source_tree, filename, staged):
    target = source_tree.root / filename
    target.write_text(target.read_text() + "/* unreviewed extra native code */\n")
    if staged:
        git(source_tree.root, "add", filename)
    with pytest.raises(ValueError, match="Unexpected native hash lifetime source"):
        record.check_sources()
    assert source_tree.host_checks == []


def test_native_hash_patch_bytes_must_match_the_reviewed_pin(source_tree):
    patch = source_tree.recipe / "hashlib-close.patch"
    patch.write_bytes(patch.read_bytes() + b"unreviewed patch modification\n")
    with pytest.raises(ValueError, match="native hash lifetime patch provenance"):
        record.check_sources()


def test_native_hash_source_allowlist_cannot_be_expanded(source_tree):
    source_tree.pins["runtime_patches"]["hashlib_close"]["files"]["native.c"] = digest(
        (source_tree.root / "native.c").read_bytes())
    source_tree.pins_path.write_text(json.dumps(source_tree.pins))
    with pytest.raises(ValueError, match="native hash lifetime patch provenance"):
        record.check_sources()


def test_unreviewed_nested_nimble_changes_are_rejected(source_tree):
    nimble = source_tree.idf / record.NIMBLE_GITLINK
    (nimble / "native.c").write_text("/* modified unrelated NimBLE source */\n")
    with pytest.raises(ValueError, match="Unexpected modified source in the NimBLE or IDF submodule"):
        record.check_sources()


def test_vendor_postimage_must_match_its_exact_pin(source_tree):
    nimble = source_tree.idf / record.NIMBLE_GITLINK
    (nimble / "nimble/host/src/ble_gap.c").write_text("/* extra NimBLE change */\n")
    with pytest.raises(ValueError, match="Unexpected patched NimBLE source"):
        record.check_sources()


@pytest.mark.parametrize("filename", sorted(record.HOST_POLICY_FILES - {BOARD}))
@pytest.mark.parametrize("staged", [False, True])
def test_entire_native_host_policy_source_must_match_reviewed_output(source_tree, filename, staged):
    target = source_tree.root / filename
    target.write_text(target.read_text() + "/* unreviewed additional policy code */\n")
    if staged:
        git(source_tree.root, "add", filename)
    with pytest.raises(ValueError, match="Unexpected native host policy source"):
        record.check_sources()


def test_native_host_policy_patch_and_allowlist_are_pinned(source_tree):
    path = source_tree.recipe / "host-policy.patch"
    path.write_bytes(path.read_bytes() + b"unreviewed modification\n")
    with pytest.raises(ValueError, match="native host policy patch provenance"):
        record.check_sources()


@pytest.mark.parametrize("change,staged", [
    ("missing", False), ("extra", False), ("alter_original", True), ("wrong_mtime", True),
])
def test_entire_reviewed_web_generator_patch_must_match(source_tree, change, staged):
    if change == "missing":
        data = BASE_WEB_TOOL
    elif change == "extra":
        data = PATCHED_WEB_TOOL + "print('unreviewed additional code')\n"
    elif change == "alter_original":
        data = PATCHED_WEB_TOOL.replace("import gzip", "import gzip, os")
    else:
        data = PATCHED_WEB_TOOL.replace("mtime=0", "mtime=1")
    source_tree.web_tool.write_text(data)
    if staged:
        git(source_tree.root, "add", WEB_TOOL)
    with pytest.raises(ValueError):
        record.check_sources()
    assert source_tree.host_checks == []


@pytest.mark.parametrize("staged", [False, True])
def test_staged_and_unstaged_foreign_native_source_edits_are_rejected(source_tree, staged):
    fixture = source_tree
    (fixture.root / "native.c").write_text("/* unreviewed source change */\n")
    if staged:
        git(fixture.root, "add", "native.c")
    with pytest.raises(ValueError, match="modified source beyond the reviewed"):
        record.check_sources()
    assert fixture.host_checks == []


def test_untracked_native_source_is_not_hidden_by_matching_head_hash(source_tree):
    (source_tree.root / "new-native.c").write_text("/* unreviewed additional input */\n")
    with pytest.raises(ValueError, match="Unexpected untracked source"):
        record.check_sources()


@pytest.mark.parametrize("change", ["missing", "extra", "alter_original", "wrong_capacity"])
def test_entire_reviewed_board_patch_must_match(source_tree, change):
    if change == "missing":
        data = BASE_BOARD
    elif change == "extra":
        data = BASE_BOARD + BOARD_ADDITIONS + "CONFIG_UNREVIEWED=y\n"
    elif change == "alter_original":
        data = BASE_BOARD.replace("CONFIG_REFERENCE=y", "CONFIG_REFERENCE=n") + BOARD_ADDITIONS
    else:
        data = BASE_BOARD + BOARD_ADDITIONS.replace("BONDS=8", "BONDS=9")
    source_tree.board.write_text(data)
    with pytest.raises(ValueError, match="Unexpected board configuration patch"):
        record.check_sources()


@pytest.mark.parametrize("name", ["circuitpython", "esp_idf", "esp_nimble"])
def test_each_declared_source_commit_is_checked_against_actual_git(source_tree, name):
    source_tree.pins["sources"][name]["commit"] = "f" * 40
    source_tree.pins_path.write_text(json.dumps(source_tree.pins))
    with pytest.raises(ValueError, match="Unexpected pinned source: " + name):
        record.check_sources()


def test_target_tool_manifest_hash_cannot_drift(source_tree):
    source_tree.pins["reference_tools"]["idf_tools_json_sha256"] = "f" * 64
    source_tree.pins_path.write_text(json.dumps(source_tree.pins))
    with pytest.raises(ValueError, match="Unexpected IDF tools manifest"):
        record.check_sources()


@pytest.mark.parametrize("filename", [
    "espidf.constraints.v6.0.txt", "requirements-build.txt",
])
def test_active_security_dependency_file_tamper_is_rejected(source_tree, filename):
    path = source_tree.recipe / filename
    path.write_bytes(path.read_bytes() + b"# unreviewed changed snapshot\n")
    with pytest.raises(ValueError, match="Unexpected isolated security-build dependencies"):
        record.check_sources()


def test_old_constraint_digest_cannot_replace_active_security_digest(source_tree):
    source_tree.pins["security_build"]["constraints_sha256"] = source_tree.pins["reference_tools"]["constraints_sha256"]
    source_tree.pins_path.write_text(json.dumps(source_tree.pins))
    with pytest.raises(ValueError, match="Unexpected isolated security-build dependencies"):
        record.check_sources()


@pytest.fixture
def host_tools(monkeypatch):
    pins = {
        "security_build": {"python": "3.11.18", "cryptography": "50.0.0"},
        "reference_tools": {"cmake": "3.30.9", "ninja_python_package": "1.13.2",
                            "gcc": "esp-15.2.0_20251204"},
    }
    host = SimpleNamespace(platform="linux", version="3.11.18 synthetic Python")
    machine = SimpleNamespace(value="x86_64")
    metadata = SimpleNamespace(value="50.0.0")
    responses = {"cmake": "3.30.9", "ninja": "1.13.2",
                 "gcc": "xtensa-esp-elf-gcc (crosstool-NG esp-15.2.0_20251204) 15.2.0"}
    calls = []

    def version(name):
        assert name == "cryptography"
        return metadata.value

    def tool_command(*args):
        calls.append(args)
        if args[0] == "/opt/host-venv/bin/python" and len(args) == 3 and args[1] == "-c":
            for package in ("cmake", "ninja"):
                if 'version("' + package + '")' in args[2]:
                    return responses[package]
        expected_gcc = "/opt/idf-tools/tools/xtensa-esp-elf/esp-15.2.0_20251204/xtensa-esp-elf/bin/xtensa-esp-elf-gcc"
        if args == (expected_gcc, "--version"):
            return responses["gcc"]
        pytest.fail("Unexpected host command; fixtures must not launch tools: " + repr(args))

    monkeypatch.setattr(record, "sys", host)
    monkeypatch.setattr(record, "platform", SimpleNamespace(machine=lambda: machine.value))
    monkeypatch.setattr(record, "importlib", SimpleNamespace(metadata=SimpleNamespace(version=version)))
    monkeypatch.setattr(record, "command", tool_command)
    return SimpleNamespace(pins=pins, host=host, machine=machine, metadata=metadata,
                           responses=responses, calls=calls)


def test_observed_host_versions_must_match_declared_tool_pins(host_tools):
    record.check_host_tools(host_tools.pins)
    assert len(host_tools.calls) == 3


@pytest.mark.parametrize("field,value", [
    ("platform", "darwin"), ("machine", "aarch64"), ("python", "3.11.17 synthetic Python"),
    ("cryptography", "49.0.0"),
])
def test_unsupported_or_wrong_security_host_is_rejected_without_running_commands(host_tools, field, value):
    if field == "platform":
        host_tools.host.platform = value
    elif field == "machine":
        host_tools.machine.value = value
    elif field == "python":
        host_tools.host.version = value
    else:
        host_tools.metadata.value = value
    with pytest.raises(ValueError, match="Unexpected isolated build host or security dependencies"):
        record.check_host_tools(host_tools.pins)
    assert host_tools.calls == []


@pytest.mark.parametrize("tool,value", [("cmake", "3.30.8"), ("ninja", "1.13.1"), ("gcc", "old GCC 14.2.0")])
def test_changed_host_compiler_or_build_tool_is_rejected(host_tools, tool, value):
    host_tools.responses[tool] = value
    with pytest.raises(ValueError, match="Unexpected (pinned host tool|target GCC version)"):
        record.check_host_tools(host_tools.pins)


@pytest.fixture
def artifact_tree(tmp_path, monkeypatch):
    root, output = tmp_path / "source", tmp_path / "output"
    root.mkdir()
    output.mkdir()
    build = root / "ports/espressif/build-espressif_esp32s3_devkitc_1_n8r8"
    data = {
        "circuitpython-firmware.bin": b"synthetic app image",
        "firmware.elf": b"\x7fELF actual CircuitPython application",
        "esp-idf/sdkconfig": b"synthetic SDK config",
        "esp-idf/config/sdkconfig.h": b"synthetic SDK header",
        "esp-idf/partition_table/partition-table.bin": b"synthetic partition reference",
        "esp-idf/bootloader/bootloader.bin": b"synthetic bootloader reference",
        "esp-idf/circuitpython.elf": b"\x7fELF wrong IDF dummy project",
    }
    for name, content in data.items():
        path = build / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    mpy = root / "mpy-cross/build/mpy-cross"
    mpy.parent.mkdir(parents=True)
    mpy.write_bytes(b"synthetic pinned compiler")
    monkeypatch.setattr(record, "ROOT", root)
    monkeypatch.setattr(record, "BUILD", build)
    monkeypatch.setattr(record, "OUTPUT", output)
    return SimpleNamespace(root=root, build=build, output=output, data=data)


def test_actual_application_elf_is_used_even_when_idf_dummy_elf_exists(artifact_tree):
    fixture = artifact_tree
    result = record.copy_artifacts()
    assert result["elf"][0] == fixture.build / "firmware.elf"
    assert (fixture.output / "application.elf").read_bytes() == fixture.data["firmware.elf"]
    assert (fixture.output / "application.elf").read_bytes() != fixture.data["esp-idf/circuitpython.elf"]


def test_wrong_idf_dummy_elf_cannot_stand_in_for_missing_application(artifact_tree):
    fixture = artifact_tree
    (fixture.build / "firmware.elf").unlink()
    with pytest.raises(ValueError, match="Missing build artifact: application.elf"):
        record.copy_artifacts()
    assert not (fixture.output / "application.elf").exists()


@pytest.mark.parametrize("project_lock", [False, True])
def test_only_actual_project_dependency_lock_is_recorded(artifact_tree, project_lock):
    fixture = artifact_tree
    unrelated = fixture.root / "ports/espressif/esp-idf/examples/demo/dependencies.lock"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("unrelated SDK example lock\n")
    project = fixture.root / "ports/espressif/dependencies.lock"
    if project_lock:
        project.write_text("reviewed project component lock\n")
    result = record.copy_artifacts()
    if project_lock:
        assert result["managed_dependencies_lock"][0] == project
        assert (fixture.output / "managed-dependencies.lock").read_text() == project.read_text()
    else:
        assert "managed_dependencies_lock" not in result
        assert not (fixture.output / "managed-dependencies.lock").exists()


@pytest.mark.parametrize("vendor_reattempt", [False, True])
def test_recorded_manifest_captures_actual_web_patch_and_preserves_offline_boundaries(
        artifact_tree, monkeypatch, vendor_reattempt):
    fixture = artifact_tree
    recipe = fixture.root.parent / "recipe"
    recipe.mkdir()
    recipes = {
        "espidf.constraints.v6.0.txt": b"cryptography>=50.0.0,<50.1\n",
        "requirements-build.txt": b"cryptography==50.0.0\n",
        "bonds8-cccd24.patch": b"synthetic reviewed board patch\n",
        "reproducible-web-assets.patch": b"synthetic reviewed gzip mtime=0 patch\n",
        "hashlib-close.patch": b"synthetic reviewed native hash lifetime patch\n",
        "host-policy.patch": b"synthetic reviewed native host policy patch\n",
        "nimble-legacy-le-features.patch": b"synthetic reviewed NimBLE feature fallback\n",
        "nimble-csfc-upsert.patch": b"synthetic reviewed NimBLE CSFC update\n",
    }
    for name, data in recipes.items():
        (recipe / name).write_bytes(data)
    idf = fixture.root / "ports/espressif/esp-idf"
    (idf / "tools").mkdir(parents=True)
    (idf / "tools/tools.json").write_text('{"synthetic": "toolchain"}\n')
    config = "CONFIG_BT_NIMBLE_MAX_BONDS=8\nCONFIG_BT_NIMBLE_MAX_CCCDS=24\nCONFIG_BT_NIMBLE_NVS_PERSIST=y\nCONFIG_BT_NIMBLE_HS_PVCY=y\n"
    config += ("CONFIG_BT_NIMBLE_ENABLE_CONN_REATTEMPT=y\n" if vendor_reattempt else
               "# CONFIG_BT_NIMBLE_ENABLE_CONN_REATTEMPT is not set\n")
    (fixture.build / "esp-idf/sdkconfig").write_text(config)
    sources = dict.fromkeys(("circuitpython", "esp_idf", "esp_nimble"), "a" * 40)

    def provenance():
        for name in ("distro-manifest.txt", "python-packages.txt", "submodules.txt"):
            (fixture.output / name).write_text("synthetic recorded provenance\n")

    responses = {
        ("/opt/host-venv/bin/cmake", "--version"): "cmake version 3.30.9",
        ("/opt/host-venv/bin/ninja", "--version"): "1.13.2",
        ("xtensa-esp-elf-gcc", "--version"): "esp-15.2.0_20251204 GCC 15.2.0",
    }

    def known_command(*args):
        assert args in responses
        return responses[args]

    monkeypatch.setattr(record, "RECIPE", recipe)
    monkeypatch.setattr(record, "IDF", idf)
    monkeypatch.setattr(record, "check_sources", lambda: sources)
    monkeypatch.setattr(record, "provenance_files", provenance)
    monkeypatch.setattr(record, "command", known_command)
    monkeypatch.setattr(record, "sys", SimpleNamespace(version="3.11.18 synthetic Python"))
    monkeypatch.setattr(record, "importlib", SimpleNamespace(metadata=SimpleNamespace(version=lambda _name: "50.0.0")))
    monkeypatch.setenv("BM83_BUILDER_IMAGE", "sha256:" + "b" * 64)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1789146568")
    if vendor_reattempt:
        with pytest.raises(ValueError, match="NimBLE connection retries"):
            record.record()
        return
    record.record()
    manifest = json.loads((fixture.output / "build-manifest.json").read_text())
    assert manifest["inputs"]["web_assets_patch_sha256"] == digest(recipes["reproducible-web-assets.patch"])
    assert manifest["inputs"]["patch_sha256"] == digest(recipes["bonds8-cccd24.patch"])
    assert manifest["inputs"]["hashlib_close_patch_sha256"] == digest(recipes["hashlib-close.patch"])
    assert manifest["inputs"]["host_policy_patch_sha256"] == digest(recipes["host-policy.patch"])
    assert manifest["inputs"]["nimble_legacy_features_patch_sha256"] == digest(recipes["nimble-legacy-le-features.patch"])
    assert manifest["inputs"]["nimble_csfc_patch_sha256"] == digest(recipes["nimble-csfc-upsert.patch"])
    assert manifest["sources"] == sources
    image_contract = json.loads((fixture.output / "artifact-manifest.json").read_text())
    assert image_contract["configuration"]["CONFIG_BT_NIMBLE_ENABLE_CONN_REATTEMPT"] is False
    assert image_contract["hardware_accepted"] is False
    assert image_contract["app"]["offset"] == 0x10000
    assert image_contract["app"]["partition_size"] == 2 * 1024 * 1024


def test_provenance_records_both_python_environments_and_sorted_distro(artifact_tree, monkeypatch):
    fixture = artifact_tree
    responses = {
        ("git", "-C", str(fixture.root), "submodule", "status", "--recursive"): " aaaa lib/one\n bbbb lib/two",
        ("dpkg-query", "-W", "-f=${Package}=${Version}\n"): "zlib=2\nbase=1",
        ("/opt/idf-venv/bin/python", "-m", "pip", "freeze", "--all"): "cryptography==50.0.0\ncffi==2.1.1",
        ("/opt/host-venv/bin/python", "-m", "pip", "freeze", "--all"): "ninja==1.13.2\ncmake==3.30.9",
    }
    calls = []

    def known_command(*args):
        calls.append(args)
        assert args in responses
        return responses[args]

    monkeypatch.setattr(record, "command", known_command)
    record.provenance_files()
    assert set(calls) == set(responses)
    assert (fixture.output / "distro-manifest.txt").read_text() == "base=1\nzlib=2\n"
    assert (fixture.output / "python-packages.txt").read_text() == (
        "[idf]\ncffi==2.1.1\ncryptography==50.0.0\n[host]\ncmake==3.30.9\nninja==1.13.2\n")


@pytest.mark.parametrize("prefix", ["+", "U"])
def test_unexpected_recursive_submodule_commits_or_conflicts_are_rejected(artifact_tree, monkeypatch, prefix):
    def only_submodules(*args):
        assert args == ("git", "-C", str(artifact_tree.root), "submodule", "status", "--recursive")
        return prefix + "a" * 40 + " lib/changed"

    monkeypatch.setattr(record, "command", only_submodules)
    with pytest.raises(ValueError, match="submodule differs from the recorded gitlink"):
        record.provenance_files()
    assert not list(artifact_tree.output.iterdir())

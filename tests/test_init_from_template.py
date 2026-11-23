"""scripts/init_from_template.py rewrites the template's identity, and only that.

The unit tests use synthetic copies of the files the script edits, so they stay
valid in repositories that have already been initialized from the template.
"""

import ast
import importlib.util
import shutil
import subprocess  # nosec B404 - fixed git argv in isolated temporary repositories
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INIT = load("init_from_template", "scripts/init_from_template.py")
POLICY = load(
    "reliability_setup_for_template_tests", "scripts/check_reliability_setup.py"
)
GIT = shutil.which("git")
UPSTREAM = INIT.UPSTREAM_URL in (ROOT / "setup.py").read_text(encoding="utf-8")

AGENT = """---
name: Reliability runtime review
description: Read-only review.
target: vscode
tools: ['read', 'search']
user-invocable: true
disable-model-invocation: true
---

The owner authorized this profile on November 12.
"""
SYNTHETIC = {
    "setup.py": """from setuptools import setup, find_packages

setup(
    name="esp32-audio-remote",
    version="1.0.0rc1",
    description="CircuitPython-based audio remote",
    author="Brian Wedderburn",
    author_email="78520287+bwedderburn@users.noreply.github.com",
    url="https://github.com/bwedderburn/BM83-ESP32-S3-Nextion",
    packages=find_packages(where="firmware/circuitpython"),
    python_requires=">=3.7",
)
""",
    "README.md": "# BM83 Remote\n\nUpstream README.\n",
    "AGENTS.md": "# Project operating instructions\n\nThe November 12 task has standing owner approval.\n",
    "CLAUDE.md": "# Working notes for Claude\n\nCheck the active session every five minutes.\n",
    "LICENSE": "MIT License\n\nCopyright (c) 2026 Brian Wedderburn\n\nPermission is hereby granted.\n",
    INIT.ISSUE_FORM: (
        "name: Reliability investigation\nassignees: [bwedderburn]\nbody:\n"
        "  - type: input\n    id: owner\n    attributes:\n      label: Owner\n"
        '      value: "@bwedderburn"\n'
    ),
    "scripts/package_source_release.py": 'PROJECT_URL = "https://github.com/bwedderburn/BM83-ESP32-S3-Nextion"\n',
    "firmware/crowpanel-remote/src/artwork.cpp": (
        'static const char *kUa = "BM83-CrowPanel/0.1 '
        '(https://github.com/bwedderburn/BM83-ESP32-S3-Nextion)";\n'
    ),
    ".github/copilot-instructions.md": "# Copilot instructions\n\nThe owner authorizes direct pushes.\n",
    ".github/instructions/bm83-reliability.instructions.md": (
        '---\napplyTo: "firmware/**"\n---\n\n# Verified reliability\n\nCodex owns this work.\n'
    ),
    ".github/agents/reliability-runtime.agent.md": AGENT,
    ".github/agents/reliability-delivery.agent.md": AGENT.replace(
        "runtime", "delivery"
    ),
    INIT.VENDOR_DIR
    + "/README.md": "# BM83 vendor reference archive\n\nThird-party files.\n",
    INIT.VENDOR_DIR + "/manifest.json": "{}\n",
    INIT.VENDOR_DIR + "/datasheets/guide.pdf": "%PDF synthetic\n",
    INIT.VENDOR_DIR + "/firmware/demo.HEX": ":00000001FF\n",
    INIT.VENDOR_DIR + "/tools/utility.exe": "MZ synthetic\n",
}
NEW_URL = "https://github.com/maker/garage-remote"


def write_tree(root, files):
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))


@pytest.fixture
def checkout(tmp_path):
    write_tree(tmp_path, SYNTHETIC)
    return tmp_path


def run(root, *extra):
    return INIT.main(
        [
            "--root",
            str(root),
            "--repo",
            "maker/garage-remote",
            "--name",
            "Garage BM83 Remote",
            "--author",
            "Ada Maker",
            "--email",
            "ada@example.com",
            *extra,
        ]
    )


def snapshot(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).parts[0] != ".git"
    }


def setup_keywords(text):
    call = next(
        node
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "setup"
    )
    return {
        keyword.arg: keyword.value.value
        for keyword in call.keywords
        if isinstance(keyword.value, ast.Constant)
    }


def git(root, *arguments):
    subprocess.run(  # nosec B603 - fixed git argv in a temporary repository
        [
            GIT,
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            *arguments,
        ],
        check=True,
        capture_output=True,
    )


def test_dry_run_lists_changes_and_writes_nothing(checkout, capsys):
    before = snapshot(checkout)
    assert run(checkout) == 0
    assert snapshot(checkout) == before
    output = capsys.readouterr().out
    assert "Dry run only" in output
    for relative in ("setup.py", "AGENTS.md", "LICENSE", INIT.ISSUE_FORM):
        assert relative in output


def test_apply_rewrites_the_project_identity(checkout):
    assert run(checkout, "--apply") == 0
    assert setup_keywords((checkout / "setup.py").read_text(encoding="utf-8")) == {
        "name": "garage-bm83-remote",
        "version": "0.1.0.dev0",
        "description": INIT.DEFAULT_DESCRIPTION,
        "author": "Ada Maker",
        "author_email": "ada@example.com",
        "url": NEW_URL,
        "python_requires": ">=3.7",
    }
    assert (
        (checkout / "README.md")
        .read_text(encoding="utf-8")
        .startswith("# Garage BM83 Remote\n")
    )
    for relative in ("AGENTS.md", "CLAUDE.md"):
        text = (checkout / relative).read_text(encoding="utf-8")
        assert "Garage BM83 Remote" in text
        assert "November" not in text and "five minutes" not in text
    license_lines = (checkout / "LICENSE").read_text(encoding="utf-8").splitlines()
    assert "Copyright (c) 2026 Brian Wedderburn" in license_lines
    assert any(
        line.startswith("Copyright (c) ") and line.endswith(" Ada Maker")
        for line in license_lines
    )
    form = yaml.safe_load((checkout / INIT.ISSUE_FORM).read_text(encoding="utf-8"))
    assert form["assignees"] == ["maker"]
    assert form["body"][0]["attributes"]["value"] == "@maker"
    for relative in INIT.URL_FILES:
        text = (checkout / relative).read_text(encoding="utf-8")
        assert INIT.UPSTREAM_URL not in text and NEW_URL in text
    assert (checkout / INIT.VENDOR_DIR / "tools/utility.exe").is_file()


def test_inherited_instructions_get_one_notice_after_their_front_matter(checkout):
    assert run(checkout, "--apply") == 0
    for relative in INIT.INHERITED_INSTRUCTIONS:
        text = (checkout / relative).read_text(encoding="utf-8")
        assert text.count(INIT.NOTICE_MARK) == 1
        if text.startswith("---\n"):
            assert isinstance(yaml.safe_load(text.split("---", 2)[1]), dict)
            assert text.split("---", 2)[2].lstrip("\n").startswith(INIT.NOTICE_MARK)
        else:
            assert text.startswith(INIT.NOTICE_MARK)
    for name in ("runtime", "delivery"):
        text = (
            checkout / ".github/agents" / ("reliability-" + name + ".agent.md")
        ).read_text(encoding="utf-8")
        assert POLICY.agent_errors(yaml.safe_load(text.split("---", 2)[1])) == []


def test_second_apply_changes_nothing(checkout, capsys):
    assert run(checkout, "--apply") == 0
    first = snapshot(checkout)
    capsys.readouterr()
    assert run(checkout, "--apply") == 0
    assert snapshot(checkout) == first
    assert "Nothing to change" in capsys.readouterr().out


def test_strip_vendor_keeps_the_readme_and_hash_manifest(checkout):
    assert run(checkout, "--strip-vendor", "--apply") == 0
    vendor = checkout / INIT.VENDOR_DIR
    assert sorted(path.name for path in vendor.rglob("*")) == [
        "README.md",
        "manifest.json",
    ]
    assert INIT.VENDOR_NOTE_HEADING in (vendor / "README.md").read_text(
        encoding="utf-8"
    )


def test_refuses_to_rewrite_the_template_itself(checkout, capsys):
    before = snapshot(checkout)
    code = INIT.main(
        [
            "--root",
            str(checkout),
            "--repo",
            INIT.UPSTREAM_SLUG,
            "--name",
            "Copy",
            "--apply",
        ]
    )
    assert code == 2
    assert "template itself" in capsys.readouterr().err
    assert snapshot(checkout) == before


def test_unexpected_setup_py_layout_stops_before_writing(checkout, capsys):
    (checkout / "setup.py").write_text(
        'from setuptools import setup\nsetup(name="x")\n', encoding="utf-8"
    )
    before = snapshot(checkout)
    assert run(checkout, "--apply") == 2
    assert "setup.py" in capsys.readouterr().err
    assert snapshot(checkout) == before


@pytest.mark.skipif(GIT is None, reason="git not available")
def test_apply_requires_a_clean_tree_unless_allowed(checkout, capsys):
    git(checkout, "init", "-q")
    git(checkout, "add", "-A")
    git(checkout, "commit", "-q", "-m", "template copy")
    (checkout / "notes.txt").write_text("local edit\n", encoding="utf-8")
    before = snapshot(checkout)
    assert run(checkout, "--apply") == 2
    assert "uncommitted changes" in capsys.readouterr().err
    assert snapshot(checkout) == before
    assert run(checkout, "--apply", "--allow-dirty") == 0


@pytest.mark.skipif(GIT is None, reason="git not available")
@pytest.mark.parametrize(
    "remote",
    [
        "git@github.com:maker/garage-remote.git",
        "https://github.com/maker/garage-remote.git",
        "https://github.com/maker/garage-remote",
    ],
)
def test_origin_remote_names_the_new_repository(checkout, remote):
    git(checkout, "init", "-q")
    git(checkout, "remote", "add", "origin", remote)
    assert INIT.origin_slug(checkout) == "maker/garage-remote"


@pytest.mark.skipif(
    not UPSTREAM, reason="only meaningful in the template repository itself"
)
def test_the_real_template_files_initialize_cleanly(tmp_path):
    named = (
        "setup.py",
        "README.md",
        "AGENTS.md",
        "CLAUDE.md",
        "LICENSE",
        INIT.ISSUE_FORM,
        *INIT.URL_FILES,
        *INIT.INHERITED_INSTRUCTIONS,
    )
    for relative in named:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    for relative in INIT.URL_FILES:
        assert INIT.UPSTREAM_URL in (ROOT / relative).read_text(
            encoding="utf-8"
        ), relative
    assert run(tmp_path, "--apply") == 0
    assert (
        setup_keywords((tmp_path / "setup.py").read_text(encoding="utf-8"))["url"]
        == NEW_URL
    )
    form = yaml.safe_load((tmp_path / INIT.ISSUE_FORM).read_text(encoding="utf-8"))
    assert form["assignees"] == ["maker"]
    assert POLICY.agent_errors({}) != []
    for name in ("runtime", "delivery"):
        text = (
            tmp_path / ".github/agents" / ("reliability-" + name + ".agent.md")
        ).read_text(encoding="utf-8")
        assert POLICY.agent_errors(yaml.safe_load(text.split("---", 2)[1])) == []

"""Isolate disposable release-test repositories from caller Git settings."""

import os


HOSTILE_GIT_CONFIG_NAME = "hostile-gitconfig"
HOSTILE_DEFAULT_BRANCH = "hostile-fixture-branch"


def git_environment():
    """Keep the host environment without inherited Git repository/config/identity selectors."""
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_SYSTEM=os.devnull,
                       GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    return environment


def set_hostile_git_environment(tmp_path, monkeypatch):
    """Install synthetic caller settings that must not influence fixture Git commands."""
    hooks = tmp_path / "hostile-hooks"
    hooks.mkdir()
    hook = hooks / "pre-commit"
    hook.write_bytes(b"#!/bin/sh\nexit 93\n")
    hook.chmod(0o755)
    template = tmp_path / "hostile-git-template"
    (template / "hooks").mkdir(parents=True)
    (template / "hooks/pre-commit").write_bytes(hook.read_bytes())
    (template / "hooks/pre-commit").chmod(0o755)
    (template / "hostile-template-marker").write_bytes(b"must not enter fixture repository\n")
    configuration = tmp_path / HOSTILE_GIT_CONFIG_NAME
    configuration.write_text(
        '[core]\n hooksPath = "' + hooks.as_posix() + '"\n'
        '[commit]\n gpgSign = true\n'
        '[gpg]\n program = "' + (tmp_path / "missing-fixture-signer").as_posix() + '"\n'
        '[init]\n templateDir = "' + template.as_posix() + '"\n'
        ' defaultBranch = ' + HOSTILE_DEFAULT_BRANCH + '\n', encoding="utf-8"
    )
    unused = {
        "GIT_DIR": tmp_path / "must-not-be-used-as-git-dir",
        "GIT_COMMON_DIR": tmp_path / "must-not-be-used-as-common-dir",
        "GIT_WORK_TREE": tmp_path / "must-not-be-used-as-work-tree",
        "GIT_INDEX_FILE": tmp_path / "must-not-be-used-as-index",
    }
    values = {
        "GIT_CONFIG_GLOBAL": str(configuration), "GIT_CONFIG_SYSTEM": str(configuration),
        "GIT_CONFIG_COUNT": "4", "GIT_CONFIG_KEY_0": "commit.gpgsign", "GIT_CONFIG_VALUE_0": "true",
        "GIT_CONFIG_KEY_1": "core.hooksPath", "GIT_CONFIG_VALUE_1": str(hooks),
        "GIT_CONFIG_KEY_2": "init.templateDir", "GIT_CONFIG_VALUE_2": str(template),
        "GIT_CONFIG_KEY_3": "init.defaultBranch", "GIT_CONFIG_VALUE_3": HOSTILE_DEFAULT_BRANCH,
        "GIT_TEMPLATE_DIR": str(template),
        "GIT_AUTHOR_NAME": "Inherited Author", "GIT_AUTHOR_EMAIL": "inherited-author@example.invalid",
        "GIT_COMMITTER_NAME": "Inherited Committer", "GIT_COMMITTER_EMAIL": "inherited-committer@example.invalid",
        "GIT_AUTHOR_DATE": "not-a-valid-fixture-date", "GIT_COMMITTER_DATE": "not-a-valid-fixture-date",
    }
    monkeypatch.delenv("GIT_CONFIG_NOSYSTEM", raising=False)
    for name, value in {**values, **{name: str(path) for name, path in unused.items()}}.items():
        monkeypatch.setenv(name, value)
    return unused

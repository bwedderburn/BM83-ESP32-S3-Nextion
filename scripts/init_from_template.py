#!/usr/bin/env python3
"""Turn a repository created from this template into its own project.

GitHub's "Use this template" copies every file from the template's default
branch, including the upstream project's identity and its owner-specific
agent notes. This script rewrites those so they do not carry over:

* setup.py metadata, the README and the reliability issue-form owner;
* the project URL used by the release packager and by the CrowPanel artwork
  client's User-Agent;
* AGENTS.md and CLAUDE.md, replaced with neutral starters, plus a notice on
  the inherited Copilot instructions, whose dated authorizations applied only
  to the upstream repository;
* LICENSE gains your copyright line; the original MIT notice stays, as the
  license requires;
* with --strip-vendor, the third-party vendor binaries (about 33 MB).

It is a dry run unless --apply is given. It edits files inside this checkout
only and never contacts a device or the network.
"""

import argparse
import datetime
import json
import re
import subprocess  # nosec B404 - fixed git argv only, never a shell
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_SLUG = "bwedderburn/BM83-ESP32-S3-Nextion"
UPSTREAM_URL = "https://github.com/" + UPSTREAM_SLUG
UPSTREAM_OWNER = UPSTREAM_SLUG.split("/")[0]
DEFAULT_DESCRIPTION = (
    "CircuitPython BM83 Bluetooth audio controller created from the "
    "BM83-ESP32-S3-Nextion template"
)

# Files where the upstream URL names the running project rather than citing it.
URL_FILES = (
    "scripts/package_source_release.py",
    "firmware/crowpanel-remote/src/artwork.cpp",
)
# Agent instructions kept for their technical content.
INHERITED_INSTRUCTIONS = (
    ".github/copilot-instructions.md",
    ".github/instructions/bm83-reliability.instructions.md",
    ".github/agents/reliability-runtime.agent.md",
    ".github/agents/reliability-delivery.agent.md",
)
ISSUE_FORM = ".github/ISSUE_TEMPLATE/reliability.yml"
VENDOR_DIR = "docs/reference/vendor/bm83"
VENDOR_KEEP = frozenset({"README.md", "manifest.json"})
VENDOR_NOTE_HEADING = "## Removed by template initialization"
NOTICE_MARK = "<!-- template-init: inherited -->"
SETUP_FIELDS = ("name", "version", "description", "author", "author_email", "url")

SLUG_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REMOTE_PATTERN = re.compile(
    r"github\.com[:/]+([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)
PACKAGE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class TemplateError(Exception):
    """A precondition failed; nothing was written."""


def read(root, relative):
    """Return a file's exact text (no newline translation), or None if absent."""
    path = root / relative
    return path.read_bytes().decode("utf-8") if path.is_file() else None


class Plan:
    """Planned writes and deletes, relative to the checkout root."""

    def __init__(self, root):
        self.root = root
        self.writes = {}
        self.deletes = {}

    def write(self, relative, text, reason):
        if read(self.root, relative) != text:
            self.writes[relative] = (text, reason)

    def delete(self, relative, reason):
        self.deletes[relative] = reason

    def __len__(self):
        return len(self.writes) + len(self.deletes)

    def describe(self):
        lines = [
            "  update  %-58s %s" % (path, reason)
            for path, (_, reason) in sorted(self.writes.items())
        ]
        lines += [
            "  delete  %-58s %s" % (path, reason)
            for path, reason in sorted(self.deletes.items())
        ]
        return "\n".join(lines)

    def touched(self):
        """Paths to stage: every written file, with the vendor folder named once."""
        paths = sorted(self.writes)
        if self.deletes:
            paths = [path for path in paths if not path.startswith(VENDOR_DIR + "/")]
            paths.append(VENDOR_DIR)
        return paths

    def apply(self):
        for relative, (text, _) in self.writes.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        for relative in self.deletes:
            (self.root / relative).unlink()
        for relative in sorted(
            {str(Path(path).parent) for path in self.deletes}, reverse=True
        ):
            folder = self.root / relative
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()


def git(root, *arguments):
    """Run git in the checkout; return (exit code, stdout), or (None, "") without git."""
    try:
        result = subprocess.run(  # nosec B603 B607 - fixed git argv, no shell, no user command text
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return result.returncode, result.stdout


def origin_slug(root):
    code, output = git(root, "remote", "get-url", "origin")
    match = REMOTE_PATTERN.search(output.strip()) if code == 0 else None
    return match.group(1) + "/" + match.group(2) if match else None


def git_config(root, key):
    code, output = git(root, "config", "--get", key)
    return output.strip() if code == 0 else ""


def package_name(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def resolve_options(args, root):
    name = " ".join(args.name.split())
    if not name:
        raise TemplateError("--name must not be empty")
    slug = args.repo or origin_slug(root)
    if not slug:
        raise TemplateError("no GitHub 'origin' remote found; pass --repo OWNER/NAME")
    if not SLUG_PATTERN.match(slug):
        raise TemplateError("--repo must look like OWNER/NAME, not %r" % slug)
    if slug.lower() == UPSTREAM_SLUG.lower() and not args.force:
        raise TemplateError(
            "this checkout is the template itself (%s). Create a new repository from it "
            "('Use this template'), clone that, and run this script there."
            % UPSTREAM_SLUG
        )
    package = args.package or package_name(name)
    if not PACKAGE_PATTERN.match(package):
        raise TemplateError(
            "cannot derive a package name from %r; pass --package" % name
        )
    owner = slug.split("/")[0]
    return {
        "name": name,
        "slug": slug,
        "owner": owner,
        "url": "https://github.com/" + slug,
        "package": package,
        "description": args.description or DEFAULT_DESCRIPTION,
        "author": args.author or git_config(root, "user.name") or owner,
        "email": (
            args.email if args.email is not None else git_config(root, "user.email")
        ),
        "year": datetime.date.today().year,
    }


def rewrite_setup(text, values):
    for key in SETUP_FIELDS:
        pattern = re.compile(r'(\b%s=)"[^"\n]*"' % key)
        literal = json.dumps(values[key], ensure_ascii=False)
        text, count = pattern.subn(lambda match: match.group(1) + literal, text)
        if count != 1:
            raise TemplateError(
                'setup.py: expected one %s="..." literal, found %d; edit it by hand'
                % (key, count)
            )
    return text


def add_copyright(text, holder, year):
    line = "Copyright (c) %d %s" % (year, holder)
    if line in text:
        return text
    matches = list(re.finditer(r"^Copyright \(c\).*$", text, re.MULTILINE))
    if not matches:
        raise TemplateError("LICENSE has no 'Copyright (c)' line to extend")
    end = matches[-1].end()
    return text[:end] + "\n" + line + text[end:]


def with_notice(text, name):
    if NOTICE_MARK in text:
        return text
    notice = (
        NOTICE_MARK + "\n"
        "> **Inherited from the BM83-ESP32-S3-Nextion template.** Dated tasks, sessions,\n"
        "> devices and owner authorizations in this file describe the upstream repository\n"
        "> and grant nothing in %s. Revise this file for the new project.\n\n" % name
    )
    if text.startswith("---\n"):
        end = text.find("\n---\n", 3)
        if end != -1:
            split = end + len("\n---\n")
            return text[:split] + "\n" + notice + text[split:].lstrip("\n")
    return notice + text


def readme(values):
    return """# {name}

{description}.

Created from the [BM83-ESP32-S3-Nextion template]({upstream}): CircuitPython on an
ESP32-S3 controlling a Microchip BM83 Bluetooth audio module over UART, a Nextion
touchscreen and an optional CrowPanel remote.

## Quick start in VS Code

1. Install Python 3.11-3.13 (or [uv](https://docs.astral.sh/uv/)), Git and VS Code.
2. From the repository root, run the one-time setup:

   Windows (PowerShell)

   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\setup-dev.ps1
   ```

   Linux, macOS or WSL (bash)

   ```
   bash scripts/setup-dev.sh
   ```

3. Open the folder in VS Code, select the `.venv` interpreter and run the
   **BM83: host tests** task.

[docs/guides/vscode.md](docs/guides/vscode.md) covers the tasks, extensions, dev
container and serial console.

## Repository layout

```text
firmware/circuitpython/    Canonical controller source
firmware/crowpanel-remote/ CrowPanel Arduino/LVGL source (PlatformIO)
addons/universe-badge/     Optional badge client and host tests
dist/                      Generated CircuitPython deployment artifacts
docs/                      Guides, references and the inherited upstream records
scripts/                   Setup, host checks and build/support scripts
tests/                     Host regression tests (no hardware needed)
tools/                     Provisioning, diagnostics and pinned native-build recipes
```

## Development and validation

```sh
python -m pytest -q
python -m flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
python scripts/check_reliability_setup.py
```

Host tests do not establish radio, audio or display behavior on a device.

## License

[MIT](LICENSE). Third-party material keeps its own terms.
""".format(
        name=values["name"],
        description=values["description"].rstrip("."),
        upstream=UPSTREAM_URL,
    )


def agents(values):
    return """# Project operating instructions

These starter rules came from the [BM83-ESP32-S3-Nextion template]({upstream}).
Revise them as {name} develops. They grant no device or publication authority:
take that from the owner's current instructions.

## Sources of truth

- Controller source: `firmware/circuitpython/`. `dist/circuitpython/` is generated
  by `build_mpy.sh`; never edit it by hand.
- CrowPanel firmware: `firmware/crowpanel-remote/` (PlatformIO).
- Host tests in `tests/` need no hardware. Passing them does not establish radio,
  audio or display behavior on a device.

## Before pushing

- `python -m pytest -q`
- `python -m flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics`
- `python scripts/check_reliability_setup.py`
- Stage exact paths. Keep credentials, Wi-Fi settings, device captures and backups
  out of Git.

## Hardware work

- Deploy, flash or open a serial console only when the owner's current task asks
  for it.
- Back up the device before writing to it and hash-verify every copied file.
- Record observed results separately from hypotheses.
""".format(name=values["name"], upstream=UPSTREAM_URL)


def claude(values):
    return """# Notes for Claude

Read `AGENTS.md` first; it applies to every coding agent working on {name}.

- Canonical CircuitPython source is `firmware/circuitpython/`; regenerate `dist/`
  with `build_mpy.sh` instead of editing it.
- Run the host gates listed in `AGENTS.md` before proposing a push.
- Treat screenshots and AI replies as leads; confirm them against the files.
""".format(name=values["name"])


def plan_identity(plan, values):
    setup_text = read(plan.root, "setup.py")
    if setup_text is None:
        raise TemplateError(
            "setup.py is missing; run this from a checkout of the template"
        )
    setup_values = {
        "name": values["package"],
        "version": "0.1.0.dev0",
        "description": values["description"],
        "author": values["author"],
        "author_email": values["email"],
        "url": values["url"],
    }
    plan.write("setup.py", rewrite_setup(setup_text, setup_values), "package metadata")
    plan.write("README.md", readme(values), "starter README for the new project")
    plan.write(
        "AGENTS.md",
        agents(values),
        "neutral agent rules (upstream authorizations dropped)",
    )
    plan.write(
        "CLAUDE.md",
        claude(values),
        "neutral Claude notes (upstream session notes dropped)",
    )
    license_text = read(plan.root, "LICENSE")
    if license_text is not None:
        plan.write(
            "LICENSE",
            add_copyright(license_text, values["author"], values["year"]),
            "add your copyright line; the original notice stays",
        )
    form = read(plan.root, ISSUE_FORM)
    if form is not None:
        owner = values["owner"]
        updated = form.replace(
            "assignees: [%s]" % UPSTREAM_OWNER, "assignees: [%s]" % owner
        ).replace('"@%s"' % UPSTREAM_OWNER, '"@%s"' % owner)
        plan.write(ISSUE_FORM, updated, "issue-form owner")
    for relative in URL_FILES:
        text = read(plan.root, relative)
        if text is not None:
            plan.write(
                relative, text.replace(UPSTREAM_URL, values["url"]), "project URL"
            )
    for relative in INHERITED_INSTRUCTIONS:
        text = read(plan.root, relative)
        if text is not None:
            plan.write(
                relative,
                with_notice(text, values["name"]),
                "mark inherited upstream authorizations",
            )


def plan_vendor_strip(plan):
    folder = plan.root / VENDOR_DIR
    if not folder.is_dir():
        return
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(plan.root).as_posix()
        if path.is_file() and not (path.parent == folder and path.name in VENDOR_KEEP):
            plan.delete(relative, "third-party vendor binary")
    readme_path = VENDOR_DIR + "/README.md"
    text = read(plan.root, readme_path)
    if text is not None and VENDOR_NOTE_HEADING not in text:
        note = (
            "\n" + VENDOR_NOTE_HEADING + "\n\n"
            "`scripts/init_from_template.py --strip-vendor` removed the binaries from this\n"
            "project. `manifest.json` keeps their names, sizes and SHA-256 hashes; obtain\n"
            "current copies from the vendor if you need them.\n"
        )
        plan.write(
            readme_path,
            text.rstrip("\n") + "\n" + note,
            "note the removed vendor binaries",
        )


def check_clean(root, allow_dirty):
    code, output = git(root, "status", "--porcelain")
    if code == 0 and output.strip() and not allow_dirty:
        raise TemplateError(
            "uncommitted changes are present. Commit or stash them first so the "
            "template changes form one reviewable diff (or pass --allow-dirty)."
        )


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Rewrite the BM83-ESP32-S3-Nextion template's identity for a new project. "
        "Dry run unless --apply is given."
    )
    parser.add_argument(
        "--name", required=True, help='project name, e.g. "Garage BM83 Remote"'
    )
    parser.add_argument(
        "--repo",
        help="GitHub OWNER/NAME of the new repository (default: the origin remote)",
    )
    parser.add_argument(
        "--package",
        help="distribution name for setup.py (default: derived from --name)",
    )
    parser.add_argument("--description", help="one-line project description")
    parser.add_argument(
        "--author", help="copyright holder and setup.py author (default: git user.name)"
    )
    parser.add_argument(
        "--email", help="setup.py author_email (default: git user.email)"
    )
    parser.add_argument(
        "--strip-vendor",
        action="store_true",
        help="also delete the third-party binaries under " + VENDOR_DIR,
    )
    parser.add_argument(
        "--apply", action="store_true", help="write the planned changes"
    )
    parser.add_argument(
        "--allow-dirty", action="store_true", help="apply even with uncommitted changes"
    )
    parser.add_argument("--force", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--root", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    try:
        values = resolve_options(args, root)
        plan = Plan(root)
        plan_identity(plan, values)
        if args.strip_vendor:
            plan_vendor_strip(plan)
        if args.apply and len(plan):
            check_clean(root, args.allow_dirty)
    except TemplateError as error:
        print("init_from_template: " + str(error), file=sys.stderr)
        return 2
    if not len(plan):
        print("Nothing to change: %s is already initialized." % values["name"])
        return 0
    print('Template initialization for "%s" (%s):' % (values["name"], values["slug"]))
    print(plan.describe())
    if not args.apply:
        print(
            "\nDry run only; nothing was written. Re-run with --apply to make these changes."
        )
        return 0
    plan.apply()
    print("\nApplied %d change(s). Next:" % len(plan))
    print("  1. Review:  git status && git diff")
    print(
        "  2. Verify:  python -m pytest -q   (VS Code task: CI parity: lint gate, host tests, policy)"
    )
    print("  3. Commit:  git add -A -- %s" % " ".join(plan.touched()))
    print(
        '              git commit -m "chore: initialize %s from template"'
        % values["name"].replace('"', "'")
    )
    print("  4. Finish the manual checklist in docs/guides/template.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Start a new project from this template

BM83-ESP32-S3-Nextion is a GitHub template repository. A repository created from
it starts with a copy of these files (firmware, tests, CI, the VS Code workspace
and the dev container) under a new, single-commit history.

## 1. Create the repository

On GitHub, choose **Use this template > Create a new repository**. With the GitHub
CLI (add `--private` instead of `--public` for a private repository):

```
gh repo create OWNER/NAME --template bwedderburn/BM83-ESP32-S3-Nextion --public --clone
```

## 2. Set up VS Code

Open the new folder and run the one-time setup from the
[VS Code guide](vscode.md): `scripts\setup-dev.ps1` on Windows or
`bash scripts/setup-dev.sh` elsewhere.

## 3. Replace the upstream identity

Preview the changes first; the dry run writes nothing:

```
python scripts/init_from_template.py --name "Garage BM83 Remote"
```

Apply them (the working tree must be clean):

```
python scripts/init_from_template.py --name "Garage BM83 Remote" --apply
```

In VS Code, the tasks **Template: initialize new project (dry run)** and
**(apply)** do the same and prompt for the name. The script reads `OWNER/NAME`
from the `origin` remote (override with `--repo`), and the author from
`git config` (override with `--author` and `--email`). It refuses to run in the
template repository itself.

| File | Change |
| --- | --- |
| `setup.py` | Package name, version `0.1.0.dev0`, description, author and URL |
| `README.md` | A starter README for the new project |
| `AGENTS.md`, `CLAUDE.md` | Neutral starter rules; the upstream owner's dated authorizations and session notes are dropped |
| `.github/copilot-instructions.md`, `.github/instructions/`, `.github/agents/` | A notice that their dated authorizations applied to the upstream repository only |
| `LICENSE` | Adds your copyright line; the original MIT notice stays, as the license requires |
| `.github/ISSUE_TEMPLATE/reliability.yml` | The new owner as assignee |
| `scripts/package_source_release.py`, `firmware/crowpanel-remote/src/artwork.cpp` | The project URL (release links and the artwork client's User-Agent) |

`--strip-vendor` also deletes the Microchip datasheets, firmware packages and
utility under `docs/reference/vendor/bm83/` (about 33 MB), keeping its README and
hash manifest. "Use this template" has already copied them into the new
repository's first commit, so they stay in its history. If they must never be in
the new history, clone the template with `--depth 1`, run the script with
`--strip-vendor --apply --allow-dirty`, delete `.git`, and push a fresh
`git init` history to an empty repository instead.

## 4. Verify and commit

Run **CI parity: lint gate, host tests, policy** (or `python -m pytest -q`), then
commit the paths the script printed.

## 5. Finish by hand

- **BLE name.** The controller advertises `BLE_NAME` from
  `firmware/circuitpython/main.py` (also `CIRCUITPY_BLE_NAME` in
  `settings.example.toml`). Keep it short: name cycling appends a suffix within
  the advertising payload (`tests/test_blehid_advertising.py`).
- **Mac metadata bridge.** Its launchd label `com.bwedderburn.bm83-metadata-bridge`
  is set in `tools/setup_mac_metadata_bridge.py` and the
  [bridge guide](mac-metadata-bridge.md).
- **Codacy.** `.github/workflows/codacy.yml` uploads SARIF to code scanning. A
  private repository needs GitHub Code Security for that upload; otherwise
  disable the workflow. `CODACY_PROJECT_TOKEN` is optional.
- **Branch protection.** Require the `build` checks from `python-package.yml` and
  `host-security` from `host-security.yml` in the new repository's settings.
- **Upstream records.** `docs/reliability/`, `docs/releases/`, `docs/validation/`,
  `docs/reviews/` and `RELEASE_NOTES-v1.0.0-rc.1.md` describe the upstream
  project. The release packager (`scripts/package_source_release.py`) and its
  tests read several of them, so remove the packager, its tests and those records
  together if you do not need them.
- **Hardware and secrets.** Pins live in `firmware/circuitpython/main.py`. Merge
  `settings.example.toml` into the device's `CIRCUITPY/settings.toml`, and keep
  real credentials out of Git (`secrets.py`, `.env` and the private JSON profiles
  are already git-ignored).

# Working notes for Claude in this repo

## Bash sandbox is a snapshot — pull origin before editing

The bash sandbox mount of this repo (`/sessions/.../mnt/BM83-ESP32-S3-Nextion/`)
is **not** a live view of the Windows working tree. The file tools
(`Read` / `Edit` / `Write`) operate on the real Windows path
(`C:\Users\brian\Repos\BM83-ESP32-S3-Nextion\...`) and are authoritative.
The bash mount is a snapshot that lags behind whatever Brian has pulled or
edited locally — sometimes by days. Writes from bash can propagate outward
to the real disk, which means a "fix" applied to the stale snapshot can
corrupt the real files (e.g. appending duplicate content past a file's
true end that bash thought was truncated).

**Rule:** before doing any code edits, refresh the bash mount so it
matches the Windows tree.

```bash
cd /sessions/<id>/mnt/BM83-ESP32-S3-Nextion
git fetch origin
git checkout <the branch Brian is on>
git pull --ff-only
```

If `git pull` won't fast-forward, stop and ask Brian which branch / state
he wants the bash view aligned to — don't force-reset.

**Symptoms that the mount is stale (and you should pull before doing
anything else):**

- `wc -l` / `tail` / `od` show a file truncated mid-statement, but the
  `Read` tool shows the same file is complete.
- `python -m ast` parsing the bash-mount file fails with
  `unterminated triple-quoted string`, while the file-tool view parses
  cleanly.
- The bash file size / mtime is older than recent file-tool writes
  Brian or Claude just made.

**Do not** "repair" the bash file by appending content via `cat >> file
<<EOF` heredocs. That writes garbage to disk because the file tool's
view of the same file is already complete; you'll end up with the real
content followed by a duplicate fragment.

## Source-of-truth layout

- `firmware/circuitpython/` — canonical source. `deploy.sh` rsyncs from
  here to `CIRCUITPY` (`.py` files, not `.mpy`).
- `dist/circuitpython/` — build artifact from `build_mpy.sh`. `main.py`
  is a verbatim copy of the firmware version; `lib/**/*.mpy` are
  compiled with `mpy-cross -O2`. Regenerate after any change under
  `firmware/circuitpython/lib/`.

When `firmware/` changes, run `build_mpy.sh` to refresh `dist/`. Do not
hand-edit `dist/` — it will be overwritten on the next build.


## Current change workflow — direct commit and push

The owner has moved the active paired BM83/Universe maintenance work to Codex
because the Copilot allowance is exhausted. Commit validated changes and push
normally to `origin/main`; do not create PRs or request Copilot reviews/jobs.
Use an isolated integration checkout to preserve frozen candidates and user edits.
Fetch first, check ancestry/concurrent changes and run the relevant host gates.
Never force-push or change branch protection, credentials or approval settings.
If a normal push is rejected, retain the commits and report the actual rejection.

Repository integration is separate from deployment and physical acceptance.
BM83 and CrowPanel must remain offline during this maintenance. Do not enumerate,
probe, reset, deploy to or change playback on connected devices. Preserve private
captures/configuration and frozen source/compiler/artifact manifests. No CI or
simulator result proves the screens, metadata, radio lifecycle or stable audio.
Phase 2 BLE HID Disconnect remains blocked on actual Phase 1 acceptance; see
`docs/reliability/README.md` and `docs/reliability/DIRECT-MAINTENANCE.md`.

The two weekly AI workflows have been retired so this work cannot automatically
create new paid agent sessions or PRs. The Codacy security scan and host checks
remain. Existing secrets and security policy are unchanged.

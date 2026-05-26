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
- `recovered_src/` — historical reference, not built or deployed.

When `firmware/` changes, run `build_mpy.sh` to refresh `dist/`. Do not
hand-edit `dist/` — it will be overwritten on the next build.

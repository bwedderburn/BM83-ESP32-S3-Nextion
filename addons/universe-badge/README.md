# GitHub Universe badge add-on

[BM83 Remote](apps/bm83_remote/README.md) is an optional client for the GitHub
Universe badge, imported from the user's BADGER app folder on October 28, 2026.
It uses the badge's MicroPython runtime and firmware-provided graphics/buttons.
It does not run on the BM83 audio unit's CircuitPython firmware.

This directory is the canonical home for the badge client. The
[Universe workshop repository](https://github.com/bwedderburn/github-universe-2026)
keeps a matching copy at `badge/apps/bm83_remote/` so the remote and World Capitals
can be reviewed together. Apply client fixes here first, then mirror the seven
app files and all three host test files (`test_badge_bm83_remote.py`,
`test_badge_bm83_artwork.py`, and `test_badge_bm83_ui.py`) into that repository. Its
`scripts/check-bm83-addon.py --bm83-repo /path/to/this/repository` checks equality.

## Compatibility

The app speaks BMW1 authenticated UDP to a configured IPv4 address, normally
on port 8767. This repository's `main` snapshot at `d2e773d` has no matching
BMW1 receiver. Its existing ESP-NOW receiver and artwork Wi-Fi support are not
substitutes. The client is included as source for further integration; no
live badge-to-unit control or receiver interoperability has been verified.
The included tests use fake sockets and sample data only.

A receiver implementation, configured credentials, and separately authorized
physical-device checks are prerequisites for a working live remote. This add-on
does not change the receiver, the audio firmware, generated artifacts, or
existing deployment scripts.

## Files and manual installation

`apps/bm83_remote/` contains the entrypoint, portable helpers, icon and app README.
For manual installation after device authorization, copy that folder to
`apps/bm83_remote/` in the badge's BADGER mass-storage view (internally
`/system/apps/bm83_remote/`). The supplied badge menu discovers app folders;
no replacement launcher or bundled system assets are needed.

Configure the existing badge `secrets.py` locally as described in the app README.
Never copy credentials, saved state or artwork into Git. The import includes
only app code and its menu icon; the original BADGER copy remains unchanged.

## Host checks

```bash
python3 -m unittest discover -s tests -p 'test_badge_bm83*.py'
```

No additional packages or physical devices are required. The badge entrypoint
is intentionally not imported on the host. These checks cover helper behavior,
not rendering, badge networking, or live hardware acceptance.

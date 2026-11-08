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
on port 8767. The matching opt-in receiver is included at
[`firmware/circuitpython/lib/remote/badge_remote.py`](../../firmware/circuitpython/lib/remote/badge_remote.py).
It is inert without a separate private profile; ESP-NOW and artwork Wi-Fi alone
are not substitutes. See the [receiver setup and runtime safeguards](../../docs/guides/deployment.md#optional-universe-badge-receiver).

Host tests use fake sockets and sample data. Dated component and physical
observations are recorded in the [validation notes](../../docs/validation/bm83-startup-artwork-validation-2026-11-01.md),
and the separately authorized
[November 4 B-Intel Phase 1 run](../../docs/reliability/phase1-bintel-2026-11-04.md)
passed its agreed scope with the badge in the tested path; other hosts, power
orders and native-failure cases remain subject to the
[reliability acceptance gates](../../docs/reliability/README.md). Configured private
credentials, a reviewed runtime and separately authorized physical checks remain
prerequisites for live use. Including this add-on does not install or activate it.

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

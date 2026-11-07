# Release preparation

The active proposed release is **v1.0.0-rc.1**, with Python package metadata
`1.0.0rc1`. Its [release notes](../../RELEASE_NOTES-v1.0.0-rc.1.md) and
[preparation record](RC-PREPARATION.md) describe the selected controller/badge
source assets, reproducible packaging and remaining acceptance gates.
Preparing or pushing the candidate does not create a GitHub Release or publish
the proposed tag.

The published [v0.1.0 source-preview prerelease](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/releases/tag/v0.1.0)
identifies the earlier revision `0f7dd18167c8634e26bcf7a7a0a7c946fbb6a49a`.
Its [original draft notes](v0.1.0.md) remain a historical record rather than the
active version plan. That prerelease does not establish physical acceptance of
this later controller/badge integration.

## Selected assets

| Asset/profile | Purpose | Boundary |
| --- | --- | --- |
| `controller-badge-source` RC ZIP | Explicit controller/badge source, public assets/notices, Windows companion/launch receiver, license and selected release/deployment/validation files | Application source; native runtime, CrowPanel and Adafruit libraries are separate |
| Optional RC `.mpy` ZIP | Exact-revision controller entrypoints and pinned-compiler project libraries | Application artifacts; not a native flash image or installer |
| `application-source` preview ZIP | Preserve the earlier controller-only packaging profile | Explicitly request this profile for the historical preview scope |
| `MANIFEST.json` and `SHA256SUMS.txt` | Record source/member provenance and downloaded bytes | Integrity/provenance; no signature or hardware qualification |

Project-authored code uses the [MIT license](../../LICENSE). Public assets retain
their notices. Full repository archives also retain vendor reference material
under upstream terms; the project license does not relicense those files. The
selected application packages exclude vendor references and third-party libraries.

Source ZIPs read the exact reviewed Git commit using explicit allowlists. They
exclude local settings, enrollment profiles, Wi-Fi credentials, pairing data,
captures, backups, private keys and native flash images. Keep the settings example
inactive and preserve each installation's private configuration. A named archive
directory prevents opening a ZIP from writing directly over device files; the
archives are review assets and must not be copied wholesale to a device.

## Generate the RC source assets

Use `scripts/package_source_release.py`, the canonical implementation for both
profiles. `scripts/prepare_release.py` is a compatibility entrypoint to the same
code; `--ref` is an alias for `--revision`. Specify the full reviewed commit and
a new host output directory. Existing output paths and output symlinks are refused.

```powershell
python scripts/package_source_release.py --revision <reviewed-commit-sha> --version v1.0.0-rc.1 --scope controller-badge-source --output C:\Users\brian\Downloads\BM83-v1.0.0-rc.1-source-assets
```

```sh
python3 scripts/package_source_release.py --revision <reviewed-commit-sha> --version v1.0.0-rc.1 --scope controller-badge-source --output /absolute/new/BM83-v1.0.0-rc.1-source-assets
```

The command reads committed Git objects with replacement objects disabled and
rejects selected symlinks/submodules or missing inputs. It produces
`bm83-controller-badge-v1.0.0-rc.1-source.zip`, `MANIFEST.json` and `SHA256SUMS.txt`.
Sorted stored ZIP members, fixed timestamps/modes and canonical committed bytes
make repeat packaging independent of checkout line endings and compression-library
versions. Generate a second output directory and compare hashes before publishing.

For the optional compiled controller ZIP, follow
[RC preparation](RC-PREPARATION.md#optional-compiled-controller-assets). It requires
a build at the exact reviewed revision and an explicitly verified pinned compiler;
source-only review does not need a compiler. These commands perform no upload,
tag creation, device discovery, deployment or native flash operation.

## Publication and acceptance gates

Record the exact source commit, inspected asset digests and host/security results
at that commit before publication. Independently identify the supported physical
configuration. The [reliability matrix](../reliability/README.md),
[B-Intel Phase 1 acceptance](../reliability/phase1-bintel-2026-11-04.md) and
[Phase 2 host-selection record](../reliability/phase2-host-selection.md) retain
their distinct scopes. The Windows Phase 1 result and exercised Phase 2 controls
do not accept all platforms, enrollment/power-order cases or a new Phase 2 timing
window. Both macOS helper paths remain **Not accepted** in the current matrix.

Native CircuitPython and CrowPanel images require their own exact source,
toolchain, layout, installed-configuration and hardware verdicts. The recorded
two native dependency builds establish historical build equality, separate from
current physical acceptance. Private device data and frozen manifests stay
outside public assets.

Review the finished candidate before fast-forwarding `main`. Keep source
integration, tag/Release publication and hardware installation as separate
decisions; none follows automatically from generating these assets.

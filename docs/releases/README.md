# Release preparation

The project has not published a GitHub release. The first proposed release is
**v0.1.0**, a prerelease source preview. Its GitHub release stays a draft until
its scope, assets and acceptance evidence have been reviewed. Creating that draft
does not publish a tag or qualify the current hardware integration for production.

[Draft v0.1.0 release notes](v0.1.0.md) describe the proposed contents and limits.
The existing `setup.py` value `1.0.0` is Python package metadata; it is not evidence
of an earlier published firmware release or its physical acceptance.

## Proposed assets

| Asset | Purpose | Boundary |
| --- | --- | --- |
| CircuitPython application-source ZIP | The tracked controller `boot.py`, `main.py`, project libraries and inactive settings example, with license and provenance | Application files only; requires the documented board/runtime and separately installed Adafruit libraries |
| SHA-256 checksums and per-file manifest | Check downloaded bytes and identify the source revision | Integrity/provenance, not a signature or hardware qualification |
| GitHub source archives when published | Review the complete tagged source, tooling and documentation | Contains optional/experimental components; not a deployable device image |

Project-authored code uses the [MIT license](../../LICENSE). Full repository
archives also retain vendor reference material under its upstream terms; the
project license does not relicense those files. The application-source ZIP excludes
that material and third-party dependencies.

The application ZIP must be generated from the exact reviewed Git commit, using
an explicit allowlist. It must not contain a local `settings.toml`, enrollment
profiles, Wi-Fi credentials, pairing data, captures, vendor installers, third-party
libraries or native flash images. Keep `settings.example.toml` inactive: operators
merge only the needed settings into their existing private file.

The ZIP should unpack under a named application directory so opening the archive
does not overwrite a device automatically. Instructions must link to the deployment
and rollback guide. The source asset includes optional receiver modules, but the
badge receiver remains inert without its separate private profile and requires
the reviewed native runtime; including source is not authorization to enable it.

## Generate the application-source assets

Run this from the repository root after the reviewed changes have been committed.
Substitute the full reviewed commit SHA for `<reviewed-commit-sha>`. The output
directory must be new; the command refuses to overwrite existing output files or
follow an existing output-directory symlink.

```powershell
# Windows PowerShell; use an installed host Python interpreter.
python scripts/package_source_release.py --revision <reviewed-commit-sha> --version v0.1.0 --output C:\Users\brian\Downloads\BM83-v0.1.0-source-assets
```

```sh
# Linux / WSL / macOS; choose a new host directory outside the repository.
python3 scripts/package_source_release.py --revision <reviewed-commit-sha> --version v0.1.0 --output /absolute/new/BM83-v0.1.0-source-assets
```

The command reads Git objects rather than working-tree files, requires every
reviewed application input and the license, and rejects committed symlinks or
submodule entries in the allowlist. Local Git replacement objects are disabled.
The outputs are `BM83-Remote-v0.1.0-application-source.zip`, `MANIFEST.json` and
`SHA256SUMS.txt`. Sorted members, stored ZIP entries, fixed timestamps/permissions
and committed bytes make repeat packaging independent of checkout line endings
and local compression-library versions. Inspect the manifest and archive before
attaching them to the GitHub draft. This command performs no upload, tag creation,
device discovery or deployment.

## Publication gates

Before publishing, record the exact source commit and asset digests, inspect the
archive, and confirm the host/security gates at that commit. Independently decide
which physical configuration the release supports. The existing
[reliability acceptance protocol](../reliability/README.md) and open issues
[#190](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/issues/190),
[#193](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/issues/193),
[#194](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/issues/194) and
[#195](https://github.com/bwedderburn/BM83-ESP32-S3-Nextion/issues/195) remain the
source of the separate runtime and physical acceptance gates.

Native CircuitPython and CrowPanel images should be added only after their exact
source, toolchain, partition layout, installed configuration and hardware verdict
are established. Historical build equality does not establish current hardware
acceptance. Public assets must exclude device-specific backups and secrets.

A later release can add reviewed photographs, wiring diagrams, screen captures
and a supported-hardware matrix. These assets should describe the actual hardware
and current UI, with provenance and permission to redistribute each image.

# Documentation

Start with the [project overview](../README.md). Commands in the guides run from
the repository root unless they explicitly select another folder.

## Setup and use

| Guide | Covers |
| --- | --- |
| [Deployment and rollback](guides/deployment.md) | Baseline `.py` setup, generated `.mpy` deployment, backups and the installed-controller recovery exception |
| [Nextion setup](guides/nextion-setup.md) | Touch press/release tokens and display configuration |
| [Build project libraries](guides/building.md) | Pinned CircuitPython compiler and host-specific build commands |
| [Host testing](guides/testing.md) | Regression suites and optional compiler checks |
| [BLE host handoff](guides/ble-volume-handoff.md) | Pause/Enable, saved hosts and bond preservation |
| [BLE runtime update](guides/ble-runtime-update.md) | Reviewed capacity/runtime updates and guarded app-only writes |
| [Mac metadata bridge](guides/mac-metadata-bridge.md) | Optional LAN metadata, private pairing and one-time USB setup |
| [CrowPanel firmware](../firmware/crowpanel-remote/README.md) | Panel controls, ESP-NOW, Wi-Fi/artwork enrollment and build instructions |
| [Universe badge add-on](../addons/universe-badge/README.md) | Optional badge client, its receiver requirements and integration limits |

## Reliability and security

- [Reliability runbook](reliability/README.md): investigation work graph, current
  evidence and remaining physical acceptance gates.
- [Direct-maintenance handoff](reliability/DIRECT-MAINTENANCE.md): repository-only
  scope, preserved candidates and delivery procedure.
- [Native runtime flash guards](reliability/RUNTIME-FLASH-GUARDS.md).
- [Security scan status](security/SCAN-STATUS.md): supported analyses, old tool
  records and reviewed findings.
- [Security reporting policy](../SECURITY.md).
- [Agent setup](agents/SETUP.md): existing integration and paused AI workflows.

## Validation records

- [Hardware test limits and source comparisons](validation/hardware-test-limitations.md).
- [CrowPanel Now Playing validation](validation/crowpanel-now-playing-validation.md).
- [Startup recovery and badge artwork](validation/bm83-startup-artwork-validation-2026-11-01.md).
- [Pinned native runtime recipes and validation](../tools/circuitpython-runtime/README.md).

These are dated records. A passing component, host test or native build does not
establish current end-to-end hardware acceptance.

## Troubleshooting

- [Muted audio-path wedge](troubleshooting/muted-path-wedge.md).
- [Phantom AUX incident, 2026-08-26](troubleshooting/incident-2026-08-26-phantom-aux.md).
- [BLE handoff and competing saved hosts](guides/ble-volume-handoff.md).

## Reviews and reference

- [Review archive](reviews/README.md): dated findings and their original evidence.
- [Code reference](reference/code-reference.md): module map and interfaces.
- [Hardware reference](reference/hardware.md): controller, displays and both DAC boards.
- [BM83 vendor reference archive](reference/vendor/bm83/README.md): consolidated
  manuals, command table, vendor firmware and utilities, with byte hashes.
- [First-release preparation](releases/README.md) and [v0.1.0 draft](releases/v0.1.0.md).

The previous root guides moved to `docs/guides/` and `docs/reference/`. Former
flat `docs/code-review-*.md` files are in `docs/reviews/`; validation and incident
notes have their own folders. `Documents/` and its byte-identical root duplicates
were consolidated into the vendor archive. Historical review references describe
paths as they existed at the time.

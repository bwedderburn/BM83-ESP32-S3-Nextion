# BM83 vendor reference archive

This folder consolidates the vendor files already tracked in the repository.
The ten copies formerly at the repository root were verified byte-for-byte
identical to their `Documents/` counterparts before consolidation. One canonical
copy of each is retained here, without modifying its content. The empty
`Documents/Test` placeholder was removed.

[`manifest.json`](manifest.json) records each file's SHA-256, size and previous
paths. It is a preservation inventory, not an authenticity signature, malware
assessment or independent verification of the original download source.

| Folder | Material |
| --- | --- |
| [datasheets/](datasheets/) | BM83 application/design guides, UART command reference, spreadsheet and release notes |
| [firmware/](firmware/) | Retained BM83 demo and UI HEX packages; reference only |
| [tools/](tools/) | Retained vendor Windows utility; reference only |

These are third-party reference materials. The project's MIT license does not
relicense them; any vendor notices and applicable upstream terms continue to
apply. Their redistribution permissions have not been independently revalidated.
Do not include this archive in project firmware release bundles. Retaining the
packages does not authorize running the utility or flashing vendor firmware.

The archive does not establish the firmware revision installed on any physical
BM83. Follow a separately authorized, board-specific procedure for hardware work.

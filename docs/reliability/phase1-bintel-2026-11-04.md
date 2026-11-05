# Phase 1 acceptance — B-Intel, 2026-11-04

The owner accepted the agreed **B-Intel / Windows Apple Music** Phase 1 scope
after the measured workload, physical controls, original-controller restoration
and CrowPanel automatic recovery checks passed. The date is local to
America/Los_Angeles; the final measured window ended on November 5 UTC.

This closes that scoped prerequisite for Phase 2 Disconnect + Select host source
work. It does not accept every host, power order or native-runtime failure case.
Private captures, receiver profiles, credentials and raw diagnostic transcripts
remain outside the repository. This record contains sanitized results only.

## Accepted scope and provenance

The tested path used BM83 Bluetooth audio and separate saved BLE HID volume
control, with the ESP32-S3 controller, Nextion, CrowPanel and Universe badge.
The owner confirmed audible audio, all four clocks and metadata, CrowPanel
artwork and physical volume controls. Existing pairings were kept and host
Bluetooth remained on; the recovery procedure prohibited manual reconnect,
Power, Retry, Scan or Save.

Measurement instrumentation is checkpointed at `5641c769`. The CrowPanel passive
recovery fix is checkpointed at `61fd7c923c79d0727e04e9c2046766354a20a6b2`.
The tested CrowPanel application SHA256 is
`a4b46324df6270ed3ab68bf2040e0f9c3458c24a9cdb46fe0177c1973e4d0c28`.
The original controller application and all 127 original files were restored;
the fresh postboot audit found no differing paths and performed zero writes.
The native controller flash image was not freshly attested in this run.

## Required component gates

| Gate | Result and boundary |
| --- | --- |
| Recovered functional baseline | Owner confirmed audio, four clocks/metadata, artwork and brief volume controls before acquisition. |
| Qualified acquisition | 320.195 seconds host/capture and 320.218322748 seconds device between qualifying endpoints; fixed budgets frozen before the later arm. |
| Subsequent measured workload | 183 reports over more than 30 minutes on all three clocks; original numerical limits retained. |
| Postwindow physical controls | Owner reported all requested checks passed, including the badge; volume reached 14% then 16%, followed by at least three seconds paused with no sound. |
| Stopped-runtime restoration point | Fresh USER Safe Mode banner and a completed 80.114-second hold; capture transmitted zero bytes. |
| Exact original restoration | Five originals restored, two added diagnostic files removed, exact original 127-file set verified, one normal restart, and fresh postboot verification. |
| CrowPanel controller-absence case | Reader began before absence; repeated passive sweeps covered all 13 channels with continuing uptime and no observed reboot markers. |
| Fresh media and cached-artwork return | Cached artwork ready in 34.226057 seconds; fresh media snapshot and reported channel in 37.220559 seconds after the logged controller reset request, within the 90-second bound. |
| Saved Wi-Fi confirmation | Owner read the exact Wi-Fi status, “Connected to the saved network.” Exact association latency was not measured. |
| Final original-firmware check | Owner confirmed audio, all four clocks/metadata, CrowPanel artwork and volume 14% then 16%; playback remained running. |

All ten gates passed within this B-Intel scope. The saved evidence graph binds
29 component records; an independent file review reproduced the selection,
fixed-budget assessment and original-restoration chain.

## Measured window

The actual arm was `2026-11-05T02:34:39.629045Z`. The finite observer completed at
`03:05:10.460871Z`, after 1830.829792 armed seconds, using one persistent client,
one HELLO and zero control commands. The selected report endpoints were
`02:34:44.318Z` and `03:05:06.229Z`.

| Measurement | Result |
| --- | --- |
| Host UTC span | 1821.911 seconds |
| Capture elapsed span | 1821.912 seconds |
| Device elapsed span | 1821.967315681 seconds |
| Selected paired comparisons | 1822; 1807 agreeing, with all 15 transient discrepancies retained |
| Complete acknowledged armed interval | 1830 comparisons; 1815 agreeing |
| Longest whole consecutive nonagreement | 4.091777 seconds, including changes of discrepancy reason |
| Raw Windows source samples | All 1830 showed current Apple Music Playing, the same active unmuted BM83 route and unchanged 16% volume. |
| Confirmed matching nonempty-title epochs | Seven epochs, six title changes; empty transition snapshots were not counted as new tracks. |
| Required UART/parser/clock/observation event deltas | Zero |

The largest allowed report interval was 15 seconds; the observed maximum was
10.092 seconds on host/capture and 10.086944581 seconds on the device clock.
The clocks' span differences remain recorded; no invented oscillator-drift
threshold was used.

| UART budget | BM83 | Nextion |
| --- | ---: | ---: |
| Fixed G limit | 318.853590 ms | 321.172932 ms |
| Maximum cumulative observed G | 171.206582 ms | 171.664338 ms |
| Minimum dynamic receive-buffer residual | 5723 bytes | 469 bytes |

The limits were derived before arming from the source-defined receive capacities,
8N1 arrival rates, hidden-byte allowance, explicit reserve and measured work.
They were not increased after later timing or queue observations. Cumulative
maxima and histograms retain startup and the earlier paused/fault interval.

Observed ESP-NOW callback successes increased by 5440 from the acquisition
baseline to the final selected report, or 5186 from the first selected report
to the last. Failures increased by zero under both boundaries; the prior
cumulative failure count of 10257 remains retained. The acquisition baseline
predates the arm. Neither delta is exact counting at the instant of arm or proof
of per-frame delivery or zero radio loss.

## Automatic recovery and remaining limits

The CrowPanel's existing app continued during controller absence. Its closed
720.171-second passive capture contained 114 listening markers, increasing
uptime, no observed boot markers or uptime decrease, and no requested reset or
application-control transmission. The tested path exercised repeated idle
discovery rather than boot discovery. Absence of markers is not proof that no
conceivable reset occurred.

The less-than-38-second return evidence covers fresh radio/media state and
**cached** artwork. A reported channel can come from either the connected Wi-Fi
getter or retained channel state; a same-channel update can be silent. The later
owner check directly confirmed saved Wi-Fi connection. These observations do not
measure AP-association latency, a live artwork fetch, or network latency.

Native FIFO/ISR overflow counters, DMA/internal-only heap and socket counts were
unavailable, rather than assumed zero. Public native 8-bit heap observations do
not guarantee internal or DMA allocation. The existing first synchronous native
ESP-NOW send can still block under a resource failure; Python cannot preempt it.
This measured workload does not establish a universal worst-case bound or the
cause of the earlier native-radio failure.

The separate Windows BM83 audio power-cycle/reconnect wedge remains unresolved
by this BLE HID work. Pi and additional cross-platform, helper and power-order
cases remain separate. This result is neither global issue closure nor release
qualification for unattended operation.

Phase 2 may now implement Disconnect + Select host under the requirements to
preserve saved pairings and leave host Bluetooth on. Phase 2 must establish its
own source, native-build and physical host-switch evidence; it is not implemented
or accepted by this Phase 1 record.

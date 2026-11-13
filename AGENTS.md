# Project operating instructions

## Use the current task and actual evidence

Read the latest owner instructions and the relevant project evidence before
acting. A later owner instruction supersedes an older saved-state assumption or
maintenance restriction. Preserve unrelated work and frozen evidence. Do not
reset a checkout or mix a qualified snapshot with a newer branch.

Canonical controller source is `firmware/circuitpython/`; generated
`dist/circuitpython/` comes from `build_mpy.sh`. Qualified device payloads may
intentionally use compiled MPY files. Do not replace such a payload with a
generic deployment or delete its MPY files as supposedly stale imports.

## Troubleshoot saved state from a clean baseline

Brian's operating rule is to establish a known clean baseline early when
troubleshooting saved hosts, bindings, caches or similar state. Do not keep
repeating an inconclusive test through suspect retained state. Retain recovery
backups and evidence separately; retaining a backup does not require keeping
the suspect state active.

Within the owner's authorized cleanup scope, clear the suspect active state,
then connect and verify each host individually before adding the next. Do not
carry an obsolete preservation requirement forward after the owner changes the
scope. Raise a clean-baseline option early when retained state obstructs the
diagnosis. Record observed outcomes and distinguish them from hypotheses.

## Programming and testing are a separate decision

Use the established automatic process whenever available. Perform authorized
builds, backups, flashes, readbacks, normal restarts and host tests without
routine approval requests. Ask Brian only for a necessary physical action that
cannot be performed with the available automation.

For the BM83 controller, prefer the demonstrated button-free CDC 1200-baud to
native USB/OTG workflow when its target and mode match. CrowPanel uses its
established automatic DTR/RTS route. A clean saved-host baseline does not mean
introducing manual BOOT/RESET/release or cable changes, or reflashing
unnecessarily. Report the actual failed stage and retained state promptly; a
serial timeout alone does not prove a cable fault. A failed guard stops that
operation; use its evidence before choosing a new action.

Code-only maintenance does not itself authorize device access. Apply the
current task's authorization: the November 12 iPhone-enrollment task has
standing approval for necessary controller/CrowPanel programming, diagnostics,
cleanup and testing. Its later clean-baseline directive supersedes retention of
the three old active bonds. Keep recovery artifacts and private data outside
Git. Keep issue #194 on hold and the badge off unless the owner changes scope.

## AI collaboration and source attribution

Record the AI collaborators actually involved, their roles, relevant session
or handoff references, coordination method and evidence limits. Do not imply
that an AI participated when it did not.

In the current BM83 investigation, Codex owns local implementation, device
execution, evidence, integration and publication. Claude Code supplies
historical research, pinned-source analysis, scratch witness tests and review.
The local handoff identifies its active session and private artifact paths.
Keep Claude Code informed of material system changes, process changes and
verified field outcomes. Proactively seek its relevant engineering advice as a
peer collaborator, then check that advice against the actual referenced source
and evidence before applying it. An acknowledgment alone is not substantive
review; ask a concrete review question when its input can change the next step.
Check Claude Code's results through computer use about every five minutes
while it is working within the active task; Brian should not have to keep
attaching screenshots. Do not create a recurring automation for this one task.

Treat AI replies and screenshots as leads. Read the actual referenced files,
verify relevant versions and hashes, and retrieve or independently reproduce
critical witnesses. Attribute findings and distinguish scratch prototypes,
host models, installed bytes and physical acceptance. Correct prior claims
when primary files or live evidence contradict them. Public gate/evidence
records are in `docs/reliability/phase2-host-selection.md`; the native contract
is in `tools/circuitpython-runtime/HOST-POLICY-API.md`.

## Integration

Use an isolated checkout and stage exact paths. Run checks appropriate to the
change, then commit and push normally to `origin/main` under the current
authorization. No PR, Copilot request or force push for this task. Do not change
credentials, branch protections, account security, hooks or approval settings.
Host tests, compilation and readback do not substitute for the requested
device/host acceptance matrix.

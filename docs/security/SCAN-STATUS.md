# Security scan status and maintenance

This project uses two active GitHub code-scanning integrations:

- **CodeQL**, with Actions, Python, C/C++ and JavaScript/TypeScript analyses.
- **Codacy Security Scan**, explicitly selecting **Bandit** and uploading the
  `codacy-bandit` SARIF category.

The separate **Host security and reliability policy** workflow runs the pinned
Bandit production check, dependency audits and repository policy validation.
Code-scanning results are host analysis; they do not establish hardware
reliability or physical acceptance.

## November 3, 2026 review

Before this cleanup, all current CodeQL analyses and the current Codacy workflow
completed successfully. There were no open CodeQL alerts. The ten open Bandit
alerts were reviewed individually:

| Rule | Locations | Review and disposition |
| --- | --- | --- |
| B404 / B603 | Native build recorder and offline host-tool verifier | Intentional subprocess imports and execution of fixed build/provenance commands or explicitly allowlisted offline modules and verbs; argv lists, no shell. |
| B404 | Guarded CircuitPython runtime updater | Required subprocess import for the guarded esptool interface. Device operations remain behind the updater's existing explicit checks. No device operation was performed during this review. |
| B404 / B603 | Repository-health MCP server | Internal fixed Git/lint commands and restricted pytest arguments, without a shell. Running repository tests remains explicitly classified as executing repository code, not read-only access. |
| B110 | BLE helper and two retained BLE skill examples | A failed optional peer-address diagnostic is ignored while trying compatible attribute paths. Pairing and authentication processing is separate; this does not suppress an authentication failure. |

These reviewed lines now have specific Bandit rule annotations and the reason
at the call site. No broad new rule exclusions, alert dismissals or runtime
behavior changes were used. The security edits preserve the Python AST; the
repository-health server also receives a separate documentation-path update.
The CircuitPython distribution was regenerated with pinned `mpy-cross` 10.3.1.

Validation of the repaired working tree included Bandit 1.9.4 over the tracked
Python files with the existing `.bandit` exclusions: **zero findings and zero
analysis errors**. The focused BLE and host-tool tests passed (81 tests).
ShellCheck 0.9.0 reported no warning/error findings across the six shell scripts.
The native builder's external `export.sh` is supplied only in its build
environment, so ShellCheck cannot follow that source in the host checkout.

The Codacy workflow now also pins checkout to a full commit, disables persisted
checkout credentials, has a 15-minute timeout, and supports a manual run.
Existing scanner selection and SARIF upload permissions are retained.

## Retired May tool configurations

GitHub retained the following tool configurations after the Codacy workflow was
changed to Bandit-only scanning. Their latest main-branch analyses were May 25,
2026 in Pacific time, under the old category
`.github/workflows/codacy.yml:codacy-security-scan`:

| Retired tool | Historical result count |
| --- | ---: |
| Jacksonlinter (reported by Codacy) | 0 |
| Prospector (reported by Codacy) | 602 |
| Pylint (reported by Codacy) | 923 |
| Pylintpython3 (reported by Codacy) | 913 |
| Remark-lint (reported by Codacy) | 3 |
| Shellcheck (reported by Codacy) | 0 |

Their stored analysis records have empty execution-error and warning fields.
GitHub's detailed status was "Code Scanning results may be out of date."
The red tool-configuration status reflects the inactive setup, not a new failure
of the current workflow. The 2,441 retained results are historical lint/style
diagnostics and must not be represented as 2,441 newly discovered security
vulnerabilities or as source defects all repaired by this cleanup.

The six obsolete default-branch configurations were removed using GitHub's
configuration cleanup after exporting their latest raw SARIF and metadata plus
the complete set of 2,451 initially open alerts to the owner's local maintenance
evidence directory. This closed 2,441 historical results; they were not dismissed
as source fixes. Active CodeQL and `codacy-bandit` were retained. GitHub-side
retirement does not prevent future analysis; the checked-in workflow determines
which tools run on subsequent pushes. For future cleanup, archive the relevant
records before retiring an obsolete configuration.

## Reviewing later findings

Use the reported commit and file location, then distinguish a tool execution
failure from a source finding. Confirm any proposed repair with the affected
tests and a fresh scan. Use a specific per-line annotation only when the trust
boundary has been reviewed and documented; retain unrelated checks.

Bandit's documented [individual-line exclusions](https://bandit.readthedocs.io/en/latest/config.html#exclusions)
support selecting individual rule IDs so other rules on the same line remain
active. The project's [security policy](../../SECURITY.md) describes reporting
concerns privately.

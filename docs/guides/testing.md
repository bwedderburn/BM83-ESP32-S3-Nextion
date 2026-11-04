# Host tests and hardware validation

Host tests live under `tests/` and can be run with `pytest` on compatible platforms.

### Test categories

| Category | Scope | File(s) |
| --- | --- | --- |
| Core unit tests | Core host-simulatable logic and regressions | `tests/test_*.py` (excluding specialized suites below) |
| Parser stress tests | Noisy/fragmented parser burst behavior | `tests/test_parser_stress.py` |
| Host artifact parity | Verifies generated host artifacts match expected outputs | `tests/test_host_artifact_parity.py` |
| Optional `.mpy` build checks | Verifies `.mpy` build flow when explicitly enabled | `tests/test_mpy_build.py` with `RUN_MPY_TESTS=1` |

### Example commands

```bash
# Normal CI-like host run
pytest -q

# Optional .mpy verification run (requires mpy-cross)
RUN_MPY_TESTS=1 pytest -q tests/test_mpy_build.py

# Full run including optional .mpy checks
RUN_MPY_TESTS=1 pytest -q
```

Hardware behavior is only partially covered by host tests; see [../validation/hardware-test-limitations.md](../validation/hardware-test-limitations.md) for details.


Install the pinned development tools with `python -m pip install -r requirements-reliability.txt`. Run all commands from the repository root. The full host suite targets Linux; some fixtures require POSIX permissions and native build tools. Windows can run the platform-compatible subset. The [reliability runbook](../reliability/README.md) records the remaining physical acceptance gates.

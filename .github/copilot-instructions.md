# GitHub Copilot Instructions for BM83-ESP32-S3-Nextion

## Project Overview
This repository contains CircuitPython firmware for an **ESP32-S3** board that host-controls a **Microchip BM83 Bluetooth audio module** over UART, integrates a **Nextion HMI display** over UART, and optionally provides **BLE HID ConsumerControl** for volume/mute.

The main entrypoint is:
- `firmware/circuitpython/code.py`

Supporting modules live under:
- `firmware/circuitpython/`

## Technology Stack
- **Language**: Python (CircuitPython style; runs on-device)
- **Platform**: CircuitPython 10.x
- **Hardware/Protocols**:
  - BM83 UART framing + parsing (binary protocol, checksum)
  - Nextion UART token parsing + command sending (`0xFF 0xFF 0xFF` terminator)
  - Optional BLE HID ConsumerControl (volume/mute)
  - Optional I²S DAC integration (e.g., UDA1334A), depending on firmware usage

## Code Structure (authoritative)
All modules below are located in `firmware/circuitpython/`:
- `code.py`: main runtime / event loop / orchestration
- `bm83.py`: BM83 UART framing, parsing, AVRCP helpers, EQ syncing
- `nextion.py`: Nextion protocol, token parsing, command queue, polling (`sendme`)
- `ble_hid.py`: optional BLE HID ConsumerControl helper
- `utils.py`: shared helpers like `sanitize_text()` and `fmt_ms()`

Tests:
- `tests/`: unit tests run in CI (host Python)

CI:
- `.github/workflows/python-package.yml`: runs **flake8** and **pytest**

## Core Commands (match CI)
### Install (local dev)
```bash
python -m pip install --upgrade pip
python -m pip install flake8 pytest
```

### Linting (CI-compatible)
```bash
# Fail on syntax errors / undefined names
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics

# Style-only pass (warnings)
flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics
```

### Testing
```bash
pytest
pytest -v
```

## Coding Standards
- Keep code compatible with CircuitPython constraints:
  - prefer simple control flow and low allocation in hot loops
  - avoid heavy imports or patterns that assume CPython-only modules
- **PEP 8**, max line length **127**
- Prefer small, testable functions (protocol parsing is a great unit-test target)
- Add docstrings for public helpers and for protocol parsing/encoding functions
- Use descriptive names; keep protocol constants centralized and documented

## Key Patterns & Conventions
### Global state
- If you must use global variables in `code.py` (common in CircuitPython), follow this rule:
  - **Only declare `global x` inside a function if that function assigns to `x`.**
  - Reading a global does **not** need a `global` statement.

### UART protocols
- **BM83**
  - treat framing/parsing as a strict binary protocol
  - validate lengths and checksums before acting on frames
  - keep parsing resilient: ignore/skip bad frames rather than crashing
- **Nextion**
  - commands are ASCII and must be terminated with `\xFF\xFF\xFF`
  - sanitize any user/device-provided text before sending to the display
  - parsing should be non-blocking and tolerant of partial tokens

### Runtime/event loop
- Maintain a **non-blocking** main loop:
  - do not add long sleeps or blocking reads
  - handle timeouts and partial UART reads gracefully
  - keep state machines explicit (especially play/pause timing and metadata updates)

## Common Operations (preferred entry points)
- Sending BM83 commands: use the canonical send helper in `bm83.py` (don’t duplicate framing logic)
- Updating Nextion UI: use the helper methods in `nextion.py` (don’t hand-roll terminators everywhere)
- Formatting/sanitizing UI text: use `utils.py` helpers (`sanitize_text()`, etc.)
- BLE HID volume/mute: use `ble_hid.py` helper rather than inlining HID reports

## Common Pitfalls to Avoid
1. Don’t declare `global` for read-only globals (flake8 will complain; also harms clarity).
2. Don’t accept BM83 frames without checksum/length validation.
3. Don’t block the event loop on UART reads; always handle timeouts/partial reads.
4. Don’t send unsanitized strings to Nextion (quotes/CRLF/length can break commands).
5. Don’t duplicate protocol constants/encoders across files—centralize in the relevant module.

## Dependency Verification & Enhancement Checks
- When adding or updating dependencies from supported ecosystems (pip/npm/etc.), run the `gh-advisory-database` tool with the exact name/version and address any findings before finalizing changes.
- If the dependency version is unknown, determine it first (e.g., from `pyproject.toml`/`setup.py`) before running the advisory check.
- While making code changes, look for small, safe enhancements (reuse existing helpers, add missing docstrings for public helpers, reduce duplicated protocol logic) without expanding scope or breaking CircuitPython constraints.

## Boundaries / Files to Treat as Read-Only (unless explicitly requested)
- `Documents/` (vendor datasheets, reference PDFs)
- `.github/workflows/` (CI config)
- `LICENSE`
- `SECURITY.md`

## Acceptance Criteria for Changes
- `flake8` passes (strict pass + style pass as in CI)
- `pytest` passes
- Changes preserve protocol correctness and non-blocking behavior
- If behavior changes, update `README.md` and/or inline docs where needed
- New protocol parsing/encoding behavior should include unit tests where feasible

## Examples

### Good: reading a global (no `global` declaration)
```python
def is_powered_on() -> bool:
    """Return the last-known BM83 power state."""
    return _power_on
```

### Good: assigning a global (requires `global`)
```python
def set_power_state(on: bool) -> None:
    """Update the cached BM83 power state."""
    global _power_on
    _power_on = on
```

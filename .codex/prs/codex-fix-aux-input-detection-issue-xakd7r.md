# PR metadata

Requested source branch: codex/fix-aux-input-detection-issue-xakd7r
Requested target branch: main
Requested commits: d14f02a, d104edf

Validation results (user provided):
- python3 -m py_compile ... passed
- pytest -q passed (81 passed, 1 skipped)
- RUN_MPY_TESTS=1 pytest -q tests/test_mpy_build.py passed (2 passed)
- build_mpy.sh passed with canonical MPY_CROSS=/home/brian/tools/circuitpython/mpy-cross/build/mpy-cross

Note: dist/circuitpython artifacts are generated output and excluded from source review.

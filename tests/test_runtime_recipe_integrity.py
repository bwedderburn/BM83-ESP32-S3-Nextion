"""Check the actual native-build recipe without building or accessing a device."""

import hashlib
import json
from pathlib import Path

import pytest


RECIPE = Path(__file__).resolve().parents[1] / "tools/circuitpython-runtime"


@pytest.mark.parametrize("filename,pin_key", [
    ("espidf.constraints.v6.0.txt", "constraints_sha256"),
    ("requirements-build.txt", "requirements_sha256"),
], ids=["constraints", "requirements"])
def test_active_native_recipe_dependency_hashes(filename, pin_key):
    """Dependency edits must update active provenance for the exact build bytes."""
    pins = json.loads((RECIPE / "source-pins.json").read_text(encoding="utf-8"))
    data = (RECIPE / filename).read_bytes()

    # Docker copies these bytes, and record-build.py hashes them without newline
    # normalization. Git attributes must therefore preserve LF on Windows too.
    assert b"\r" not in data, f"{filename} must retain LF line endings for native-build provenance"
    actual = hashlib.sha256(data).hexdigest()
    assert pins["security_build"][pin_key] == actual, (
        f"{filename} changed without updating security_build.{pin_key}; "
        f"expected active SHA256 {actual}. Preserve historical reference_tools pins."
    )

"""Structural sanity checks for firmware/circuitpython/main.py recovery artifacts."""
from __future__ import annotations

from pathlib import Path
import ast


MAIN_PATH = Path(__file__).parent.parent / "firmware" / "circuitpython" / "main.py"


def test_main_has_single_entrypoint_definition():
    """Recovered main should not contain concatenated duplicate module bodies."""
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))

    main_defs = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    ]
    assert len(main_defs) == 1


def test_main_has_single_main_guard():
    """Ensure we did not accidentally append a second __main__ block."""
    source = MAIN_PATH.read_text(encoding="utf-8")
    assert source.count('if __name__ == "__main__":') == 1

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
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))

    def is_main_guard(node: ast.AST) -> bool:
        """Return True when node is a top-level if checking __name__ == '__main__'."""
        if not isinstance(node, ast.If):
            return False

        test = node.test
        if not isinstance(test, ast.Compare):
            return False
        if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
            return False
        if len(test.comparators) != 1:
            return False

        left = test.left
        right = test.comparators[0]
        return (
            isinstance(left, ast.Name)
            and left.id == "__name__"
            and isinstance(right, ast.Constant)
            and right.value == "__main__"
        ) or (
            isinstance(right, ast.Name)
            and right.id == "__name__"
            and isinstance(left, ast.Constant)
            and left.value == "__main__"
        )

    main_guards = [node for node in tree.body if is_main_guard(node)]
    assert len(main_guards) == 1

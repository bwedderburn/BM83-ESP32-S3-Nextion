"""Dispatch EBIND through the real loop without opening an adapter or UART."""
import ast
import copy
from pathlib import Path
from unittest import mock

import pytest

from blehid.ble import BleHid

MAIN = Path(__file__).resolve().parents[1] / "firmware/circuitpython/main.py"
TREE = ast.parse(MAIN.read_text())
DISPATCH = next(node for node in ast.walk(TREE)
                if isinstance(node, ast.For) and isinstance(node.target, ast.Name)
                and node.target.id == "tok")
CODE = compile(ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(DISPATCH)], type_ignores=[])),
               str(MAIN), "exec")


@pytest.mark.parametrize("connected", [False, True])
def test_ebind_claimed_owner_reports_forget_before_checking_connection(connected):
    ble = mock.Mock()
    ble.host_policy_claimed.return_value = True
    ble.is_connected.return_value = connected
    scope = dict(tokens=[b"BT_EBIND"], now=10.0, last_ebind_at=0.0,
                 ebind_min_interval_s=1.0, ble=ble, EQ_MAP={}, dprint=lambda *_args: None)
    exec(CODE, scope)  # nosec B102 - fixed repository AST dispatch, inert test doubles
    assert ble.mock_calls == [mock.call.host_policy_claimed(), mock.call.request_erase_bonds()]


@pytest.mark.parametrize("connected", [False, True])
def test_ebind_legacy_connection_guard_and_erase_flow_are_preserved(connected, capsys):
    ble = mock.Mock()
    ble.host_policy_claimed.return_value = False
    ble.is_connected.return_value = connected
    scope = dict(tokens=[b"BT_EBIND"], now=10.0, last_ebind_at=0.0,
                 ebind_min_interval_s=1.0, ble=ble, EQ_MAP={}, dprint=lambda *_args: None)
    exec(CODE, scope)  # nosec B102 - fixed repository AST dispatch, inert test doubles
    expected = [mock.call.host_policy_claimed(), mock.call.is_connected()]
    if not connected:
        expected.append(mock.call.request_erase_bonds())
    assert ble.mock_calls == expected
    assert ("EBIND denied" in capsys.readouterr().out) is connected


def test_claimed_erase_guidance_performs_no_native_erase(capsys):
    ble = BleHid(True, "unchanged")
    ble._host_policy = object()
    ble._ble = mock.Mock()
    ble.request_erase_bonds()
    assert "CrowPanel Volume hosts > Disconnect > select host > Forget" in capsys.readouterr().out
    assert ble._ble.mock_calls == []

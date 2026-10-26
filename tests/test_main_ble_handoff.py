"""Remote handoff dispatch never operates BM83 audio/power/source controls."""
import ast
from unittest import mock

import pytest

from remote.ble_status import BleStatusPublisher
from tests.test_main_mute import CODE, MAIN, TREE
from tests.test_remote_ble_status import Backend, Clock, Sink
from tests.test_remote_espnow import OTHER_MAC_B, REMOTE_MAC_B, frame, make_remote


@pytest.mark.parametrize("token", [b"BLE_PAUSE", b"BLE_ENABLE"])
@pytest.mark.parametrize("aux", [False, True])
def test_handoff_is_remote_only_intent_and_cancels_old_host_volume_hold(token, aux):
    remote, _radio, clock, _logs = make_remote()
    assert remote.accept(OTHER_MAC_B, frame(1, token), clock()) is None
    assert remote.accept(REMOTE_MAC_B, frame(2, token), clock()) == token
    backend, bm, sink = Backend(), mock.Mock(), Sink()
    publisher = BleStatusPublisher(sink, backend, clock=Clock(), session=1)
    scope = dict(tokens=[token], remote=remote, ble_status=publisher, bm=bm,
                 ble=mock.Mock(), aux_mode=aux, vol_hold_active="up", vol_repeat_count=5,
                 dprint=lambda *_args: None)
    exec(CODE, scope)  # nosec B102 - local repository AST, never external input
    assert backend.requests == ["pause" if token == b"BLE_PAUSE" else "enable"]
    assert scope["vol_hold_active"] is None
    assert scope["vol_repeat_count"] == 0
    assert bm.mock_calls == []
    assert sink.frames == []
    # A fabricated Nextion token has no paired BMR1 context and cannot run it.
    exec(CODE, scope)  # nosec B102 - same fixed repository AST
    assert len(backend.requests) == 1


def test_ble_native_tick_is_after_uart_events_and_controls_before_publish():
    function = next(item for item in TREE.body if isinstance(item, ast.FunctionDef) and item.name == "main")
    loop = next(item for item in function.body if isinstance(item, ast.While))
    calls = [(node.lineno, node.func.id) for node in ast.walk(loop)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    ble_lines = [line for line, name in calls if name == "ble_tick"]
    bm_line = next(line for line, name in calls if name == "bm_poll")
    dispatch = next(node for node in ast.walk(loop) if isinstance(node, ast.For)
                    and isinstance(node.target, ast.Name) and node.target.id == "tok")
    publish = next(node.lineno for node in ast.walk(loop) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Attribute) and node.func.attr == "tick"
                   and isinstance(node.func.value, ast.Name) and node.func.value.id == "remote_state")
    assert len(ble_lines) == 1
    assert bm_line < dispatch.lineno < dispatch.end_lineno < ble_lines[0] < publish
    assert MAIN.exists()

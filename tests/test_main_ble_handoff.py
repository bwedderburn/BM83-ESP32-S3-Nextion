"""Remote handoff dispatch never operates BM83 audio/power/source controls."""
import ast
from unittest import mock

import pytest

from remote.badge_remote import BadgeRemote
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
    badge = BadgeRemote(profile_path="/nonexistent/.badge_remote.json", log=lambda _m: None)
    assert not badge.setup()
    scope = dict(tokens=[token], remote=remote, badge_remote=badge, ble_status=publisher, bm=bm,
                 ble=mock.Mock(), badge_hosts=mock.Mock(), aux_mode=aux, vol_hold_active="up", vol_repeat_count=5,
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


class _Badge:
    """Records the dispatch contract without opening a socket."""

    def __init__(self, pending):
        self.pending = dict(pending)
        self.noted = []

    def take_ble_request(self, token):
        return self.pending.pop(token, None)

    def note_ble_request(self, origin):
        self.noted.append(origin)


@pytest.mark.parametrize("token", [b"BLE_PAUSE", b"BLE_ENABLE"])
def test_badge_ble_request_echoes_zero_and_records_its_origin(token):
    remote, _radio, clock, _logs = make_remote()
    backend, bm, sink = Backend(), mock.Mock(), Sink()
    publisher = BleStatusPublisher(sink, backend, clock=Clock(), session=1)
    badge = _Badge({token: (7, 3)})
    scope = dict(tokens=[token], remote=remote, badge_remote=badge, ble_status=publisher, bm=bm,
                 ble=mock.Mock(), badge_hosts=mock.Mock(), aux_mode=False, vol_hold_active="down", vol_repeat_count=2,
                 dprint=lambda *_args: None)
    exec(CODE, scope)  # nosec B102 - local repository AST, never external input
    assert backend.requests == ["pause" if token == b"BLE_PAUSE" else "enable"]
    # CrowPanel requests start at 1; echo 0 can never confirm a waiting panel.
    assert publisher._request_sequence == 0
    assert badge.noted == [(7, 3)]
    assert scope["vol_hold_active"] is None
    assert bm.mock_calls == []
    exec(CODE, scope)  # nosec B102 - the badge request was consumed once
    assert len(backend.requests) == 1


def test_crowpanel_ble_request_supersedes_badge_origin():
    remote, _radio, clock, _logs = make_remote()
    backend, sink = Backend(), Sink()
    publisher = BleStatusPublisher(sink, backend, clock=Clock(), session=1)
    badge = _Badge({b"BLE_PAUSE": (7, 3)})
    scope = dict(tokens=[b"BLE_PAUSE"], remote=remote, badge_remote=badge, ble_status=publisher,
                 bm=mock.Mock(), ble=mock.Mock(), badge_hosts=mock.Mock(), aux_mode=False, vol_hold_active=None,
                 vol_repeat_count=0, dprint=lambda *_args: None)
    exec(CODE, scope)  # nosec B102 - local repository AST, never external input
    assert remote.accept(REMOTE_MAC_B, frame(9, b"BLE_ENABLE"), clock()) == b"BLE_ENABLE"
    scope["tokens"] = [b"BLE_ENABLE"]
    exec(CODE, scope)  # nosec B102 - same fixed repository AST
    assert backend.requests == ["pause", "enable"]
    assert publisher._request_sequence == 9
    # The badge then reports "superseded" instead of a false confirmation.
    assert badge.noted == [(7, 3), None]
    assert scope["badge_hosts"].supersede.call_count == 2


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

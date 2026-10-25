"""Exercise CrowPanel mute through the paired receiver and real dispatch."""
import ast
import copy
from pathlib import Path
from unittest import mock

import pytest

from nextion.display import Nextion
from tests.test_nextion import DummyUART
from tests.test_remote_espnow import FakePacket, OTHER_MAC_B, REMOTE_MAC_B, frame, make_remote


MAIN = Path(__file__).resolve().parents[1] / "firmware/circuitpython/main.py"
TREE = ast.parse(MAIN.read_text())
DISPATCH = next(node for node in ast.walk(TREE)
                if isinstance(node, ast.For) and isinstance(node.target, ast.Name)
                and node.target.id == "tok")
CODE = compile(ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(DISPATCH)], type_ignores=[])),
               str(MAIN), "exec")


def dispatch(tokens, aux=False):
    ble = mock.Mock()
    bm = mock.Mock()
    exec(CODE, {"tokens": tokens, "aux_mode": aux, "ble": ble, "bm": bm,
                "dprint": lambda *_args: None})  # nosec B102 - repository AST, never external input
    assert bm.mock_calls == []
    return ble


def test_paired_crowpanel_mute_dispatches_once_despite_radio_retry():
    remote, radio, _clock, _logs = make_remote()
    radio.queue.extend([FakePacket(OTHER_MAC_B, frame(10, b"BT_MUTE")),
                        FakePacket(REMOTE_MAC_B, frame(11, b"BT_MUTE")),
                        FakePacket(REMOTE_MAC_B, frame(11, b"BT_MUTE"))])
    tokens = remote.poll()
    assert tokens == [b"BT_MUTE"]
    ble = dispatch(tokens)
    assert ble.mock_calls == [mock.call.mute()]


def test_mute_does_not_change_phone_volume_during_aux(capsys):
    ble = dispatch([b"BT_MUTE"], aux=True)
    assert ble.mock_calls == []
    assert "Ignoring BT_MUTE while AUX IN is active" in capsys.readouterr().out


@pytest.mark.parametrize("pieces", [(b"BT_MUTE\xff\xff\xff",),
                                    (b"BT_MU", b"TE\xff\xff\xff")])
def test_mute_token_is_ready_for_future_nextion_hmi(pieces):
    uart = DummyUART()
    panel = Nextion(uart)
    received = []
    for piece in pieces:
        uart.to_read.extend(piece)
        uart.in_waiting = len(uart.to_read)
        tokens, _page = panel.read()
        received.extend(tokens)
    assert received == [b"BT_MUTE"]
    assert dispatch(received).mock_calls == [mock.call.mute()]

"""Run main.py's real AVRCP response branch without UART or radio hardware."""
import ast
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from bm83.bm83 import Bm83
from remote.state_tx import StatePublisher
from utils.common import TIME_UNKNOWN, _fmt_ms, _normalize_track_time_ms

MAIN_PATH = Path(__file__).resolve().parents[1] / "firmware/circuitpython/main.py"


def handler_code():
    """Extract only the actual vendor-response branch, preserving continues."""
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    branch = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                  and any(isinstance(value, ast.Attribute) and value.attr == "EVT_AVC_VENDOR_RSP"
                          for value in node.test.comparators))
    loop = ast.For(target=ast.Name(id="_once", ctx=ast.Store()), iter=ast.Tuple(elts=[ast.Constant(0)], ctx=ast.Load()),
                   body=copy.deepcopy(branch.body), orelse=[])
    return compile(ast.fix_missing_locations(ast.Module(body=[loop], type_ignores=[])), str(MAIN_PATH), "exec")


HANDLER_CODE = handler_code()


def response(pdu, avp, code=0x0F, packet_type=0):
    """Build BM83 EVT_AVC_VENDOR_RSP params using the production parser layout."""
    return bytes((0, code, 0x48, 0, 0, 0x19, 0x58, pdu, packet_type)) + len(avp).to_bytes(2, "big") + avp


class Handler:
    def __init__(self, play_status=1):
        self.bm = mock.Mock(spec=Bm83)
        self.bm.parse_avc_vendor_rsp.side_effect = Bm83.parse_avc_vendor_rsp
        self.remote = StatePublisher(object(), clock=lambda: 1000, session=42)
        self.remote.set_transport(True, True, False)
        self.remote.note_attributes({1: "Current title", 2: "Current artist", 3: "Current album"})
        self.remote.note_status(play_status)
        self.remote.note_position(12000, 180000)
        self.invalidations = 0
        self.pushes = []
        self.meta = {"title": "Current title", "artist": "Current artist", "time_cur": "0:12", "time": "3:00"}
        self.env = dict(bm=self.bm, remote_state=self.remote, time=SimpleNamespace(monotonic=lambda: 123.0),
                        last_play_status=play_status, last_pos_ms=12000, last_total_ms=180000,
                        last_avrcp_rx_at=0, PLAYING_STATES=(1, 3, 4), desired_meta=self.meta,
                        TIME_UNKNOWN=TIME_UNKNOWN, _normalize_track_time_ms=_normalize_track_time_ms,
                        _fmt_ms=_fmt_ms, maybe_track_changed=lambda _pos, _total: False,
                        primary_metadata_missing=lambda: self.meta["title"] == "—",
                        meta_set=self.meta_set, invalidate_track_meta=self.invalidate,
                        push_meta_updates=lambda changed: self.pushes.append(list(changed)),
                        dprint=lambda *_args: None)

    def meta_set(self, key, value, changed):
        if value is not None and self.meta.get(key) != value:
            self.meta[key] = value
            changed.append(key)

    def invalidate(self):
        self.invalidations += 1
        self.remote.clear_track()
        self.meta["time_cur"] = self.meta["time"] = TIME_UNKNOWN
        return ["time_cur", "time"]

    def run(self, params):
        self.env["params"] = params
        exec(HANDLER_CODE, self.env)  # nosec B102 - repository AST branch, never external input


def test_track_interim_retains_metadata_and_outstanding_subscription():
    handler = Handler()
    handler.run(response(0x31, b"\x02" + b"\x00" * 8))
    assert handler.invalidations == 0
    assert handler.remote.snapshot()["title"] == "Current title"
    assert handler.remote.snapshot()["duration_ms"] == 180000
    assert handler.env["last_pos_ms"] == 12000
    handler.bm.avrcp_reregister_track_changed.assert_not_called()
    handler.bm.schedule_attrs.assert_not_called()


def test_track_changed_clears_old_fields_and_rearms_once():
    handler = Handler()
    handler.run(response(0x31, b"\x02" + b"\x00" * 8, code=0x0D))
    assert handler.invalidations == 1
    assert handler.remote.snapshot()["title"] == ""
    assert handler.remote.snapshot()["position_ms"] is None
    assert handler.env["last_pos_ms"] is None and handler.env["last_total_ms"] is None
    handler.bm.avrcp_reregister_track_changed.assert_called_once_with()
    handler.bm.schedule_attrs.assert_called_once_with(0.25)


@pytest.mark.parametrize("code,rearm", [(0x0F, False), (0x0D, True)])
def test_playback_notification_seeds_state_but_only_changed_rearms(code, rearm):
    handler = Handler(play_status=2)
    handler.run(response(0x31, b"\x01\x01", code=code))
    assert handler.env["last_play_status"] == 1
    assert handler.remote.snapshot()["play_status"] == 1
    assert handler.remote.snapshot()["title"] == "Current title"
    assert handler.invalidations == 0
    assert handler.bm.avrcp_reregister_status_changed.call_count == int(rearm)
    handler.bm.schedule_play_status.assert_called_once_with(0.05)


@pytest.mark.parametrize("code,rearm", [(0x0F, False), (0x0D, True)])
def test_position_notification_seeds_genuine_position_without_interim_rearm(code, rearm):
    handler = Handler()
    handler.run(response(0x31, b"\x05" + (40000).to_bytes(4, "big"), code=code))
    assert handler.remote.snapshot()["position_ms"] == 40000
    assert handler.remote.snapshot()["title"] == "Current title"
    assert handler.meta["time_cur"] == _fmt_ms(40000)
    assert handler.invalidations == 0
    assert handler.bm.avrcp_reregister_position_changed.call_count == int(rearm)


def test_paused_interim_position_seeds_crowpanel_without_advancing_nextion():
    handler = Handler(play_status=2)
    handler.run(response(0x31, b"\x05" + (45000).to_bytes(4, "big")))
    assert handler.remote.snapshot()["position_ms"] == 45000
    assert handler.remote.snapshot()["play_status"] == 2
    assert handler.meta["time_cur"] == "0:12"
    handler.bm.avrcp_reregister_position_changed.assert_not_called()


@pytest.mark.parametrize("code", [0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0E])
@pytest.mark.parametrize("avp", [b"\x01\x02", b"\x02" + b"\x00" * 8, b"\x05" + (90000).to_bytes(4, "big")])
def test_rejected_or_unrelated_notification_responses_leave_state_and_requests_untouched(code, avp):
    handler = Handler()
    before = handler.remote.snapshot()
    handler.run(response(0x31, avp, code=code))
    assert handler.remote.snapshot() == before
    assert handler.env["last_play_status"] == 1
    assert handler.invalidations == 0
    assert handler.bm.method_calls == [mock.call.parse_avc_vendor_rsp(handler.env["params"])]


@pytest.mark.parametrize("code", [0x08, 0x09, 0x0D, 0x0F])
def test_play_status_only_accepts_stable_response(code):
    handler = Handler()
    avp = (240000).to_bytes(4, "big") + (70000).to_bytes(4, "big") + b"\x02"
    handler.run(response(0x30, avp, code=code))
    assert handler.remote.snapshot()["position_ms"] == 12000
    assert handler.env["last_play_status"] == 1
    assert handler.bm.method_calls == [mock.call.parse_avc_vendor_rsp(handler.env["params"])]


def test_stable_play_status_updates_clock_and_state():
    handler = Handler()
    avp = (240000).to_bytes(4, "big") + (70000).to_bytes(4, "big") + b"\x02"
    handler.run(response(0x30, avp, code=0x0C))
    assert handler.remote.snapshot()["position_ms"] == 70000
    assert handler.remote.snapshot()["duration_ms"] == 240000
    assert handler.remote.snapshot()["play_status"] == 2
    assert handler.env["last_play_status"] == 2


@pytest.mark.parametrize("params", [
    b"", b"\x00", response(0x31, b"\x01"), response(0x31, b"\x05\x00"),
    response(0x31, b"\x01\x02")[:-1], response(0x31, b"\x01\x02", packet_type=1),
])
def test_truncated_or_fragmented_notifications_do_not_mutate_state(params):
    handler = Handler()
    before = handler.remote.snapshot()
    handler.run(params)
    assert handler.remote.snapshot() == before
    assert handler.invalidations == 0
    handler.bm.avrcp_reregister_status_changed.assert_not_called()
    handler.bm.avrcp_reregister_position_changed.assert_not_called()


def test_response_code_uses_low_nibble_after_validated_parse():
    handler = Handler()
    handler.run(response(0x31, b"\x01\x02", code=0xFD))
    assert handler.remote.snapshot()["play_status"] == 2
    handler.bm.avrcp_reregister_status_changed.assert_called_once_with()

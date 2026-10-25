"""Exercise metadata retry decisions through the production main loop."""

import importlib.util
from pathlib import Path
import sys
import time
import types

import pytest

from bm83.bm83 import Bm83
from nextion.display import NX_RUNTIME
from tests.test_bm83_uart import frame_to_bytes


class _ScriptFinished(BaseException):
    """End the otherwise infinite firmware loop after the final checkpoint."""


class _Clock:
    def __init__(self, script):
        self.script = script
        self.index = 0

    def monotonic(self):
        return self.script[self.index][0]

    def sleep(self, _seconds):
        if self.index + 1 == len(self.script):
            raise _ScriptFinished
        self.index += 1


class _ScriptedUART:
    """Supply framed replies once per checkpoint and timestamp real TX frames."""

    def __init__(self, clock):
        self.clock = clock
        self.pending = bytearray()
        self.fed_at = None
        self.writes = []

    @property
    def in_waiting(self):
        if self.fed_at != self.clock.index:
            self.fed_at = self.clock.index
            self.pending.extend(b"".join(self.clock.script[self.clock.index][1]))
        return len(self.pending)

    def read(self, count):
        chunk = bytes(self.pending[:count])
        del self.pending[:count]
        return chunk

    def write(self, frame):
        self.writes.append((self.clock.monotonic(), bytes(frame)))
        return len(frame)


class _Display:
    def __init__(self, _uart):
        self.current_page = 1
        self.text = {}

    def boot_sync(self, _timeout):
        pass

    def tick(self):
        pass

    def read(self):
        return [], False

    def set_text_active_page(self, name, value):
        self.text[name] = value


class _Ble:
    def __init__(self, *_args):
        pass

    def setup(self):
        pass

    def tick(self):
        pass

    def volume(self, _up):
        raise AssertionError("the metadata script contains no volume controls")


class _Remote:
    # This script exercises AVRCP retries; its radio double has no state TX.
    state_tx_enabled = False

    def __init__(self, **_kwargs):
        pass

    def setup(self):
        pass

    def poll(self):
        return ()


def _avc_reply(pdu, payload, response=0x0C):
    # DB + AV/C response header + PDU, single-packet type, payload length.
    params = (bytes((0, response, 0x48, 0, 0, 0x19, 0x58)) + bytes((pdu, 0))
              + len(payload).to_bytes(2, "big") + payload)
    return frame_to_bytes(Bm83.EVT_AVC_VENDOR_RSP, params)


def _play_status(position_ms):
    payload = (180000).to_bytes(4, "big") + position_ms.to_bytes(4, "big") + b"\x01"
    return _avc_reply(0x30, payload)


def _metadata(*attributes):
    body = b""
    for attribute, text in attributes:
        value = text.encode("utf-8")
        body += (attribute.to_bytes(4, "big") + b"\x00\x6A"
                 + len(value).to_bytes(2, "big") + value)
    params = bytes((0x20, 0, 1, 1, len(attributes))) + len(body).to_bytes(2, "big") + body
    return frame_to_bytes(Bm83.EVT_AVRCP_VENDOR_DEP_RSP, params)


def _run_main(monkeypatch, script, publisher_snapshots=None):
    clock = _Clock(script)
    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    monkeypatch.setattr(time, "sleep", clock.sleep)
    bm_uart = _ScriptedUART(clock)

    board = types.ModuleType("board")
    for pin in (15, 16, 17, 18):
        setattr(board, "IO%d" % pin, pin)
    busio = types.ModuleType("busio")
    busio.UART = lambda *_args, **_kwargs: bm_uart
    microcontroller = types.ModuleType("microcontroller")
    microcontroller.cpu = types.SimpleNamespace(reset_reason="host test")
    for name, module in (("board", board), ("busio", busio), ("microcontroller", microcontroller)):
        monkeypatch.setitem(sys.modules, name, module)

    # Load a separate module so this harness does not replace the cached main
    # module used by other tests. Its main() and nested event handlers are real.
    path = Path(__file__).resolve().parents[1] / "firmware" / "circuitpython" / "main.py"
    spec = importlib.util.spec_from_file_location("_metadata_retry_main", path)
    firmware = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(firmware)
    display = _Display(None)
    firmware.Nextion = lambda _uart: display
    firmware.BleHid = _Ble
    firmware.EspNowRemote = _Remote
    if publisher_snapshots is not None:
        class CapturingPublisher(firmware.StatePublisher):
            def tick(self):
                publisher_snapshots.append((clock.monotonic(), self.snapshot()))
                return super().tick()

        firmware.StatePublisher = CapturingPublisher

    def established_bm83(uart):
        bm = Bm83(uart)
        # Start in an established A2DP session: boot/reconnect scheduling must
        # not accidentally supply the requests this test expects from main.
        bm.connected = True
        bm.power_on = True
        bm.audio_source = bm.AUDIO_SRC_A2DP
        bm._source_ever_seen = True
        bm._boot_init_at = 0.0
        bm._last_connected_seen = clock.monotonic()
        return bm

    firmware.Bm83 = established_bm83
    with pytest.raises(_ScriptFinished):
        firmware.main()
    return bm_uart.writes, display.text


def test_main_retries_empty_metadata_stops_when_complete_and_rearms_on_track_change(monkeypatch):
    # Ordinary play-status replies trigger a 150 ms deferred retry, subject to
    # the existing 1.5 s throttle. Check both sides of each scheduled deadline.
    start = 100.0
    delay = 0.15
    throttle = 1.5
    first_due = start + delay
    second_status = first_due + throttle
    second_due = second_status + delay
    third_status = second_due + throttle
    third_due = third_status + delay
    track_changed_at = third_due + 4 * throttle
    track_due = track_changed_at + 0.25
    empty = _metadata()
    script = [
        (start, (empty, _play_status(1000))),
        (first_due - 0.001, ()),
        (first_due, ()),
        (first_due + 0.1, (empty, _play_status(1100))),
        (second_status - 0.001, (empty, _play_status(2000))),
        (second_status, (_play_status(2500),)),
        (second_due - 0.001, ()),
        (second_due, ()),
        (second_due + 0.1, (empty, _play_status(2700))),
        (third_status, (_play_status(4000),)),
        (third_due - 0.001, ()),
        (third_due, ()),
        (third_due + 0.05, (_metadata((1, "Song"), (2, "Artist")),)),
        (third_due + 0.5, (_play_status(4500),)),
        (third_due + throttle + 0.5, (_play_status(6000),)),
        (third_due + 2 * throttle + 0.5, (_play_status(7500),)),
        (third_due + 3 * throttle + 0.5, (_play_status(9000),)),
        # RegisterNotification CHANGED is0x0D; STABLE0x0C is not a track event.
        (track_changed_at, (_avc_reply(0x31, b"\x02" + (1).to_bytes(8, "big"), response=0x0D),)),
        (track_due - 0.001, ()),
        (track_due, ()),
    ]

    writes, text = _run_main(monkeypatch, script)
    metadata_requests = [
        stamp for stamp, frame in writes
        if frame[3] == Bm83.OP_AVRCP_VENDOR_DEP_CMD and frame[4:6] == b"\x00\x20"
    ]
    assert metadata_requests == pytest.approx([first_due, second_due, third_due, track_due])
    assert all(later - earlier >= throttle
               for earlier, later in zip(metadata_requests, metadata_requests[1:]))
    # Complete title AND artist updates travel through the actual parser and
    # main's cache/display path; subsequent status polls add no metadata TX.
    assert text[NX_RUNTIME["title"]] == "Song"
    assert text[NX_RUNTIME["artist"]] == "Artist"
    # Every empty/full GEA frame was consumed by production and ACKed, rather
    # than a discarded test input leaving the initial missing state unchanged.
    metadata_acks = [frame for _stamp, frame in writes
                     if frame[3:5] == bytes((Bm83.OP_EVENT_ACK, Bm83.EVT_AVRCP_VENDOR_DEP_RSP))]
    assert len(metadata_acks) == 5


@pytest.mark.parametrize("track_event", ["notification", "inferred"])
def test_rapid_track_change_eventually_refreshes_cleared_remote_metadata(monkeypatch, track_event):
    # A track can change immediately after the preceding metadata reply. The
    # Nextion intentionally retains its old title/artist while waiting, but the
    # remote clears all track fields; it needs a deferred refresh even though
    # Nextion's primary fields are nonempty. Never bypass the UART throttle.
    start = 100.0
    first_due = start + 0.15
    changed_at = first_due + 0.15
    second_due = first_due + 1.5
    event = (_avc_reply(0x31, b"\x02" + (2).to_bytes(8, "big"), response=0x0D)
             if track_event == "notification" else _play_status(500))
    script = [
        (start, (_metadata(), _play_status(1000))),
        (first_due, ()),
        (first_due + 0.05, (_metadata((1, "Old Song"), (2, "Old Artist"), (3, "Old Album")),
                            _play_status(10000))),
        (changed_at, (event,)),
        (changed_at + 0.10, (_play_status(600),)),
        (changed_at + 0.25, ()),
        (second_due - 0.001, (_play_status(1200),)),
        (second_due, ()),
        (second_due + 0.05, (_metadata((1, "New Song"), (2, "New Artist"), (3, "New Album")),
                             _play_status(1500))),
        (second_due + 2.0, (_play_status(3500),)),
    ]
    snapshots = []
    writes, text = _run_main(monkeypatch, script, snapshots)
    metadata_requests = [stamp for stamp, frame in writes
                         if frame[3] == Bm83.OP_AVRCP_VENDOR_DEP_CMD and frame[4:6] == b"\x00\x20"]
    assert metadata_requests == pytest.approx([first_due, second_due])
    assert metadata_requests[1] - metadata_requests[0] >= 1.5
    at_change = next(snapshot for stamp, snapshot in snapshots if stamp == changed_at)
    assert at_change["title"] == at_change["artist"] == at_change["album"] == ""
    final = snapshots[-1][1]
    assert (final["title"], final["artist"], final["album"]) == ("New Song", "New Artist", "New Album")
    assert text[NX_RUNTIME["title"]] == "New Song"
    assert text[NX_RUNTIME["artist"]] == "New Artist"


@pytest.mark.parametrize("gea_hex,title,nextion_title", [
    ("20000c0103003300000001006a00044b696e6400000002006a0016506c696e6920e280942053756e68656164202d204550"
     "00000004006a000130", "Kind", "Kind"),
    ("20000c0103004800000001006a0019466cc3a26e6575722028666561742e20416e6f6d616c69652900000002006a0016"
     "506c696e6920e280942053756e68656164202d20455000000004006a000130",
     "Flâneur (feat. Anomalie)", "Fl neur (feat. Anomalie)"),
])
def test_windows_captured_gea_restores_album_for_both_displays(monkeypatch, gea_hex, title, nextion_title):
    # Exact 0x5D parameter bytes from the Windows web-player capture: UTF-8
    # charset106, attributes1/2/4 only, and combined artist/album in attr2.
    params = bytes.fromhex(gea_hex)
    bm = Bm83(None)
    _response, raw = bm.parse_gea_0x5d(params)
    assert raw == {1: title, 2: "Plini — Sunhead - EP", 4: "0"}
    assert 3 not in raw

    snapshots = []
    script = [(100.0, (frame_to_bytes(Bm83.EVT_AVRCP_VENDOR_DEP_RSP, params),)),
              (100.1, ()), (100.2, ())]
    writes, text = _run_main(monkeypatch, script, snapshots)
    assert text[NX_RUNTIME["title"]] == nextion_title
    assert text[NX_RUNTIME["artist"]] == "Plini"
    assert text[NX_RUNTIME["album"]] == "Sunhead - EP"
    final = snapshots[-1][1]
    assert (final["title"], final["artist"], final["album"]) == (title, "Plini", "Sunhead - EP")
    assert raw == {1: title, 2: "Plini — Sunhead - EP", 4: "0"}
    assert any(frame[3:5] == bytes((Bm83.OP_EVENT_ACK, Bm83.EVT_AVRCP_VENDOR_DEP_RSP))
               for _stamp, frame in writes)

"""Host tests for the ESP-NOW wireless-remote receiver (lib/remote).

The receiver must speak exactly the Nextion token vocabulary, drop anything
that is not a well-formed frame from the paired remote, and never raise into
the main loop. main.py must merge its tokens before the shared dispatch.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import nextion
from remote import EspNowRemote, FRAME_PREFIX, PROBE_FRAME, fmt_mac, mac_to_bytes, parse_frame
from remote import espnow_rx

REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = REPO_ROOT / "firmware" / "circuitpython" / "main.py"
REMOTE_SRC = REPO_ROOT / "firmware" / "crowpanel-remote" / "src"

REMOTE_MAC = "44:1B:F6:8A:C1:7C"
REMOTE_MAC_B = bytes([0x44, 0x1B, 0xF6, 0x8A, 0xC1, 0x7C])
OTHER_MAC_B = bytes([0x02, 0x00, 0x00, 0x00, 0x00, 0x01])


class FakePacket:
    def __init__(self, mac, msg, rssi=-42):
        self.mac = mac
        self.msg = msg
        self.rssi = rssi


class FakeESPNow:
    """Mimics CircuitPython espnow.ESPNow: falsy when empty, read() -> packet|None."""

    def __init__(self):
        self.queue = []
        self.reads = 0
        self.fail_next = False

    def __bool__(self):
        return bool(self.queue)

    def read(self):
        self.reads += 1
        if self.fail_next:
            self.fail_next = False
            raise OSError("radio hiccup")
        return self.queue.pop(0) if self.queue else None


class FakeModule:
    def __init__(self, raise_on_init=None):
        self.raise_on_init = raise_on_init
        self.radio = None

    def ESPNow(self):
        if self.raise_on_init is not None:
            raise self.raise_on_init
        self.radio = FakeESPNow()
        return self.radio


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


def frame(seq, tok):
    return b"BMR1:%d:%s" % (seq, tok)


def make_remote(peer_mac=REMOTE_MAC):
    mod = FakeModule()
    clock = Clock()
    logs = []
    remote = EspNowRemote(peer_mac=peer_mac, espnow_module=mod, clock=clock, log=logs.append)
    assert remote.setup()
    return remote, mod.radio, clock, logs


# ----------------------------------------------------------------------------
# Frame parsing
# ----------------------------------------------------------------------------


def test_parse_frame_accepts_every_nextion_token():
    assert nextion.TOKENS, "Nextion vocabulary must not be empty"
    for tok in nextion.TOKENS:
        assert parse_frame(frame(7, tok)) == (7, tok)


def test_parse_frame_seq_bounds():
    assert parse_frame(b"BMR1:0:BT_PLAY") == (0, b"BT_PLAY")
    assert parse_frame(b"BMR1:4294967295:BT_PLAY") == (0xFFFFFFFF, b"BT_PLAY")
    assert parse_frame(b"BMR1:4294967296:BT_PLAY") is None


@pytest.mark.parametrize("msg", [
    None,
    b"",
    b"BMR1:",
    b"BMR1::BT_PLAY",
    b"BMR1:12BT_PLAY",
    b"BMR1:x1:BT_PLAY",
    b"BMR1:+1:BT_PLAY",
    b"BMR1: 1:BT_PLAY",
    b"BMR1:12345678901:BT_PLAY",
    b"BMR1:1:bt_play",
    b"BMR1:1:BT_PLAY\x00",
    b"BMR1:1:BT_PLAY ",
    b"BMR1:1:BT_FOO",
    b"BMR1:1:",
    b"BMR1:1:BT_PLAY:extra",
    b"BMR2:1:BT_PLAY",
    b"bmr1:1:BT_PLAY",
    b"BMS1:1:vol=3",
    b"BMR1:1:" + b"A" * 60,
])
def test_parse_frame_rejects_malformed(msg):
    assert parse_frame(msg) is None


def test_parse_frame_accepts_bytearray():
    assert parse_frame(bytearray(b"BMR1:3:BT_NEXT")) == (3, b"BT_NEXT")


# ----------------------------------------------------------------------------
# MAC helpers
# ----------------------------------------------------------------------------


def test_mac_helpers_round_trip():
    assert mac_to_bytes(REMOTE_MAC) == REMOTE_MAC_B
    assert mac_to_bytes(REMOTE_MAC.lower()) == REMOTE_MAC_B
    assert mac_to_bytes(REMOTE_MAC_B) == REMOTE_MAC_B
    assert fmt_mac(REMOTE_MAC_B) == REMOTE_MAC
    assert fmt_mac(None) == "?"


@pytest.mark.parametrize("bad", [
    None, 123, "", "44:1B:F6:8A:C1", "44:1B:F6:8A:C1:7C:00", "4:1B:F6:8A:C1:7C",
    "GG:1B:F6:8A:C1:7C", "+1:1B:F6:8A:C1:7C", "44-1B-F6-8A-C1-7C", b"\x01\x02",
])
def test_mac_to_bytes_rejects_malformed(bad):
    assert mac_to_bytes(bad) is None


# ----------------------------------------------------------------------------
# Receiver bring-up: every failure path leaves the receiver off, never raises
# ----------------------------------------------------------------------------


def test_setup_without_espnow_module_stays_off(monkeypatch):
    monkeypatch.setattr(espnow_rx, "_espnow", None)
    logs = []
    remote = EspNowRemote(peer_mac=REMOTE_MAC, log=logs.append)
    assert remote.setup() is False
    assert remote.poll() == ()
    assert any("no espnow module" in line for line in logs)


def test_setup_disabled_by_config_never_touches_radio():
    mod = FakeModule()
    logs = []
    remote = EspNowRemote(enabled=False, peer_mac=REMOTE_MAC, espnow_module=mod, log=logs.append)
    assert remote.setup() is False
    assert mod.radio is None
    assert remote.poll() == ()
    assert any("disabled by config" in line for line in logs)


def test_setup_bad_mac_fails_closed():
    mod = FakeModule()
    logs = []
    remote = EspNowRemote(peer_mac="not-a-mac", espnow_module=mod, log=logs.append)
    assert remote.setup() is False
    assert mod.radio is None
    assert any("bad REMOTE_MAC" in line for line in logs)


def test_setup_radio_failure_is_contained():
    mod = FakeModule(raise_on_init=RuntimeError("wifi unavailable"))
    logs = []
    remote = EspNowRemote(peer_mac=REMOTE_MAC, espnow_module=mod, log=logs.append)
    assert remote.setup() is False
    assert remote.poll() == ()
    assert any("init failed" in line for line in logs)


@pytest.mark.parametrize("runtime,ble,expect_up", [
    (("circuitpython", (10, 0, 3)), True, False),   # coexistence fault: refuse
    (("circuitpython", (10, 0, 3)), False, True),   # no BLE: 10.0.x is fine
    (("circuitpython", (10, 1, 0)), True, True),    # ESP-IDF 5.5.1 fix
    (("circuitpython", (10, 2, 0)), True, True),
    (("cpython", (3, 11, 0)), True, True),          # host: never gated
])
def test_ble_coexistence_gate(runtime, ble, expect_up):
    mod = FakeModule()
    logs = []
    remote = EspNowRemote(peer_mac=REMOTE_MAC, espnow_module=mod, log=logs.append,
                          ble_active=ble, runtime=runtime)
    assert remote.setup() is expect_up
    # Refusing must leave the WiFi radio untouched, so BLE keeps the RF.
    assert (mod.radio is not None) is expect_up
    if not expect_up:
        assert remote.poll() == ()
        assert any("upgrade CircuitPython to 10.1+" in line for line in logs)


def test_main_tells_receiver_whether_ble_runs():
    source = MAIN_PATH.read_text(encoding="utf-8")
    assert "ble_active=BLE_ENABLED" in source


def test_setup_reports_pairing():
    _remote, _radio, _clock, logs = make_remote()
    assert any("receiver up" in line and "accepting=" + REMOTE_MAC in line for line in logs)


# ----------------------------------------------------------------------------
# Receive path
# ----------------------------------------------------------------------------


def test_token_from_paired_remote_is_returned_and_logged():
    remote, radio, _clock, logs = make_remote()
    radio.queue.append(FakePacket(REMOTE_MAC_B, frame(1, b"BT_PLAY")))
    assert remote.poll() == [b"BT_PLAY"]
    assert remote.rx_ok == 1
    assert "[REMOTE] BT_PLAY seq=1 rssi=-42" in logs


def test_foreign_sender_is_dropped_and_logged_once():
    remote, radio, _clock, logs = make_remote()
    radio.queue.append(FakePacket(OTHER_MAC_B, frame(1, b"BT_EBIND")))
    radio.queue.append(FakePacket(OTHER_MAC_B, frame(2, b"BT_EBIND")))
    assert remote.poll() == ()
    assert remote.rx_foreign == 2
    assert sum("ignoring ESP-NOW from 02:00:00:00:00:01" in line for line in logs) == 1


def test_unpaired_receiver_accepts_any_sender():
    remote, radio, _clock, logs = make_remote(peer_mac=None)
    radio.queue.append(FakePacket(OTHER_MAC_B, frame(1, b"BT_NEXT")))
    assert remote.poll() == [b"BT_NEXT"]
    assert any("accepting=any MAC" in line for line in logs)


def test_malformed_frame_from_paired_remote_is_counted_not_returned():
    remote, radio, _clock, _logs = make_remote()
    radio.queue.append(FakePacket(REMOTE_MAC_B, b"BMR1:1:BT_NOPE"))
    assert remote.poll() == ()
    assert remote.rx_bad == 1


def test_discovery_probe_is_ignored_not_counted_as_bad():
    # The remote probes every channel with PROBE_FRAME to find ours; the ACK
    # is all it needs, so the frame is neither a token nor an error.
    remote, radio, _clock, _logs = make_remote()
    radio.queue.append(FakePacket(REMOTE_MAC_B, PROBE_FRAME))
    assert remote.poll() == ()
    assert remote.rx_probe == 1
    assert remote.rx_bad == 0
    assert parse_frame(PROBE_FRAME) is None


def test_crowpanel_probe_matches_receiver():
    link_cpp = REMOTE_SRC / "espnow_link.cpp"
    if not link_cpp.exists():
        pytest.skip("crowpanel-remote ESP-NOW sender not present on this branch")
    src = link_cpp.read_text(encoding="utf-8")
    assert 'PROBE_FRAME[]      = "%s"' % PROBE_FRAME.decode() in src


def test_duplicate_delivery_is_dropped():
    remote, radio, clock, _logs = make_remote()
    radio.queue.append(FakePacket(REMOTE_MAC_B, frame(5, b"BT_PLAY")))
    radio.queue.append(FakePacket(REMOTE_MAC_B, frame(5, b"BT_PLAY")))
    assert remote.poll() == [b"BT_PLAY"]
    assert remote.rx_dup == 1
    clock.t += 0.1
    radio.queue.append(FakePacket(REMOTE_MAC_B, frame(6, b"BT_PLAY")))
    assert remote.poll() == [b"BT_PLAY"]


def test_same_seq_after_window_is_a_new_press():
    # The remote rebooted and restarted its counter: not a duplicate.
    remote, radio, clock, _logs = make_remote()
    radio.queue.append(FakePacket(REMOTE_MAC_B, frame(1, b"BT_PLAY")))
    assert remote.poll() == [b"BT_PLAY"]
    clock.t += espnow_rx.DUP_WINDOW_S + 1.0
    radio.queue.append(FakePacket(REMOTE_MAC_B, frame(1, b"BT_PLAY")))
    assert remote.poll() == [b"BT_PLAY"]


def test_volume_press_release_pair_passes_through_in_order():
    remote, radio, _clock, _logs = make_remote()
    radio.queue.append(FakePacket(REMOTE_MAC_B, frame(1, b"BT_VOLUP_P")))
    radio.queue.append(FakePacket(REMOTE_MAC_B, frame(2, b"BT_VOLUP_R")))
    assert remote.poll() == [b"BT_VOLUP_P", b"BT_VOLUP_R"]


def test_poll_is_bounded_per_call():
    remote, radio, _clock, _logs = make_remote()
    for seq in range(1, 11):
        radio.queue.append(FakePacket(REMOTE_MAC_B, frame(seq, b"BT_NEXT")))
    assert len(remote.poll(max_frames=4)) == 4
    assert len(remote.poll(max_frames=4)) == 4
    assert len(remote.poll(max_frames=4)) == 2
    assert remote.poll(max_frames=4) == ()


def test_idle_poll_skips_read():
    remote, radio, _clock, _logs = make_remote()
    assert remote.poll() == ()
    assert radio.reads == 0


def test_read_error_is_contained_then_backs_off_then_recovers():
    remote, radio, clock, logs = make_remote()
    radio.queue.append(FakePacket(REMOTE_MAC_B, frame(9, b"BT_PREV")))
    radio.fail_next = True
    assert remote.poll() == ()          # error swallowed, nothing raised
    assert remote.rx_err == 1
    assert any("read error #1" in line for line in logs)
    reads = radio.reads
    clock.t += espnow_rx.ERROR_BACKOFF_S - 0.5
    assert remote.poll() == ()          # still paused: radio untouched
    assert radio.reads == reads
    clock.t += 1.0
    assert remote.poll() == [b"BT_PREV"]  # time-bounded pause, then recovery


def test_stats_line_only_when_counters_change():
    remote, radio, clock, logs = make_remote()

    def stats_lines():
        return [line for line in logs if line.startswith("[REMOTE] rx ok=")]

    clock.t += espnow_rx.STATS_PERIOD_S
    remote.poll()
    assert stats_lines() == ["[REMOTE] rx ok=0 dup=0 foreign=0 bad=0 err=0 probe=0"]
    clock.t += espnow_rx.STATS_PERIOD_S
    remote.poll()
    assert len(stats_lines()) == 1      # unchanged -> silent
    radio.queue.append(FakePacket(REMOTE_MAC_B, frame(1, b"BT_EQ")))
    remote.poll()
    clock.t += espnow_rx.STATS_PERIOD_S
    remote.poll()
    assert stats_lines()[-1] == "[REMOTE] rx ok=1 dup=0 foreign=0 bad=0 err=0 probe=0"


# ----------------------------------------------------------------------------
# main.py wiring: remote tokens go through the SAME dispatch as panel tokens
# ----------------------------------------------------------------------------


def _main_constant(name):
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("%s not defined at module level in main.py" % name)


def test_main_merges_remote_tokens_before_the_shared_dispatch():
    source = MAIN_PATH.read_text(encoding="utf-8")
    assert "from remote import EspNowRemote" in source
    merge = source.index("remote_tokens = remote_poll()")
    dispatch = source.index("for tok in tokens:")
    assert merge < dispatch, "remote tokens must be merged before the dispatch loop"
    assert "tokens = list(tokens) + list(remote_tokens)" in source
    # Exactly one dispatch loop: remote tokens must not get a private path
    # that skips the aux_mode / EBIND / hold-and-repeat gates.
    assert source.count("for tok in tokens:") == 1


def test_main_remote_config_is_valid():
    assert _main_constant("REMOTE_ENABLED") in (True, False)
    assert mac_to_bytes(_main_constant("REMOTE_MAC")) is not None


# ----------------------------------------------------------------------------
# Cross-check against the CrowPanel firmware once it is on the branch
# ----------------------------------------------------------------------------


def test_crowpanel_remote_emits_only_nextion_vocabulary():
    main_cpp = REMOTE_SRC / "main.cpp"
    if not main_cpp.exists():
        pytest.skip("firmware/crowpanel-remote not present on this branch")
    src = main_cpp.read_text(encoding="utf-8")
    emitted = set()
    for cb, tok in re.findall(
        r'(cb_click|cb_press_release),\s*LV_EVENT_[A-Z_]+,\s*\(void \*\)"([A-Z0-9_]+)"', src
    ):
        if cb == "cb_click":
            emitted.add(tok.encode())
        else:
            emitted.add((tok + "_P").encode())
            emitted.add((tok + "_R").encode())
    assert emitted, "no button tokens found in crowpanel-remote main.cpp"
    for tok in emitted:
        assert tok in nextion.TOKENS, "remote emits %r, which the Nextion dispatch does not know" % tok
        assert parse_frame(frame(1, tok)) == (1, tok)


def test_crowpanel_remote_frame_format_matches_receiver():
    link_cpp = REMOTE_SRC / "espnow_link.cpp"
    if not link_cpp.exists():
        pytest.skip("crowpanel-remote ESP-NOW sender not present on this branch")
    src = link_cpp.read_text(encoding="utf-8")
    assert '"%s%%lu:%%s"' % FRAME_PREFIX.decode() in src

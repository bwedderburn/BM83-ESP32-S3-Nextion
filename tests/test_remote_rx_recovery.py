"""Recover native ESP-NOW framing damage while retaining application safety."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from remote.espnow_rx import ERROR_BACKOFF_S, PROBE_FRAME, EspNowRemote

PEER = bytes.fromhex("441bf68ac17c")
FOREIGN = bytes.fromhex("021234567890")


class Radio:
    def __init__(self, error=None, deinit_failures=0):
        self.error = error
        self.deinit_failures = deinit_failures
        self.deinit_calls = 0
        self.deinited = False
        self.queue = []
        self.peers = []
        self.send_success = 0
        self.send_failure = 0
        self.sent = []

    def __bool__(self):
        return self.error is not None or bool(self.queue)

    def read(self):
        if self.error is not None:
            raise self.error
        return self.queue.pop(0) if self.queue else None

    def send(self, frame, peer):
        assert not self.deinited
        self.sent.append((frame, peer.mac))

    def deinit(self):
        self.deinit_calls += 1
        if self.deinit_failures:
            self.deinit_failures -= 1
            raise OSError("deinit temporarily unavailable")
        self.deinited = True


class Module:
    def __init__(self, *radios):
        self.radios = list(radios)
        self.calls = 0

    def ESPNow(self):
        self.calls += 1
        value = self.radios.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    class Peer:
        def __init__(self, mac):
            self.mac = mac


class CompletedRadio(Radio):
    """A native-like ring can expose bytes before a packet is complete."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.read_success = 0
        self.read_calls = 0

    def capture(self, packet, complete=True):
        self.queue.append(packet)
        if complete:
            self.read_success = (self.read_success + 1) & 0xFFFFFFFF

    def read(self):
        self.read_calls += 1
        return super().read()


def token(seq, value=b"BT_NEXT", mac=PEER):
    return SimpleNamespace(mac=mac, msg=b"BMR1:%d:" % seq + value, rssi=-42)


def receiver(*radios):
    clock = SimpleNamespace(now=100.0)
    logs = []
    module = Module(*radios)
    remote = EspNowRemote(peer_mac=PEER, espnow_module=module,
                          clock=lambda: clock.now, log=logs.append)
    assert remote.setup()
    assert remote.state_tx_enabled
    return remote, module, clock, logs


def test_persistent_invalid_buffer_rebuilds_once_and_restores_controls_and_reverse_state():
    broken, fresh = Radio(ValueError("Invalid buffer")), Radio()
    remote, module, _clock, logs = receiver(broken, fresh)
    remote._tx_pending = True
    remote._tx_counts = (12, 3)
    remote._tx_backoff_until = 999
    assert remote.poll() == ()
    assert broken.deinit_calls == 1 and broken.deinited
    assert module.calls == 2
    assert remote.rx_err == 1 and remote.rx_recoveries == 1
    assert remote.enabled and remote.state_tx_enabled
    assert not remote._tx_pending and remote._tx_counts == (0, 0)
    assert remote._tx_backoff_until == 0
    assert len(fresh.peers) == 1 and fresh.peers[0].mac == PEER
    fresh.queue.append(token(1))
    assert remote.poll() == [b"BT_NEXT"]
    assert remote.send_state_frame(b"BMS2fresh state")
    assert fresh.sent == [(b"BMS2fresh state", PEER)]
    assert any("receive buffer restored" in line for line in logs)


def test_recent_sequences_mac_filter_and_receive_counters_survive_recovery():
    original, fresh = Radio(), Radio()
    remote, _module, _clock, _logs = receiver(original, fresh)
    original.queue.append(token(7, b"BT_VOLUP_P"))
    assert remote.poll() == [b"BT_VOLUP_P"]
    original.error = ValueError("Invalid buffer")
    assert remote.poll() == ()
    fresh.queue.extend([token(7, b"BT_VOLUP_P"), token(8, mac=FOREIGN), token(9, b"BT_VOLUP_R")])
    assert remote.poll() == [b"BT_VOLUP_R"]
    assert remote.peer_mac == PEER
    assert remote.rx_ok == 2 and remote.rx_dup == 1 and remote.rx_foreign == 1 and remote.rx_err == 1


@pytest.mark.parametrize("error", [
    OSError("radio hiccup"), ValueError("different error"),
    ValueError("Invalid buffer", "extra argument"), RuntimeError("Invalid buffer"),
])
def test_other_errors_preserve_existing_backoff_without_reinitializing_radio(error):
    radio = Radio(error)
    remote, module, clock, logs = receiver(radio)
    assert remote.poll() == ()
    assert remote.rx_err == 1
    assert radio.deinit_calls == 0 and module.calls == 1
    radio.error = None
    radio.queue.append(token(1))
    clock.now += ERROR_BACKOFF_S - 0.01
    assert remote.poll() == ()
    clock.now += 0.02
    assert remote.poll() == [b"BT_NEXT"]
    assert not any("rebuilding" in line for line in logs)


def test_constructor_failure_retries_after_cooldown_even_with_receiver_disabled():
    broken, fresh = Radio(ValueError("Invalid buffer")), Radio()
    remote, module, clock, logs = receiver(broken, OSError("init unavailable"), fresh)
    assert remote.poll() == ()
    assert not remote.enabled and not remote.state_tx_enabled
    assert remote._rx_restart_pending
    assert module.calls == 2 and broken.deinit_calls == 1
    log_count = len(logs)
    for _ in range(100):
        assert remote.poll() == ()
    assert module.calls == 2 and len(logs) == log_count
    clock.now += ERROR_BACKOFF_S
    assert remote.poll() == ()
    assert remote.enabled and remote.state_tx_enabled and remote.rx_recoveries == 1
    assert module.calls == 3 and broken.deinit_calls == 1
    fresh.queue.append(token(1))
    assert remote.poll() == [b"BT_NEXT"]


def test_deinit_failure_retains_old_instance_for_one_later_bounded_attempt():
    broken, fresh = Radio(ValueError("Invalid buffer"), deinit_failures=1), Radio()
    remote, module, clock, _logs = receiver(broken, fresh)
    assert remote.poll() == ()
    assert not remote.enabled and remote._rx_restart_pending
    assert broken.deinit_calls == 1 and module.calls == 1
    clock.now += ERROR_BACKOFF_S
    assert remote.poll() == ()
    assert broken.deinit_calls == 2 and broken.deinited and module.calls == 2
    assert remote.enabled and remote.state_tx_enabled


def test_repeated_corruption_cannot_spin_reinitialization_or_logs_in_main_loop():
    first = Radio(ValueError("Invalid buffer"))
    second = Radio(ValueError("Invalid buffer"))
    fresh = Radio()
    remote, module, clock, logs = receiver(first, second, fresh)
    assert remote.poll() == ()
    assert remote.rx_recoveries == 1 and module.calls == 2
    clock.now += 0.01
    assert remote.poll() == ()
    assert remote._rx_restart_pending and module.calls == 2
    log_count = len(logs)
    for _ in range(100):
        assert remote.poll() == ()
    assert len(logs) == log_count and module.calls == 2
    clock.now = 100 + ERROR_BACKOFF_S
    assert remote.poll() == ()
    assert remote.rx_recoveries == 2 and module.calls == 3


def test_tokens_accepted_before_buffer_damage_remain_accepted_after_recovery():
    class PartialRadio(Radio):
        def read(self):
            if self.queue:
                return self.queue.pop(0)
            raise ValueError("Invalid buffer")

    old, fresh = PartialRadio(), Radio()
    old.error = ValueError("Invalid buffer")  # Keep __bool__ true after its good packet.
    old.queue.append(token(1, b"BT_VOLUP_R"))
    remote, _module, _clock, _logs = receiver(old, fresh)
    assert remote.poll() == [b"BT_VOLUP_R"]
    assert remote.rx_ok == 1 and remote.rx_recoveries == 1


def test_recovery_never_toggles_joined_wifi_or_resets_application_state(monkeypatch):
    class JoinedRadio:
        connected = True
        ipv4_address = "192.168.0.75"
        power_management = "NONE"

        @property
        def enabled(self):
            return True

        @enabled.setter
        def enabled(self, _value):
            raise AssertionError("recovery must not toggle the joined Wi-Fi radio")

    import sys
    joined = JoinedRadio()
    monkeypatch.setitem(sys.modules, "wifi", SimpleNamespace(radio=joined, PowerManagement=SimpleNamespace(NONE="NONE")))
    broken, fresh = Radio(ValueError("Invalid buffer")), Radio()
    remote, _module, _clock, _logs = receiver(broken, fresh)
    assert remote.poll() == ()
    assert joined.connected and joined.ipv4_address == "192.168.0.75"
    assert remote.enabled and remote.rx_recoveries == 1


def test_partial_native_header_is_not_read_until_the_complete_capture_counter_advances():
    radio = CompletedRadio()
    remote, _module, _clock, _logs = receiver(radio)
    radio.capture(token(1), complete=False)
    assert bool(radio)
    assert remote.poll() == ()
    assert radio.read_calls == 0 and remote.rx_err == 0
    radio.read_success += 1
    assert remote.poll() == [b"BT_NEXT"]
    assert radio.read_calls == 1 and remote._rx_consumed == 1


def test_each_drain_iteration_checks_complete_capture_count_before_reading_partial_tail():
    radio = CompletedRadio()
    remote, _module, _clock, _logs = receiver(radio)
    radio.capture(token(1))
    radio.capture(token(2), complete=False)
    assert remote.poll(max_frames=4) == [b"BT_NEXT"]
    assert radio.read_calls == 1 and len(radio.queue) == 1
    radio.read_success += 1
    assert remote.poll(max_frames=4) == [b"BT_NEXT"]
    assert radio.read_calls == 2 and not radio.queue


def test_foreign_probe_and_bad_frames_all_advance_consumption_before_valid_control():
    radio = CompletedRadio()
    remote, _module, _clock, _logs = receiver(radio)
    radio.capture(token(1, mac=FOREIGN))
    radio.capture(SimpleNamespace(mac=PEER, msg=PROBE_FRAME))
    radio.capture(SimpleNamespace(mac=PEER, msg=b"invalid BMR frame"))
    radio.capture(token(2))
    assert remote.poll(max_frames=4) == [b"BT_NEXT"]
    assert remote._rx_consumed == radio.read_success == 4
    assert remote.rx_foreign == remote.rx_probe == remote.rx_bad == remote.rx_ok == 1
    assert remote.poll() == ()
    assert radio.read_calls == 4


def test_complete_capture_and_consumption_counters_wrap_as_native_uint32():
    radio = CompletedRadio()
    remote, _module, _clock, _logs = receiver(radio)
    radio.read_success = remote._rx_consumed = 0xFFFFFFFE
    radio.capture(token(1))
    radio.capture(token(2))
    assert radio.read_success == 0
    assert remote.poll() == [b"BT_NEXT", b"BT_NEXT"]
    assert remote._rx_consumed == 0 and radio.read_calls == 2
    assert remote.poll() == ()


def test_receiver_rebuild_resets_consumed_count_for_the_new_native_instance():
    broken = CompletedRadio()
    fresh = CompletedRadio()
    remote, _module, _clock, _logs = receiver(broken, fresh)
    broken.read_success = remote._rx_consumed = 50
    broken.read_success += 1
    broken.error = ValueError("Invalid buffer")
    assert remote.poll() == ()
    assert remote.rx_recoveries == 1 and remote._rx_consumed == 0
    fresh.capture(token(1))
    assert remote.poll() == [b"BT_NEXT"]
    assert remote._rx_consumed == 1


@pytest.mark.parametrize("counter", [None, True, object(), MagicMock(spec=int)])
def test_noninteger_capture_property_uses_existing_buffer_fallback(counter):
    radio = Radio()
    radio.read_success = counter
    remote, _module, _clock, _logs = receiver(radio)
    radio.queue.append(token(1))
    assert remote.poll() == [b"BT_NEXT"]

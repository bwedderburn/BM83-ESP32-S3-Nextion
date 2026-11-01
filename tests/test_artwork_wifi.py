"""Host checks for private startup Wi-Fi profiles; no radio/network I/O."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "firmware/circuitpython/lib/remote/artwork_wifi.py"
SPEC = importlib.util.spec_from_file_location("artwork_wifi", SOURCE)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def profile(**changes):
    data = {"ssid": "Artwork test", "password": "private-passphrase", "bssid": "02:12:34:56:78:90", "channel": 6}  # nosec B105 - synthetic host-test profile
    data.update(changes)
    return data


def write_profile(tmp_path, data=None):
    path = tmp_path / ".artwork_wifi.json"
    path.write_text(json.dumps(profile() if data is None else data))
    return str(path)


@pytest.mark.parametrize("changes", [
    {"ssid": ""}, {"ssid": "é" * 17}, {"ssid": "bad\0ssid"}, {"password": "short"},  # nosec B105 - invalid synthetic profile
    {"password": "x" * 64}, {"password": 123}, {"channel": 0}, {"channel": 14},  # nosec B105 - invalid synthetic length/type
    {"channel": True}, {"channel": 6.0}, {"bssid": "FF:FF:FF:FF:FF:FF"},
    {"bssid": "00:00:00:00:00:00"}, {"bssid": "02:12:34:56:78"},
    {"bssid": "02:12:34:56:78:GG"}, {"version": 2},
])
def test_rejects_invalid_profiles_without_secret_in_error(changes):
    with pytest.raises(ValueError) as raised:
        module.validate_profile(profile(**changes))
    assert "private-passphrase" not in str(raised.value)


def test_profile_limits_and_open_network():
    assert module.validate_profile(profile(password=""))["password"] == ""  # nosec B106 - open-network fixture
    assert module.validate_profile(profile(ssid="é" * 16))["ssid"] == "é" * 16


def test_absent_or_oversize_profile(tmp_path):
    assert module.load_profile(str(tmp_path / "absent")) is None
    path = tmp_path / "oversize"
    path.write_bytes(b" " * 513)
    with pytest.raises(ValueError):
        module.load_profile(str(path))


class Radio:
    def __init__(self, fail=False, connected=False, bssid=bytes.fromhex("021234567890")):
        self.connected = connected
        self.ap_info = SimpleNamespace(bssid=bssid, channel=11)
        self.calls = []
        self.fail = fail

    def connect(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.fail:
            raise RuntimeError("private-passphrase")
        self.connected = True


def test_startup_pins_ap_searches_all_channels_and_bounds_timeout(tmp_path):
    path = write_profile(tmp_path)
    radio = Radio()
    logs = []
    assert module.start_artwork_wifi(path, radio=radio, timeout_s=99, log=logs.append)
    assert radio.calls == [(("Artwork test", "private-passphrase"),
                            {"bssid": bytes.fromhex("021234567890"), "channel": 0, "timeout": 10})]
    assert logs == ["[NET] artwork Wi-Fi ready channel=11"]


def test_join_failure_is_optional_and_does_not_log_credentials(tmp_path):
    path = write_profile(tmp_path)
    logs = []
    assert not module.start_artwork_wifi(path, radio=Radio(fail=True), log=logs.append)
    assert all("private-passphrase" not in line for line in logs)


def test_existing_other_ap_is_not_silently_reconfigured(tmp_path):
    path = write_profile(tmp_path)
    radio = Radio(connected=True, bssid=bytes.fromhex("021234567891"))
    assert not module.start_artwork_wifi(path, radio=radio, log=lambda _line: None)
    assert radio.calls == []


def test_network_retry_only_restarts_with_a_valid_existing_profile(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "supervisor",
                        SimpleNamespace(runtime=SimpleNamespace(usb_connected=False)))
    called = []
    missing = str(tmp_path / "missing")
    assert not module.retry_artwork_wifi(missing, reload_fn=lambda: called.append(True), log=lambda _line: None)
    path = write_profile(tmp_path)
    assert module.retry_artwork_wifi(path, reload_fn=lambda: called.append(True), log=lambda _line: None)
    assert called == [True]


def test_default_retry_uses_hard_reset_not_supervisor_reload(tmp_path, monkeypatch):
    path = write_profile(tmp_path)
    before = Path(path).read_bytes()
    calls, logs = [], []
    monkeypatch.setitem(sys.modules, "microcontroller",
                        SimpleNamespace(reset=lambda: calls.append("hard")))
    monkeypatch.setitem(sys.modules, "supervisor",
                        SimpleNamespace(runtime=SimpleNamespace(usb_connected=False),
                                        reload=lambda: calls.append("soft")))
    assert module.retry_artwork_wifi(path, log=logs.append)
    assert calls == ["hard"]
    assert logs == ["[NET] requested hard-reset artwork Wi-Fi startup retry"]
    assert Path(path).read_bytes() == before


@pytest.mark.parametrize("controller", [None, SimpleNamespace()],
                         ids=["missing-module", "missing-reset"])
def test_retry_without_safe_reset_fails_closed(tmp_path, monkeypatch, controller):
    path = write_profile(tmp_path)
    before = Path(path).read_bytes()
    calls, logs = [], []
    monkeypatch.setitem(sys.modules, "microcontroller", controller)
    monkeypatch.setitem(sys.modules, "supervisor",
                        SimpleNamespace(runtime=SimpleNamespace(usb_connected=False),
                                        reload=lambda: calls.append("soft")))
    assert not module.retry_artwork_wifi(path, log=logs.append)
    assert calls == []
    assert logs == ["[NET] safe restart unavailable; use local RESET"]
    assert Path(path).read_bytes() == before


@pytest.mark.parametrize("serial_connected", [False, True])
@pytest.mark.parametrize("injected_reset", [False, True])
def test_remote_retry_refuses_enumerated_usb_even_without_serial(
        tmp_path, monkeypatch, serial_connected, injected_reset):
    path = write_profile(tmp_path)
    before = Path(path).read_bytes()
    calls, logs = [], []

    def reset():
        calls.append("hard")

    monkeypatch.setitem(sys.modules, "microcontroller", SimpleNamespace(reset=reset))
    monkeypatch.setitem(sys.modules, "supervisor", SimpleNamespace(
        runtime=SimpleNamespace(usb_connected=True, serial_connected=serial_connected),
        reload=lambda: calls.append("soft")))
    kwargs = {"reload_fn": reset} if injected_reset else {}
    assert not module.retry_artwork_wifi(path, log=logs.append, **kwargs)
    assert calls == []
    assert logs == ["[NET] remote restart refused while USB connected; safely eject and disconnect USB first"]
    assert Path(path).read_bytes() == before


class UnreadableUSB:
    @property
    def usb_connected(self):
        raise RuntimeError("synthetic USB read failure")


@pytest.mark.parametrize("supervisor", [
    None, SimpleNamespace(), SimpleNamespace(runtime=SimpleNamespace()),
    SimpleNamespace(runtime=UnreadableUSB()),
    *[SimpleNamespace(runtime=SimpleNamespace(usb_connected=value))
      for value in (None, 0, 1, "false")],
], ids=["missing-module", "missing-runtime", "missing-property", "read-error",
        "none", "zero", "one", "text"])
def test_remote_retry_refuses_unknown_usb_state(tmp_path, monkeypatch, supervisor):
    path = write_profile(tmp_path)
    before = Path(path).read_bytes()
    calls, logs = [], []
    monkeypatch.setitem(sys.modules, "supervisor", supervisor)
    assert not module.retry_artwork_wifi(path, reload_fn=lambda: calls.append("hard"), log=logs.append)
    assert calls == []
    assert logs == ["[NET] USB state unavailable; remote restart refused"]
    assert Path(path).read_bytes() == before


@pytest.mark.parametrize("usb_connected", [True, False])
def test_main_shared_retry_token_uses_usb_guard(tmp_path, monkeypatch, usb_connected):
    # Drive the real main-loop dispatch with a CrowPanel token and the real
    # retry implementation. Only reset/profile arguments are host fixtures.
    from remote import artwork_wifi
    from tests.test_main_metadata_retry import _Remote, _run_main

    path = write_profile(tmp_path)
    calls, logs = [], []
    retry = artwork_wifi.retry_artwork_wifi
    monkeypatch.setattr(artwork_wifi, "retry_artwork_wifi", lambda: retry(
        path, reload_fn=lambda: calls.append("hard"), log=logs.append))
    monkeypatch.setitem(sys.modules, "supervisor", SimpleNamespace(
        runtime=SimpleNamespace(usb_connected=usb_connected)))
    tokens = iter(((b"NET_RETRY",), ()))
    monkeypatch.setattr(_Remote, "poll", lambda _self: next(tokens, ()))
    _run_main(monkeypatch, [(100.0, ()), (100.1, ())])
    assert calls == ([] if usb_connected else ["hard"])
    assert logs == (["[NET] remote restart refused while USB connected; safely eject and disconnect USB first"]
                    if usb_connected else ["[NET] requested hard-reset artwork Wi-Fi startup retry"])


def test_invalid_network_retry_does_not_restart_or_expose_credentials(tmp_path):
    path = write_profile(tmp_path, profile(password="short"))  # nosec B106 - invalid synthetic profile
    called, logs = [], []
    assert not module.retry_artwork_wifi(path, reload_fn=lambda: called.append(True), log=logs.append)
    assert called == []
    assert all("short" not in line for line in logs)

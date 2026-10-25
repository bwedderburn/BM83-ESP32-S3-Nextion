import base64
import importlib.util
import json
from types import SimpleNamespace
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "tools/provision_artwork_wifi.py"
SPEC = importlib.util.spec_from_file_location("provision_artwork_wifi", SOURCE)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def response(nonce="a" * 32, **changes):
    profile = {"ssid": "Test", "password": "private-password", "bssid": "02:12:34:56:78:90", "channel": 6}  # nosec B105 - synthetic USB-provisioning fixture
    profile.update(changes)
    return b"BMWIFI_PROFILE:" + nonce.encode() + b":" + base64.b64encode(json.dumps(profile).encode())


def test_exact_nonce_and_validated_fields():
    assert module.decode_profile(response(), "a" * 32)["channel"] == 6
    assert module.decode_profile(response(), "b" * 32) is None
    assert module.decode_profile(b"[playback] fresh=1", "a" * 32) is None


@pytest.mark.parametrize("line", [response(channel=0), response(bssid="FF:FF:FF:FF:FF:FF"),
                                   response(password="short"), b"BMWIFI_PROFILE:" + b"a" * 32 + b":not-base64"])  # nosec B106 - invalid synthetic response
def test_invalid_response_errors_do_not_leak_secret(line):
    with pytest.raises(ValueError) as caught:
        module.decode_profile(line, "a" * 32)
    assert "private-password" not in str(caught.value)


def test_private_rollback_files_read_back_and_are_not_world_readable(tmp_path):
    path = tmp_path / "private-profile.json"
    data = b"private-password"
    module.private_write(path, data)
    assert path.read_bytes() == data
    assert path.stat().st_mode & 0o077 == 0
    path.chmod(0o644)
    module.private_write(path, data)
    assert path.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("host_file", [True, False])
@pytest.mark.parametrize("host", [SimpleNamespace(name="posix"),
                                   SimpleNamespace(name="nt", fchmod=lambda *_args: None)])
def test_private_write_rejects_unsupported_host_before_open(tmp_path, monkeypatch, host_file, host):
    path = tmp_path / "private-profile.json"
    path.write_bytes(b"unchanged private data")
    opened = []
    host.open = lambda *_args: opened.append(True)
    monkeypatch.setattr(module, "os", host)
    with pytest.raises(module.SetupError, match="requires macOS/Linux POSIX private file permissions"):
        module.private_write(path, b"replacement", host_file=host_file)
    assert not opened
    assert path.read_bytes() == b"unchanged private data"


def test_delayed_repl_prompt_still_resumes_after_interrupt():
    class Port:
        def __init__(self):
            self.writes = []

        def write(self, value):
            self.writes.append(value)

    port = Port()
    controller = module.Controller(port)
    controller.receive = lambda _seconds: b"no prompt yet"
    with pytest.raises(RuntimeError):
        controller.stop()
    assert controller.interrupt_sent and not controller.stopped
    controller.recover_if_interrupted()
    assert port.writes[-1] == b"\x04"
    assert not controller.interrupt_sent


def transaction(tmp_path, monkeypatch, *, controller_fails=False, crow_fails=False,
                commit_ack=True, abort_fails=False):
    """Run the real setup orchestration against deterministic USB stand-ins."""
    import sys

    volume = tmp_path / "device"
    (volume / "lib/remote").mkdir(parents=True)
    (volume / "lib/remote/artwork_wifi.mpy").write_bytes(b"firmware presence")
    old = b'{"ssid":"Old","password":"old-private-password","bssid":"02:00:00:00:00:02","channel":1}'
    target = volume / ".artwork_wifi.json"
    target.write_bytes(old)
    all_commands, port_objects = [], []
    nonce = "a" * 32

    class Port:
        def __init__(self, **_kwargs):
            self.port = None
            self.is_open = False
            self.responses = []
            port_objects.append(self)

        def open(self):
            self.is_open = True

        def close(self):
            self.is_open = False

        def write(self, data):
            all_commands.append(data)
            if data.startswith(b"BMWIFI_PROFILE:"):
                self.responses.append(response() + b"\n")
            elif data.startswith(b"BMWIFI_APPLY:"):
                status = b"FAILED_TEST" if crow_fails else b"CONNECTED"
                self.responses.append(b"BMWIFI_STATUS:" + nonce.encode() + b":" + status + b"\n")
                if not crow_fails:
                    self.responses.append(b"[playback] snapshot=1 fresh=1 power=1\n")
            elif data.startswith(b"BMWIFI_COMMIT:") and commit_ack:
                self.responses.append(b"BMWIFI_ACK:" + nonce.encode() + b":COMMITTED\n")
            elif data.startswith(b"BMWIFI_ABORT:") and abort_fails:
                raise OSError("untrusted raw USB response must stay out of logs")

        def read(self, _size):
            return self.responses.pop(0) if self.responses else b""

        def reset_input_buffer(self):
            self.responses.clear()

    class Controller:
        def __init__(self, _port):
            self.stopped = self.interrupt_sent = False
            self.events = _port.controller_events = []

        def stop(self):
            self.events.append("stop")
            self.stopped = self.interrupt_sent = True

        def start(self, verify_wifi):
            self.events.append(("start", verify_wifi))
            self.stopped = self.interrupt_sent = False
            if verify_wifi and controller_fails:
                raise RuntimeError("controller join failed")

        def recover_if_interrupted(self):
            self.events.append("recover")
            self.stopped = self.interrupt_sent = False

    ports = [SimpleNamespace(vid=0x303A, pid=0x7003, serial_number="UNIT", device="unit"),
             SimpleNamespace(vid=0x1A86, pid=0x7523, serial_number=None, device="crow")]
    monkeypatch.setitem(sys.modules, "serial", SimpleNamespace(Serial=Port))
    monkeypatch.setitem(sys.modules, "serial.tools", SimpleNamespace(list_ports=SimpleNamespace(comports=lambda: ports)))
    monkeypatch.setattr(module, "Controller", Controller)
    monkeypatch.setattr(module.secrets, "token_hex", lambda _size: nonce)
    ticks = iter(range(10000))
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    output = tmp_path / "private-setup"
    args = SimpleNamespace(controller_serial="UNIT", crow_port="crow", volume=str(volume), output=str(output))
    return args, target, old, all_commands, port_objects, output


def test_unsupported_host_fails_before_usb_files_or_commit(tmp_path, monkeypatch):
    args, target, old, commands, ports, output = transaction(tmp_path, monkeypatch)
    monkeypatch.setattr(module, "os", SimpleNamespace(name="posix"))
    with pytest.raises(module.SetupError, match="requires macOS/Linux POSIX private file permissions"):
        module.provision(args)
    assert not commands and not ports
    assert target.read_bytes() == old
    assert not output.exists()


def test_trial_is_committed_only_after_peer_proof(tmp_path, monkeypatch, capsys):
    args, target, _old, commands, ports, output = transaction(tmp_path, monkeypatch)
    module.provision(args)
    assert json.loads(target.read_bytes())["ssid"] == "Test"
    apply = next(i for i, command in enumerate(commands) if command.startswith(b"BMWIFI_APPLY:"))
    commit = next(i for i, command in enumerate(commands) if command.startswith(b"BMWIFI_COMMIT:"))
    assert apply < commit
    assert not any(command.startswith(b"BMWIFI_ABORT:") for command in commands)
    assert all(not port.is_open for port in ports)
    assert output.stat().st_mode & 0o077 == 0
    summary = output / "provisioning.json"
    assert summary.stat().st_mode & 0o077 == 0
    assert "profile_sha256" not in summary.read_text()
    assert "private-password" not in capsys.readouterr().out


@pytest.mark.parametrize("controller_fails,crow_fails", [(True, False), (False, True)])
def test_precommit_failure_aborts_panel_and_restores_unit(tmp_path, monkeypatch, controller_fails, crow_fails):
    args, target, old, commands, ports, _output = transaction(
        tmp_path, monkeypatch, controller_fails=controller_fails, crow_fails=crow_fails)
    with pytest.raises(RuntimeError):
        module.provision(args)
    assert target.read_bytes() == old
    assert any(command.startswith(b"BMWIFI_ABORT:") for command in commands)
    assert not any(command.startswith(b"BMWIFI_COMMIT:") for command in commands)
    assert all(not port.is_open for port in ports)


def test_abort_transport_failure_still_restores_and_resumes_controller(tmp_path, monkeypatch, capsys):
    args, target, old, commands, ports, _output = transaction(
        tmp_path, monkeypatch, crow_fails=True, abort_fails=True)
    with pytest.raises(module.SetupError, match="CrowPanel Wi-Fi join failed"):
        module.provision(args)
    assert target.read_bytes() == old
    assert any(command.startswith(b"BMWIFI_ABORT:") for command in commands)
    assert not any(command.startswith(b"BMWIFI_COMMIT:") for command in commands)
    assert ports[1].controller_events[-1] == ("start", False)
    assert all(not port.is_open for port in ports)
    output = capsys.readouterr().out
    assert "Panel abort could not be confirmed" in output
    assert "untrusted raw USB response" not in output
    assert "private-password" not in output


def test_rollback_write_failure_still_recovers_interrupted_controller(tmp_path, monkeypatch, capsys):
    args, _target, _old, commands, ports, _output = transaction(tmp_path, monkeypatch, crow_fails=True)
    original = module.private_write

    def fail_rollback(path, data, host_file=True):
        if not host_file:
            raise OSError("untrusted filesystem error must stay out of logs")
        return original(path, data, host_file=host_file)

    monkeypatch.setattr(module, "private_write", fail_rollback)
    with pytest.raises(OSError):
        module.provision(args)
    assert ports[1].controller_events[-1] == "recover"
    assert not any(command.startswith(b"BMWIFI_COMMIT:") for command in commands)
    assert all(not port.is_open for port in ports)
    output = capsys.readouterr().out
    assert "untrusted filesystem error" not in output
    assert "private-password" not in output


def test_lost_commit_ack_does_not_rollback_only_one_device(tmp_path, monkeypatch):
    args, target, _old, commands, ports, output = transaction(tmp_path, monkeypatch, commit_ack=False)
    with pytest.raises(RuntimeError):
        module.provision(args)
    assert json.loads(target.read_bytes())["ssid"] == "Test"
    assert any(command.startswith(b"BMWIFI_COMMIT:") for command in commands)
    assert not any(command.startswith(b"BMWIFI_ABORT:") for command in commands)
    assert json.loads((output / "provisioning.json").read_text())["commit_outcome"] == "unknown"
    assert all(not port.is_open for port in ports)

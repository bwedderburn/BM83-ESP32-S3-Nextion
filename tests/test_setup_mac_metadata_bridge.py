"""Provisioning tests use synthetic profiles on temporary host filesystems."""
import importlib.util
import json
import os
from pathlib import Path
import plistlib

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "tools/setup_mac_metadata_bridge.py"
SPEC = importlib.util.spec_from_file_location("setup_mac_metadata_bridge", SOURCE)
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


@pytest.fixture
def staged(tmp_path):
    volume = tmp_path / "CIRCUITPY"
    (volume / "lib/remote").mkdir(parents=True)
    (volume / "boot_out.txt").write_text("Adafruit CircuitPython 9.2.1 on ESP32-S3 with ESP32S3\n")
    (volume / "lib/remote/metadata_bridge.mpy").write_bytes(b"test receiver")
    (volume / ".artwork_wifi.json").write_text(json.dumps({"ssid": "Test LAN", "channel": 6, "password": "test-only"}))
    source = tmp_path / "source"
    source.mkdir()
    for name in setup.SOURCE_FILES:
        (source / name).write_bytes(b"test source")
    home = tmp_path / "Test User & Space"
    home.mkdir()
    return {"volume": volume, "host": "192.168.1.40", "home": home, "source": source,
            "python": "/usr/bin/python3"}


def profile(path, token="a" * 64, **fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(v=1, token=token, **fields)))
    path.chmod(0o600)


def fake_commands(monkeypatch, *, fail_build=False, fail_bootstrap=False):
    calls = []

    def command(arguments, check=True):
        calls.append((arguments, check))
        if "--build-helper" in arguments:
            if fail_build:
                raise setup.SetupError("Local helper build failed.")
            Path(arguments[-1]).write_bytes(b"test native helper")
        if "bootstrap" in arguments and fail_bootstrap and check:
            raise setup.SetupError("Agent startup failed.")

    monkeypatch.setattr(setup, "run_command", command)
    monkeypatch.setattr(setup.sys, "platform", "darwin")
    return calls


def test_validation_creates_no_files_and_does_not_change_wifi(staged):
    wifi = staged["volume"] / ".artwork_wifi.json"
    previous = wifi.read_bytes()
    plan = setup.prepare_setup(**staged)
    assert not plan["app"].exists()
    assert not plan["agent"].exists()
    assert not plan["receiver_path"].exists()
    assert wifi.read_bytes() == previous
    assert len(plan["host"]["token"]) == 64
    assert plan["host"]["token"] == plan["receiver"]["token"]
    assert "host_ip" not in plan["receiver"]


@pytest.mark.parametrize("host", ["localhost", "::1", "127.0.0.1", "0.0.0.0", "224.0.0.1", "255.255.255.255"])
def test_invalid_host_rejected_before_writes(staged, host):
    staged["host"] = host
    with pytest.raises(setup.SetupError):
        setup.prepare_setup(**staged)
    assert not (staged["home"] / "Library").exists()


@pytest.mark.parametrize("boot", ["CircuitPython on RP2040", "ESP32-S3 running another firmware"])
def test_wrong_usb_device_rejected(staged, boot):
    (staged["volume"] / "boot_out.txt").write_text(boot)
    with pytest.raises(setup.SetupError, match="ESP32-S3 CircuitPython"):
        setup.prepare_setup(**staged)


def test_receiver_firmware_and_existing_wifi_required(staged):
    (staged["volume"] / "lib/remote/metadata_bridge.mpy").unlink()
    with pytest.raises(setup.SetupError, match="Deploy"):
        setup.prepare_setup(**staged)
    (staged["volume"] / "lib/remote/metadata_bridge.py").write_text("# installed receiver")
    (staged["volume"] / ".artwork_wifi.json").write_text('{"ssid":"Test","channel":true}')
    with pytest.raises(setup.SetupError, match="Wi-Fi profile"):
        setup.prepare_setup(**staged)


def test_receiver_secrets_cannot_be_created_in_repository(staged):
    (staged["volume"].parent / ".git").write_text("gitdir: test-worktree")
    with pytest.raises(setup.SetupError, match="Git repository"):
        setup.prepare_setup(**staged)
    assert not (staged["volume"] / ".metadata_bridge.json").exists()


def test_existing_pairing_reused_and_mismatches_fail_without_secret(staged):
    receiver = staged["volume"] / ".metadata_bridge.json"
    profile(receiver)
    plan = setup.prepare_setup(**staged, host_ip="192.168.1.20")
    assert plan["host"]["token"] == "a" * 64
    assert plan["receiver"]["host_ip"] == "192.168.1.20"
    profile(plan["config_path"], token="b" * 64)
    with pytest.raises(setup.SetupError, match="different pairings") as caught:
        setup.prepare_setup(**staged)
    assert "a" * 64 not in str(caught.value) and "b" * 64 not in str(caught.value)


def test_host_secret_permissions_enforced(staged):
    plan = setup.prepare_setup(**staged)
    profile(plan["config_path"])
    plan["config_path"].chmod(0o644)
    with pytest.raises(setup.SetupError, match="mode 600"):
        setup.prepare_setup(**staged)


def test_existing_receiver_source_pin_preserved_without_new_flag(staged):
    profile(staged["volume"] / ".metadata_bridge.json", host_ip="192.168.1.20")
    plan = setup.prepare_setup(**staged)
    assert plan["receiver"]["host_ip"] == "192.168.1.20"


def test_existing_output_name_preserved_when_receiver_address_changes(staged):
    first = setup.prepare_setup(**staged)
    profile(first["config_path"], target_output="Renamed BM83", interval=1.0)
    plan = setup.prepare_setup(**staged)
    assert plan["host"]["target_output"] == "Renamed BM83"
    assert plan["host"]["interval"] == 1.0


@pytest.mark.parametrize("destination", ["receiver", "wifi", "app", "source"])
def test_symlink_paths_refused_without_touching_target(staged, tmp_path, destination):
    victim = tmp_path / "victim"
    victim.write_bytes(b"unchanged")
    paths = {"receiver": staged["volume"] / ".metadata_bridge.json",
             "wifi": staged["volume"] / ".artwork_wifi.json",
             "app": staged["home"] / "Library/Application Support/BM83MetadataBridge",
             "source": staged["source"] / "bridge.py"}
    path = paths[destination]
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    path.symlink_to(victim)
    with pytest.raises(setup.SetupError, match="symbolic links"):
        setup.prepare_setup(**staged)
    assert victim.read_bytes() == b"unchanged"


def test_pairing_install_and_plist_paths_remain_separate_arguments(staged, monkeypatch):
    calls = fake_commands(monkeypatch)
    plan = setup.prepare_setup(**staged)
    wifi = (staged["volume"] / ".artwork_wifi.json").read_bytes()
    setup.install(plan)
    host = json.loads(plan["config_path"].read_text())
    receiver = json.loads(plan["receiver_path"].read_text())
    assert host["token"] == receiver["token"]
    assert host["host"] == staged["host"] and host["target_output"] == "BM83"
    assert (staged["volume"] / ".artwork_wifi.json").read_bytes() == wifi
    for path in (plan["config_path"], plan["receiver_path"], plan["agent"], plan["app"] / "bridge.log"):
        assert path.stat().st_mode & 0o777 == 0o600
    assert plan["app"].stat().st_mode & 0o777 == 0o700
    assert not list(plan["app"].glob(".setup-*"))
    agent = plistlib.loads(plan["agent"].read_bytes())
    assert agent["ProgramArguments"] == [
        plan["python"], "-u", str(plan["app"] / "bridge.py"), "--config", str(plan["config_path"]),
        "--helper", str(plan["app"] / "now_playing.dylib"),
    ]
    assert agent["RunAtLoad"] and agent["KeepAlive"]
    assert all(host["token"] not in str(arguments) for arguments, _check in calls)
    assert calls[-1][0] == ["/bin/launchctl", "bootstrap", "gui/" + str(os.getuid()), str(plan["agent"])]


def test_failed_build_leaves_existing_profiles_and_agent_intact(staged, monkeypatch):
    fake_commands(monkeypatch, fail_build=True)
    plan = setup.prepare_setup(**staged)
    profile(plan["config_path"])
    profile(plan["receiver_path"])
    plan["agent"].parent.mkdir(parents=True)
    plan["agent"].write_bytes(b"previous agent")
    previous = {path: path.read_bytes() for path in (plan["config_path"], plan["receiver_path"], plan["agent"])}
    with pytest.raises(setup.SetupError, match="build failed"):
        setup.install(plan)
    assert all(path.read_bytes() == data for path, data in previous.items())


def test_agent_startup_failure_restores_paired_profiles(staged, monkeypatch):
    calls = fake_commands(monkeypatch, fail_bootstrap=True)
    plan = setup.prepare_setup(**staged)
    profile(plan["config_path"], host="192.168.1.99")
    profile(plan["receiver_path"])
    previous_host = plan["config_path"].read_bytes()
    previous_receiver = plan["receiver_path"].read_bytes()
    with pytest.raises(setup.SetupError, match="Agent startup failed"):
        setup.install(plan)
    assert plan["config_path"].read_bytes() == previous_host
    assert plan["receiver_path"].read_bytes() == previous_receiver
    assert not plan["agent"].exists()
    assert any("bootout" in arguments for arguments, _check in calls)


def test_cli_default_never_installs(staged, monkeypatch, capsys):
    plan = setup.prepare_setup(**staged)
    monkeypatch.setattr(setup, "prepare_setup", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(setup, "install", lambda _plan: pytest.fail("installation needs --install"))
    assert setup.main(["--volume", str(staged["volume"]), "--host", staged["host"]]) == 0
    assert "no files changed" in capsys.readouterr().out
    assert not plan["receiver_path"].exists()

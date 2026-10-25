#!/usr/bin/env python3
"""Pair the controller and install a local Mac metadata sender, only with --install.

The default command validates the proposed setup without writing any files.
Wi-Fi credentials remain in the controller's existing artwork Wi-Fi profile.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import stat
import subprocess
import sys
import tempfile

LABEL = "com.bwedderburn.bm83-metadata-bridge"
SOURCE_FILES = ("bridge.py", "now_playing.m", "read_now_playing.pl")
TOKEN_PATTERN = re.compile(r"[0-9a-fA-F]{32,128}\Z")


class SetupError(RuntimeError):
    """A fixed diagnostic that never contains secret profile contents."""


def safe_path(path):
    """Refuse symlinks in destinations and their existing parent directories."""
    path = Path(path).expanduser().absolute()
    for component in (path, *path.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise SetupError("Setup paths must not contain symbolic links.")
    return path


def read_regular(path, *, private=False, limit=8192):
    """Read a bounded regular file; host secrets must already be private."""
    path = safe_path(path)
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise SetupError("Setup files must be regular files.")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise SetupError("Setup files must be regular files.")
            if private and (info.st_uid != os.getuid() or info.st_mode & 0o077):
                raise SetupError("Existing host profile must be user-owned and private (mode 600).")
            data = handle.read(limit + 1)
        if len(data) > limit:
            raise SetupError("Setup file exceeds its size limit.")
        return data
    except OSError:
        raise SetupError("Cannot read a required setup file.") from None


def read_profile(path, *, private=False):
    """Load a valid existing pairing, retaining its token without printing it."""
    if not safe_path(path).exists():
        return None
    try:
        data = json.loads(read_regular(path, private=private, limit=4096))
        if (not isinstance(data, dict) or type(data.get("v")) is not int or data["v"] != 1
                or not isinstance(data.get("token"), str) or not TOKEN_PATTERN.fullmatch(data["token"])):
            raise ValueError
        return data
    except (ValueError, UnicodeError):
        raise SetupError("Existing bridge profile is invalid; restore its private backup before setup.") from None


def ipv4(value):
    """Require an explicit unicast IPv4 address rather than a hostname."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise SetupError("Use the controller's IPv4 address for --host and the Mac's IPv4 for --host-ip.") from None
    if (address.version != 4 or address.is_multicast or address.is_unspecified
            or address.is_loopback or str(address) == "255.255.255.255"):
        raise SetupError("Bridge addresses must be unicast LAN IPv4 addresses.")
    return str(address)


def validate_controller(volume):
    """Identify native CircuitPython USB and existing Wi-Fi without changing either."""
    volume = safe_path(volume)
    if not volume.is_dir():
        raise SetupError("Connect the BM83 controller's native USB port so CIRCUITPY is mounted.")
    if any((parent / ".git").exists() for parent in (volume, *volume.parents)):
        raise SetupError("Controller pairing profiles must not be written inside a Git repository.")
    boot = read_regular(volume / "boot_out.txt").decode("utf-8", errors="replace")
    if "CircuitPython" not in boot or not re.search(r"ESP32[-_ ]?S3", boot, re.IGNORECASE):
        raise SetupError("The selected volume is not an ESP32-S3 CircuitPython controller.")
    receiver = volume / "lib/remote/metadata_bridge.py"
    if not any(safe_path(candidate).is_file() for candidate in (receiver, receiver.with_suffix(".mpy"))):
        raise SetupError("Deploy the metadata bridge controller firmware before pairing.")
    try:
        wifi = json.loads(read_regular(volume / ".artwork_wifi.json", limit=2048))
        if (not isinstance(wifi, dict) or not isinstance(wifi.get("ssid"), str) or not wifi["ssid"]
                or type(wifi.get("channel")) is not int or not 1 <= wifi["channel"] <= 14):
            raise ValueError
    except (ValueError, UnicodeError):
        raise SetupError("Controller Wi-Fi profile is invalid; complete its Wi-Fi setup first.") from None
    return volume


def prepare_setup(volume, host, *, port=8766, host_ip=None, home=None, source=None, python=None):
    """Validate a complete installation plan without changing host or controller."""
    if os.name != "posix" or not hasattr(os, "fchmod"):
        raise SetupError("Setup requires macOS with POSIX private file permissions.")
    host = ipv4(host)
    host_ip = ipv4(host_ip) if host_ip is not None else None
    if type(port) is not int or not 1024 <= port <= 65535:
        raise SetupError("Bridge port must be between 1024 and 65535.")
    volume = validate_controller(volume)
    home = safe_path(home if home is not None else Path.home())
    app = safe_path(home / "Library/Application Support/BM83MetadataBridge")
    agent = safe_path(home / "Library/LaunchAgents" / (LABEL + ".plist"))
    source = safe_path(source if source is not None else Path(__file__).parent / "mac_metadata_bridge")
    sources = {name: read_regular(source / name, limit=131072) for name in SOURCE_FILES}
    config_path = safe_path(app / "config.json")
    receiver_path = safe_path(volume / ".metadata_bridge.json")
    existing_host = read_profile(config_path, private=True)
    existing_receiver = read_profile(receiver_path)
    if existing_host and existing_receiver and existing_host["token"] != existing_receiver["token"]:
        raise SetupError("Host and controller have different pairings; restore a matching private profile first.")
    previous = existing_host or existing_receiver
    token = previous["token"] if previous else secrets.token_hex(32)
    host_profile = {"v": 1, "host": host, "port": port, "token": token, "target_output": "BM83", "interval": 2.0}
    if existing_host:
        target = existing_host.get("target_output", "BM83")
        interval = existing_host.get("interval", 2.0)
        if (not isinstance(target, str) or not target.strip() or len(target.encode("utf-8")) > 256
                or type(interval) not in (int, float) or not 0.5 <= interval <= 3.0):
            raise SetupError("Existing host bridge settings are invalid; correct the private profile before setup.")
        host_profile.update(target_output=target.strip(), interval=interval)
    receiver_profile = {"v": 1, "port": port, "token": token}
    if host_ip is None and existing_receiver and "host_ip" in existing_receiver:
        host_ip = ipv4(existing_receiver["host_ip"])
    if host_ip is not None:
        receiver_profile["host_ip"] = host_ip
    for path in (app, app / "now_playing.dylib", app / "bridge.log", app / "bridge-error.log"):
        safe_path(path)
    return {"app": app, "agent": agent, "sources": sources, "host": host_profile,
            "receiver": receiver_profile, "config_path": config_path, "receiver_path": receiver_path,
            "python": str(Path(python or sys.executable).absolute())}


def private_directory(path):
    """Restrict the bridge's own directory without changing shared Library folders."""
    path = safe_path(path)
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.stat().st_uid != os.getuid():
        raise SetupError("Bridge directory must belong to the current user.")
    path.chmod(0o700)


def atomic_write(path, data, *, host_file=True):
    """Replace complete files atomically; FAT receiver permissions are best effort."""
    path = safe_path(path)
    if path.exists() and not path.is_file():
        raise SetupError("Setup destination must be a regular file.")
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as handle:
            try:
                os.fchmod(handle.fileno(), 0o600)
            except OSError:
                if host_file:
                    raise
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        safe_path(path)
        os.replace(temporary, path)
        if read_regular(path, private=host_file, limit=max(len(data), 4096)) != data:
            raise SetupError("Setup file read-back verification failed.")
    finally:
        if temporary.exists():
            temporary.unlink()


def launch_agent(plan):
    """Keep every path a separate plist argument, including paths with spaces."""
    app = plan["app"]
    return {"Label": LABEL,
            "ProgramArguments": [plan["python"], "-u", str(app / "bridge.py"),
                                 "--config", str(plan["config_path"]), "--helper", str(app / "now_playing.dylib")],
            "WorkingDirectory": str(app), "RunAtLoad": True, "KeepAlive": True,
            "ThrottleInterval": 10, "ProcessType": "Background", "LowPriorityIO": True,
            "StandardOutPath": str(app / "bridge.log"), "StandardErrorPath": str(app / "bridge-error.log")}


def run_command(arguments, *, check=True):
    """Bound local subprocesses and keep raw command output out of setup logs."""
    try:
        return subprocess.run(arguments, check=check, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        raise SetupError("Local helper build or LaunchAgent operation failed; no secret details were logged.") from None


def install(plan):
    """Build first, then pair and start the per-user agent. Caller supplies --install."""
    if sys.platform != "darwin":
        raise SetupError("The Now Playing helper and LaunchAgent require macOS.")
    app, agent = plan["app"], plan["agent"]
    private_directory(app)
    safe_path(agent.parent).mkdir(parents=True, mode=0o700, exist_ok=True)
    # A failed build leaves the existing pairing and agent intact.
    with tempfile.TemporaryDirectory(prefix=".setup-", dir=app) as staging:
        staging = Path(staging)
        for name, data in plan["sources"].items():
            atomic_write(staging / name, data)
        helper = staging / "now_playing.dylib"
        run_command([plan["python"], str(staging / "bridge.py"), "--build-helper", "--helper", str(helper)])
        helper_data = read_regular(helper, limit=16777216)
        for name, data in plan["sources"].items():
            atomic_write(app / name, data)
        atomic_write(app / "now_playing.dylib", helper_data)
    paths = (plan["config_path"], plan["receiver_path"], agent)
    previous = {path: read_regular(path, private=path != plan["receiver_path"], limit=16384)
                if path.exists() else None for path in paths}
    domain = "gui/" + str(os.getuid())
    stopped = False
    try:
        for key, path in (("host", plan["config_path"]), ("receiver", plan["receiver_path"])):
            data = (json.dumps(plan[key], separators=(",", ":")) + "\n").encode("utf-8")
            atomic_write(path, data, host_file=key == "host")
        atomic_write(agent, plistlib.dumps(launch_agent(plan)))
        for name in ("bridge.log", "bridge-error.log"):
            path = app / name
            if not path.exists():
                atomic_write(path, b"")
            else:
                read_regular(path, private=True, limit=16777216)
        run_command(["/bin/launchctl", "bootout", domain + "/" + LABEL], check=False)
        stopped = True
        run_command(["/bin/launchctl", "bootstrap", domain, str(agent)])
    except Exception:
        for path, data in previous.items():
            if data is None:
                if safe_path(path).exists():
                    path.unlink()
            else:
                atomic_write(path, data, host_file=path != plan["receiver_path"])
        if stopped and previous[agent] is not None:
            run_command(["/bin/launchctl", "bootstrap", domain, str(agent)], check=False)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--volume", type=Path, required=True,
                        help="native USB CircuitPython volume, usually /Volumes/CIRCUITPY")
    parser.add_argument("--host", required=True, help="controller's existing Wi-Fi IPv4 address")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--host-ip", help="optionally accept datagrams only from this Mac IPv4 address")
    parser.add_argument("--install", action="store_true", help="pair the controller and install/start the login agent")
    args = parser.parse_args(argv)
    try:
        plan = prepare_setup(args.volume, args.host, port=args.port, host_ip=args.host_ip)
        if args.install:
            install(plan)
            print("Bridge paired and login agent installed. Verify fresh metadata on the controller display.")
        else:
            print("Setup validated; no files changed. Add --install to pair and start the login agent.")
        return 0
    except (SetupError, OSError):
        # OSError paths can contain private profile names, but never dump contents.
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, SetupError) else "Cannot complete local setup; check file access."
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

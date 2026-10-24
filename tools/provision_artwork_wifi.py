"""One-time local USB Wi-Fi provisioning; never needed during playback.

Enter credentials on CrowPanel and press Save. This utility receives them only
over its physical UART, validates them, updates the connected controller and
then permits CrowPanel to join the same AP. Credentials are never printed.
"""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import secrets
import time

ROOT = next(parent for parent in Path(__file__).resolve().parents
            if (parent / "firmware/circuitpython/main.py").is_file())
SOURCE = ROOT / "firmware/circuitpython/lib/remote/artwork_wifi.py"
SPEC = importlib.util.spec_from_file_location("artwork_wifi", SOURCE)
wifi_profile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wifi_profile)


class SetupError(RuntimeError):
    """A fixed local diagnostic that never contains received profile data."""


def decode_profile(line, nonce):
    """Return a validated profile only for this exact USB setup session."""
    prefix = ("BMWIFI_PROFILE:" + nonce + ":").encode("ascii")
    if not line.startswith(prefix):
        return None
    encoded = line[len(prefix):].strip()
    if len(encoded) > 1024:
        raise ValueError("profile response too large")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > wifi_profile.MAX_PROFILE_BYTES:
            raise ValueError("profile too large")
        return wifi_profile.validate_profile(json.loads(raw))
    except Exception:
        raise ValueError("invalid USB profile response") from None


def private_write(path, data, host_file=True):
    """Write and read back private setup material without printing contents."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    if host_file:
        os.fchmod(fd, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    if path.read_bytes() != data:
        raise SetupError("private setup file verification failed")


class Lines:
    def __init__(self, port):
        self.port = port
        self.pending = bytearray()

    def read(self):
        """Bound a line buffer; callers never print profile response lines."""
        self.pending.extend(self.port.read(1024))
        if len(self.pending) > 8192:
            self.pending.clear()
            raise SetupError("USB setup response exceeded bounds")
        lines = []
        while b"\n" in self.pending:
            line, _, rest = self.pending.partition(b"\n")
            self.pending[:] = rest
            lines.append(bytes(line).rstrip(b"\r"))
        return lines


class Controller:
    def __init__(self, port):
        self.port = port
        self.stopped = False
        self.interrupt_sent = False

    def receive(self, seconds):
        end = time.monotonic() + seconds
        data = bytearray()
        while time.monotonic() < end:
            data.extend(self.port.read(4096))
        return bytes(data)

    def stop(self):
        self.interrupt_sent = True
        self.port.write(b"\x03")
        response = self.receive(2)
        if b"Press any key to enter the REPL" in response:
            self.port.write(b"\r")
            response += self.receive(1)
        if b">>>" not in response:
            raise SetupError("controller REPL not confirmed")
        self.stopped = True
        self.command("import supervisor; supervisor.runtime.autoreload = False")

    def command(self, text):
        self.port.write(text.encode("ascii") + b"\r\n")
        reply = self.receive(0.7)
        if b">>>" not in reply or b"Traceback" in reply:
            raise SetupError("controller setup command failed")

    def start(self, verify_wifi):
        self.command("import supervisor; supervisor.runtime.autoreload = True")
        self.port.write(b"\x04")
        self.stopped = False
        self.interrupt_sent = False
        end = time.monotonic() + 25
        received = bytearray()
        while time.monotonic() < end:
            received.extend(self.port.read(4096))
            if b"Traceback" in received or b"[FATAL]" in received:
                raise SetupError("controller startup failed")
            wifi_ok = b"[NET] artwork Wi-Fi ready channel=" in received
            running = b"[REMOTE] Now Playing return channel enabled" in received
            if running and (wifi_ok or not verify_wifi):
                return
        raise SetupError("controller artwork Wi-Fi startup not confirmed")

    def recover_if_interrupted(self):
        """Bounded recovery even when the initial REPL prompt was delayed."""
        if not self.interrupt_sent:
            return
        if not self.stopped:
            self.port.write(b"\r")
            self.stopped = b">>>" in self.receive(1)
        if self.stopped:
            self.start(verify_wifi=False)
        else:
            # This is only the USB Python console, never the BM83 UART.
            self.port.write(b"\x04")
            self.interrupt_sent = False
            self.receive(3)


def provision(args):
    import serial
    from serial.tools import list_ports

    ports = list(list_ports.comports())
    units = [p for p in ports if (p.vid, p.pid) == (0x303A, 0x7003)
             and (args.controller_serial is None or p.serial_number == args.controller_serial)]
    crows = [p for p in ports if (p.vid, p.pid) == (0x1A86, 0x7523)
             and (args.crow_port is None or p.device == args.crow_port)]
    if len(units) != 1 or len(crows) != 1:
        raise SetupError("identify exactly one controller and CrowPanel USB port")
    volume = Path(args.volume)
    module_path = volume / "lib/remote/artwork_wifi.py"
    if not module_path.is_file() and not module_path.with_suffix(".mpy").is_file():
        raise SetupError("install artwork-capable controller firmware first")
    output = Path(args.output)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(output, 0o700)
    target = volume / ".artwork_wifi.json"
    previous = target.read_bytes() if target.exists() else None
    if previous is not None:
        private_write(output / "private-profile-before.json", previous)
    nonce = secrets.token_hex(16)
    crow = serial.Serial(port=None, baudrate=115200, timeout=0.1)
    crow.dtr = crow.rts = False
    crow.port = crows[0].device
    unit = serial.Serial(port=None, baudrate=115200, timeout=0.1)
    unit.dtr, unit.rts, unit.port = True, False, units[0].device
    controller = Controller(unit)
    changed = False
    success = False
    commit_sent = False
    try:
        crow.open()
        lines = Lines(crow)
        print("Enter Wi-Fi details on CrowPanel and press Save; credentials stay out of logs.", flush=True)
        end = time.monotonic() + 300
        next_request = 0
        profile = None
        while time.monotonic() < end and profile is None:
            if time.monotonic() >= next_request:
                crow.write(("BMWIFI_PROFILE:" + nonce + "\n").encode("ascii"))
                next_request = time.monotonic() + 1
            for line in lines.read():
                profile = decode_profile(line, nonce)
                if profile is not None:
                    break
        if profile is None:
            raise SetupError("no freshly saved CrowPanel profile received")
        data = json.dumps(profile, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(data) > wifi_profile.MAX_PROFILE_BYTES:
            raise SetupError("normalized Wi-Fi profile exceeds bounds")
        print("Profile validated. Updating the controller over local USB.", flush=True)
        unit.open()
        controller.stop()
        # Mark only after opening succeeds; a read-only volume remains intact.
        with target.open("wb") as handle:
            changed = True
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if target.read_bytes() != data:
            raise SetupError("controller profile read-back mismatch")
        controller.start(verify_wifi=True)
        print("Controller Wi-Fi verified. Checking the panel and audio-unit radio link.", flush=True)
        crow.reset_input_buffer()
        lines.pending.clear()
        crow.write(("BMWIFI_APPLY:" + nonce + "\n").encode("ascii"))
        end = time.monotonic() + 35
        connected = False
        peer_fresh = False
        while time.monotonic() < end:
            for line in lines.read():
                if line.startswith(("BMWIFI_STATUS:" + nonce + ":CONNECTED").encode("ascii")):
                    connected = True
                if line.startswith(("BMWIFI_STATUS:" + nonce + ":FAILED").encode("ascii")):
                    raise SetupError("CrowPanel Wi-Fi join failed")
                if connected and line.startswith(b"[playback]") and b"fresh=1" in line:
                    peer_fresh = True
            if connected and peer_fresh:
                break
        if not connected or not peer_fresh:
            raise SetupError("both Wi-Fi association and peer snapshots were not confirmed")
        print("Both devices are communicating on Wi-Fi. Saving the panel profile.", flush=True)
        # The panel is still trial-joined. Persist only after actual peer data
        # proves both radios share the access point/channel.
        commit_sent = True
        end = time.monotonic() + 8
        next_commit = 0
        while time.monotonic() < end and not success:
            if time.monotonic() >= next_commit:
                crow.write(("BMWIFI_COMMIT:" + nonce + "\n").encode("ascii"))
                next_commit = time.monotonic() + 1
            for line in lines.read():
                if line == ("BMWIFI_ACK:" + nonce + ":COMMITTED").encode("ascii"):
                    success = True
        if not success:
            raise SetupError("commit outcome unconfirmed")
        summary = {"success": True,
                   "controller_serial": units[0].serial_number, "crow_port": crows[0].device,
                   "credentials_logged": False, "runtime_host_helper": False}
        private_write(output / "provisioning.json", (json.dumps(summary, indent=2) + "\n").encode())
        print("Both devices joined the selected access point; artwork setup is complete.", flush=True)
    finally:
        try:
            if changed and not success and not commit_sent:
                crow.write(("BMWIFI_ABORT:" + nonce + "\n").encode("ascii"))
                if not controller.stopped:
                    controller.stop()
                if previous is None:
                    target.unlink(missing_ok=True)
                else:
                    private_write(target, previous, host_file=False)
                controller.start(verify_wifi=False)
                print("Setup did not complete; restored the controller's previous private profile.", flush=True)
            elif commit_sent and not success:
                # COMMIT may have arrived even if its ACK did not. Rolling
                # back only one device here would create a permanent mismatch.
                private_write(output / "provisioning.json", b'{"success":false,"commit_outcome":"unknown","controller_profile_retained":true}\n')
                print("Commit outcome is unconfirmed; the new controller profile was retained.", flush=True)
            if controller.interrupt_sent:
                controller.recover_if_interrupted()
        finally:
            if unit.is_open:
                unit.close()
            if crow.is_open:
                crow.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller-serial")
    parser.add_argument("--crow-port")
    parser.add_argument("--volume", default="/Volumes/CIRCUITPY")
    parser.add_argument("--output", required=True, help="new private local rollback directory")
    try:
        provision(parser.parse_args())
    except Exception as error:
        # Every locally raised error is generic; never print serial input or
        # the parsed profile, including in a traceback.
        detail = str(error) if isinstance(error, SetupError) else type(error).__name__
        print("Wi-Fi setup stopped: %s" % detail, flush=True)
        raise SystemExit(1)

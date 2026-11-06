"""Open the local BM83 Volume Remote on an authenticated remote request."""

import argparse
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import hmac
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from tempfile import NamedTemporaryFile
import time


PORT = 45837
POLL = b"BWL1\x01"
RESPONSE = b"BWL1\x02"
EMPTY = bytes(16)
FRAME_SIZE = 69
WINDOW_TITLE = "BM83 Volume Remote"
COMPANION = "bm83-windows-volume-host.py"
LAN_RANGES = tuple(map(ipaddress.ip_network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))


def local_profile(name):
    local = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    return Path(local) / "BM83VolumeRemote" / name


def poll_frame(key, nonce, acknowledged):
    body = POLL + nonce + acknowledged
    return body + hmac.digest(key, body, "sha256")


def response_event(key, nonce, frame):
    if len(frame) != FRAME_SIZE or frame[:21] != RESPONSE + nonce:
        return None
    body, tag = frame[:-32], frame[-32:]
    if not hmac.compare_digest(tag, hmac.digest(key, body, "sha256")):
        return None
    return body[21:]


def lan_address(host, port=PORT):
    for entry in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM):
        address = entry[4][0]
        if any(ipaddress.ip_address(address) in subnet for subnet in LAN_RANGES):
            return address
    raise OSError("BM83 endpoint did not resolve to a private LAN address")


def endpoint(value, port):
    key = bytes.fromhex(value["key"])
    if len(key) != 32 or key == bytes(32):
        raise ValueError("Expected a 32-byte launch key")
    host = value["host"]
    if not isinstance(host, str) or not host or len(host) > 253:
        raise ValueError("Expected a BM83 LAN host")
    if type(port) is not int or not 0 < port < 65536:
        raise ValueError("Expected a BM83 LAN port")
    return host, port, key


@dataclass(frozen=True)
class Config:
    host: str
    key: bytes
    pythonw: Path
    app: Path
    controller: tuple | None = None

    @classmethod
    def read(cls, path):
        raw = json.loads(path.read_text(encoding="utf-8"))
        host, _, key = endpoint(raw, PORT)
        controller = raw.get("controller")
        if controller is not None:
            controller = endpoint(controller, controller["port"])
        pythonw, app = Path(raw["pythonw"]), Path(raw["app"])
        for file, name in ((pythonw, "pythonw.exe"), (app, COMPANION)):
            if not file.is_absolute() or len(file.drive) != 2 or file.name.casefold() != name or not file.is_file():
                raise ValueError("Expected the local BM83 app and Python window launcher")
        return cls(host, key, pythonw, app, controller)


def window_for(pythonw):
    user = ctypes.windll.user32
    kernel = ctypes.windll.kernel32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    user.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user.IsWindowVisible.argtypes = (wintypes.HWND,)
    user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    )
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    matching = None

    @callback_type
    def inspect(hwnd, _):
        nonlocal matching
        caption = ctypes.create_unicode_buffer(128)
        if not user.IsWindowVisible(hwnd) or not user.GetWindowTextW(hwnd, caption, len(caption)):
            return True
        if caption.value != WINDOW_TITLE:
            return True
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            try:
                image = ctypes.create_unicode_buffer(32768)
                count = wintypes.DWORD(len(image))
                if kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(count)):
                    if Path(image.value) == pythonw:
                        matching = hwnd
                        return False
            finally:
                kernel.CloseHandle(handle)
        return True

    user.EnumWindows(inspect, 0)
    return matching


def open_window(config):
    hwnd = window_for(config.pythonw)
    if hwnd is None:
        subprocess.Popen([str(config.pythonw), str(config.app)], cwd=config.app.parent)
        deadline = time.monotonic() + 4
        while hwnd is None and time.monotonic() < deadline:
            time.sleep(0.1)
            hwnd = window_for(config.pythonw)
    if hwnd is None:
        return False
    user = ctypes.windll.user32
    user.IsIconic.argtypes = (wintypes.HWND,)
    user.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user.FlashWindow.argtypes = (wintypes.HWND, wintypes.BOOL)
    if user.IsIconic(hwnd):
        user.ShowWindow(hwnd, 9)  # SW_RESTORE
    if not user.SetForegroundWindow(hwnd):
        user.FlashWindow(hwnd, True)
    return True


class Receiver:
    def __init__(self, key, open_app):
        self.key = key
        self.open_app = open_app
        self.attempted = EMPTY
        self.acknowledged = EMPTY

    def poll(self, wire):
        nonce = secrets.token_bytes(16)
        wire.send(poll_frame(self.key, nonce, self.acknowledged))
        event = response_event(self.key, nonce, wire.recv(FRAME_SIZE + 1))
        if event and event != EMPTY and event != self.attempted:
            self.attempted = event
            if self.open_app():
                self.acknowledged = event
                print("Confirmed BM83 Volume Remote window", flush=True)


class Link:
    def __init__(self, host, port, key, open_app):
        self.host, self.port = host, port
        self.receiver = Receiver(key, open_app)
        self.wire = None

    def poll(self):
        try:
            if self.wire is None:
                self.wire = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.wire.connect((lan_address(self.host, self.port), self.port))
                self.wire.settimeout(0.45)
            self.receiver.poll(self.wire)
        except OSError:
            if self.wire is not None:
                self.wire.close()
                self.wire = None


def single_receiver():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel.CreateMutexW(None, False, r"Local\BM83CrowPanelVolumeAppReceiver")
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle(handle)
        return None
    return handle  # retained by the process for its lifetime


def configure(config_path, companion):
    import serial
    from serial.tools import list_ports

    pythonw = Path(sys.executable).with_name("pythonw.exe").resolve(strict=True)
    companion = companion.resolve(strict=True)
    if companion.name.casefold() != COMPANION or not companion.is_file():
        raise ValueError("Select the local BM83 Volume Remote entry point")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    ports = [port.device for port in list_ports.comports() if (port.vid, port.pid) == (0x1A86, 0x7523)]
    if len(ports) != 1:
        raise OSError("Connect exactly one CrowPanel CH340 USB port")
    existing = Config.read(config_path) if config_path.exists() else None
    key = existing.key if existing else secrets.token_bytes(32)

    def request(wire, line):
        wire.reset_input_buffer()
        wire.write(line + b"\n")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            reply = wire.read_until(b"\n", 256).strip()
            if reply.startswith((b"BMWIN_READY:", b"BMWIN_ERROR:")):
                return reply.decode("ascii")
        raise OSError("CrowPanel did not answer the Windows launch setup request")

    with serial.Serial(baudrate=115200, timeout=0.2, write_timeout=1) as wire:
        wire.dtr = wire.rts = False
        wire.port = ports[0]
        wire.open()
        reply = request(wire, b"BMWIN_INFO")
        if reply == "BMWIN_ERROR:NO_KEY" or reply.startswith("BMWIN_READY:"):
            reply = request(wire, b"BMWIN_KEY:" + key.hex().encode("ascii"))
        deadline = time.monotonic() + 25
        while reply == "BMWIN_READY:0.0.0.0" and time.monotonic() < deadline:
            time.sleep(1)
            reply = request(wire, b"BMWIN_INFO")
    if not reply.startswith("BMWIN_READY:"):
        raise OSError("CrowPanel could not store the launch key")
    address = ipaddress.IPv4Address(reply.split(":", 1)[1])
    if not any(address in subnet for subnet in LAN_RANGES):
        raise OSError("Join the CrowPanel to its saved local Wi-Fi network and rerun setup")
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=config_path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        values = dict(host=str(address), key=key.hex(), pythonw=str(pythonw), app=str(companion))
        if existing and existing.controller is not None:
            host, port, controller_key = existing.controller
            values["controller"] = dict(host=host, port=port, key=controller_key.hex())
        json.dump(values, stream)
    try:
        temporary.replace(config_path)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"CrowPanel launch configured for {address}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=local_profile(".bm83_windows_receiver.json"))
    parser.add_argument("--configure", type=Path, nargs="?", const=Path(__file__).with_name(COMPANION),
                        metavar="COMPANION_APP", help="Set up or refresh over CrowPanel USB")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("The launch receiver requires a signed-in Windows desktop session")
    if args.configure is not None:
        configure(args.config, args.configure)
        return
    mutex = single_receiver()
    if not mutex:
        return
    config = Config.read(args.config)

    def open_app():
        return open_window(config)

    links = [Link(config.host, PORT, config.key, open_app)]
    if config.controller is not None:
        links.append(Link(*config.controller, open_app))
    while True:
        for link in links:
            link.poll()
        time.sleep(0.8)


if __name__ == "__main__":
    main()

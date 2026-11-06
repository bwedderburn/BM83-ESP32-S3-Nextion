"""Inspect and disconnect the BM83 controller's BLE volume link."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from importlib.util import module_from_spec, spec_from_file_location
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import sys
import time

from windows_volume_app_receiver import WINDOW_TITLE, lan_address, local_profile


BADGE_APP = Path(__file__).resolve().parents[1] / "addons/universe-badge/apps/bm83_remote"
MAX_PROFILE_BYTES = 1024
DEFAULT_PORT = 8767


def load_badge_protocol():
    # The on-device model imports protocol as a top-level module. Bind the
    # known adjacent source for that import without replacing another client.
    def load(name):
        spec = spec_from_file_location("bm83_companion_" + name, BADGE_APP / (name + ".py"))
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    protocol = load("protocol")
    previous = sys.modules.get("protocol")
    sys.modules["protocol"] = protocol
    try:
        return protocol, load("models")
    finally:
        if previous is None:
            del sys.modules["protocol"]
        else:
            sys.modules["protocol"] = previous


protocol, models = load_badge_protocol()


class Failure(Exception):
    """Bounded, secret-free operator message."""


class VolumeHost:
    def __init__(self, wire, key, *, clock=time.monotonic, sleep=time.sleep):
        self.wire = wire
        self.key = key
        self.clock = clock
        self.sleep = sleep
        self.unit = self.client = None
        self.seq = 0

    def close(self):
        self.wire.close()

    def exchange(self, message, match, timeout=0.75):
        # A retry sends identical authenticated bytes, never a new command seq.
        frame = protocol.encode(self.key, message)
        deadline = self.clock() + timeout
        for _ in range(3):
            if self.clock() >= deadline:
                break
            self.wire.send(frame)
            until = min(deadline, self.clock() + timeout / 3)
            while self.clock() < until:
                self.wire.settimeout(max(0.001, until - self.clock()))
                try:
                    reply = protocol.decode(self.key, self.wire.recv(1201))
                except TimeoutError:
                    break
                if self.clock() > until:
                    break
                if reply is not None and match(reply):
                    return reply
        return None

    def command(self, token, timeout=0.75):
        if token not in ("STATUS", "BLE_PAUSE"):
            raise Failure("This tool only sends Status and Disconnect commands.")
        if self.unit is None:
            nonce = secrets.token_hex(8)

            def welcome(reply):
                return (reply.get("type") == "welcome" and reply.get("nonce") == nonce
                        and protocol.hex_text(reply.get("unit"), 8) and reply["unit"] != "00000000"
                        and protocol.uint(reply.get("client")) and reply["client"] != 0)

            reply = self.exchange({"v": 1, "type": "hello", "nonce": nonce}, welcome)
            if reply is None:
                raise Failure("No authenticated reply from the BM83 unit. Check the saved Wi-Fi connection.")
            self.unit, self.client, self.seq = reply["unit"], reply["client"], 0
        if self.seq == 0xffffffff:
            raise Failure("BMW1 sequence exhausted. Close and reopen this tool.")
        self.seq += 1

        def matching(reply):
            if (not protocol.uint(reply.get("client")) or reply["client"] != self.client
                    or not protocol.uint(reply.get("seq")) or reply["seq"] != self.seq):
                return False
            return (reply.get("type") == "rehello"
                    or (reply.get("type") == "state" and reply.get("unit") == self.unit))

        message = {"v": 1, "type": "cmd", "unit": self.unit, "client": self.client,
                   "seq": self.seq, "token": token}
        reply = self.exchange(message, matching, timeout)
        if reply is None:
            return None
        if reply["type"] == "rehello":
            self.unit = self.client = None
            raise Failure("BM83 restarted or retired this session. Use Status to establish a fresh session.")
        if reply.get("denied") is True:
            raise Failure("The BM83 unit denied the request.")
        ble = reply.get("ble")
        if (type(reply.get("dup")) is not bool or "ble" not in reply
                or (ble is not None and not models.valid_ble(ble))):
            raise Failure("The unit returned an invalid BLE status.")
        return reply

    def status(self):
        reply = self.command("STATUS")
        if reply is None or reply.get("ble") is None:
            raise Failure("No fresh authenticated volume-remote status. Try Status again.")
        return reply["ble"]

    def disconnect(self):
        before = self.status()
        if before["mode"] == 2:
            return "Already disconnected. The unit reports PAUSED with its HID link and advertising off."
        if before["mode"] != 0 or not before["flags"] & 2:
            raise Failure("The volume remote is busy or unavailable. Check Status before retrying.")
        # The first state reply precedes dispatch. A lost ACK can still mean the
        # PAUSE applied, so observe fresh STATUS and never issue another PAUSE.
        request = (self.client, self.seq + 1)
        self.command("BLE_PAUSE")
        deadline = self.clock() + 5
        remaining = deadline - self.clock()
        while remaining > 0:
            reply = self.command("STATUS", min(0.75, remaining))
            ble = reply.get("ble") if reply else None
            if ble is not None:
                if ble["session"] != before["session"]:
                    raise Failure("The controller restarted before Disconnect could be verified.")
                fresh = models.newer(ble["sequence"], before["sequence"])
                origin = (ble.get("req_client"), ble.get("req_seq"))
                if fresh and origin == request:
                    if ble["mode"] == 2 and ble["flags"] == 2 and ble["error"] == 0:
                        return "Disconnected. The unit confirms PAUSED with its HID link and advertising off."
                    if ble["mode"] == 3:
                        raise Failure(f"The unit could not confirm Disconnect (BLE error {ble['error']}).")
            self.sleep(0.15)
            remaining = deadline - self.clock()
        raise Failure("Disconnect could not be verified. Use Status to check the unit before trying again.")


def load_profile(path):
    """Read the explicit user-local BMW1 profile without exposing its data."""
    with path.open("rb") as stream:
        raw = stream.read(MAX_PROFILE_BYTES + 1)
    if len(raw) > MAX_PROFILE_BYTES:
        raise ValueError("Invalid companion profile size")
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict) or type(value.get("v")) is not int or value["v"] != 1:
        raise ValueError("Unsupported companion profile")
    host = value.get("host")
    port = value.get("port", DEFAULT_PORT)
    if not isinstance(host, str) or not host or len(host) > 253 or not protocol.uint(port, 65535) or port < 1024:
        raise ValueError("Invalid controller endpoint")
    key = protocol.key_bytes(value.get("key"))
    if not any(key):
        raise ValueError("Invalid controller key")
    client_ip = value.get("client_ip")
    if client_ip is not None:
        if not isinstance(client_ip, str):
            raise ValueError("Invalid Windows IPv4 constraint")
        client_ip = str(ipaddress.IPv4Address(client_ip))
    return host, port, key, client_ip


def live_client(path):
    try:
        host, port, key, client_ip = load_profile(path)
    except (OSError, ValueError):
        raise Failure("The private Windows companion profile is missing or invalid.") from None
    wire = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        wire.connect((lan_address(host, port), port))
        if client_ip is not None and wire.getsockname()[0] != client_ip:
            raise Failure("The controller profile does not authorize this Windows network source.")
        return VolumeHost(wire, key)
    except Exception:
        wire.close()
        raise


def describe(ble):
    mode = ("Enabled", "Disconnecting", "Paused", "Controller error")[ble["mode"]]
    hid = "connected" if ble["flags"] & 4 else "disconnected"
    adv = "on" if ble["flags"] & 8 else "off"
    error = f" Controller error {ble['error']}." if ble["error"] else ""
    return f"Controller status: {mode}. HID {hid}. Advertising {adv}.{error}"


class MockWire:
    """In-memory BMW1 exchange with throwaway credentials and no sockets."""

    key = bytes(range(32))

    def __init__(self):
        self.reply = None
        self.sequence = 0
        self.request = (None, None)

    def send(self, frame):
        value = protocol.decode(self.key, frame)
        identity = {"v": 1, "unit": "a1b2c3d4", "client": 1}
        if value["type"] == "hello":
            self.reply = {**identity, "type": "welcome", "nonce": value["nonce"]}
            return
        self.sequence += 1
        ble = None
        if value["token"] == "BLE_PAUSE":
            self.request = (value["client"], value["seq"])
        else:
            paused = self.request[0] is not None
            ble = {"session": 1, "sequence": self.sequence, "mode": 2 if paused else 0,
                   "flags": 2 if paused else 7, "error": 0,
                   "req_client": self.request[0], "req_seq": self.request[1]}
        self.reply = {**identity, "type": "state", "seq": value["seq"], "dup": False, "ble": ble}

    def recv(self, _size):
        return protocol.encode(self.key, self.reply)

    def settimeout(self, _seconds):
        pass

    def close(self):
        pass


def mock_client():
    return VolumeHost(MockWire(), MockWire.key)


def show_window(factory, mock=False):
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(WINDOW_TITLE + (" (offline demo)" if mock else ""))
    root.minsize(415, 195)
    root.columnconfigure(0, weight=1)
    pane = ttk.Frame(root, padding=18)
    pane.grid(sticky="nsew")
    ttk.Label(pane, text="BM83 Volume Remote", font=("Segoe UI", 15, "bold")).grid(sticky="w", columnspan=2)
    ttk.Label(pane, text="Disconnect pauses the unit’s active BLE volume remote.\n"
                         "Use Volume hosts on the CrowPanel or badge to reconnect.",
              justify="left").grid(sticky="w", columnspan=2, pady=(8, 12))
    text = tk.StringVar(value="Click Status to check the controller.")
    ttk.Label(pane, textvariable=text, wraplength=380, justify="left").grid(
        row=3, column=0, columnspan=2, sticky="w", pady=(12, 0))
    executor = ThreadPoolExecutor(max_workers=1)
    client = pending = None

    def action(disconnect):
        nonlocal client
        try:
            if client is None:
                client = factory()
            return client.disconnect() if disconnect else describe(client.status())
        except Failure as exc:
            return str(exc)
        except OSError:
            return "Network request failed. Use Status to check the unit before retrying."

    def finish():
        nonlocal pending
        if not pending.done():
            root.after(75, finish)
            return
        try:
            text.set(pending.result())
        except Exception:
            text.set("Unexpected error. Use Status to check the unit before retrying.")
        pending = None
        for button in buttons:
            button.state(["!disabled"])

    def start(disconnect):
        nonlocal pending
        if pending is None:
            for button in buttons:
                button.state(["disabled"])
            text.set("Checking controller…" if not disconnect else "Verifying Disconnect…")
            pending = executor.submit(action, disconnect)
            root.after(75, finish)

    def close():
        if pending is None:
            if client is not None:
                client.close()
            executor.shutdown(wait=False)
            root.destroy()

    buttons = (ttk.Button(pane, text="Status", command=lambda: start(False)),
               ttk.Button(pane, text="Disconnect", command=lambda: start(True)))
    for index, button in enumerate(buttons):
        button.grid(row=2, column=index, sticky="w", padx=(0, 8))
    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=local_profile(".bm83_windows_companion.json"),
                        help="Owner-private BMW1 connection profile")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="Exercise the protocol with no network or hardware")
    modes.add_argument("--mock-window", action="store_true", help="Open the Windows UI without a live network")
    args = parser.parse_args()
    if args.dry_run:
        client = mock_client()
        print(describe(client.status()))
        print(client.disconnect())
        print(describe(client.status()))
    else:
        show_window(mock_client if args.mock_window else lambda: live_client(args.config), args.mock_window)


if __name__ == "__main__":
    main()

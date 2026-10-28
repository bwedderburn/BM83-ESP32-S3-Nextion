"""One in-flight BMW1 transaction, bounded input queue and UDP retries."""

import binascii
import errno
import os
import socket

from protocol import TOKENS, decode, encode, hex_text, uint
from models import Playback, BleControl, valid_np

WOULD_BLOCK = (errno.EAGAIN, 11, 10035)


class Remote:
    def __init__(self, host, port, key):
        self.peer = (host, port)
        self.key = key
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setblocking(False)
        self.playback = Playback()
        self.ble = BleControl()
        self.unit = self.client = None
        self.seq = 0
        self.nonce = None
        self.pending = None
        self.queue = []
        self.last_poll = -1000
        self.feedback = "Waiting for audio unit"
        self.held_volume = None
        self.volume_queue = []
        self.rehello_count = 0

    def queue_command(self, command):
        if command not in TOKENS:
            raise ValueError("Unknown remote control")
        if command.endswith("_R"):
            base = command[:-2]
            for gesture in reversed(self.volume_queue):
                if gesture["command"] == base and not gesture["released"]:
                    gesture["released"] = True
                    return True
            # A release without a local press is still a useful stop request,
            # but repeated stop requests must not create an unbounded queue.
            if not any(gesture["command"] == base for gesture in self.volume_queue):
                self.volume_queue.append({"command": base, "pressed": True, "released": True})
            return True
        if len(self.queue) + len(self.volume_queue) >= 8:
            self.feedback = "Busy - try again"
            return False
        if command.endswith("_P"):
            self.volume_queue.append({"command": command[:-2], "pressed": False, "released": False})
        else:
            self.queue.append(command)
        return True

    def volume(self, command):
        if self.held_volume == command:
            return
        self.release_volume()
        if self.queue_command(command + "_P"):
            self.held_volume = command

    def release_volume(self):
        if self.held_volume:
            self.queue_command(self.held_volume + "_R")
            self.held_volume = None

    def _send(self, now):
        p = self.pending
        try:
            self.socket.sendto(p["wire"], self.peer)
        except OSError as error:
            self.feedback = "UDP unavailable: %s" % error
        p["sent"] = now
        p["attempts"] += 1

    def _hello(self, now):
        self.nonce = binascii.hexlify(os.urandom(8)).decode()
        message = {"v": 1, "type": "hello", "nonce": self.nonce}
        self.pending = {"wire": encode(self.key, message), "command": None,
                        "attempts": 0, "sent": now}
        self._send(now)

    def _command(self, command, now):
        self.seq += 1
        message = {"v": 1, "type": "cmd", "unit": self.unit, "client": self.client,
                   "seq": self.seq, "token": command}
        self.pending = {"wire": encode(self.key, message), "command": command,
                        "attempts": 0, "sent": now}
        if command in ("BLE_PAUSE", "BLE_ENABLE"):
            if not self.ble.begin(command == "BLE_PAUSE", self.client, self.seq, now):
                self.pending = None
                self.feedback = "Fresh BLE status required"
                return
        self._send(now)
        if command != "STATUS":
            self.feedback = "%s: sent" % command

    def _receive(self, now):
        for _ in range(4):
            try:
                wire, peer = self.socket.recvfrom(1201)
            except OSError as error:
                if error.args[0] in WOULD_BLOCK:
                    return
                self.feedback = "UDP receive error: %s" % error
                return
            if peer != self.peer:
                continue
            m = decode(self.key, wire)
            if not m or not self.pending:
                continue
            kind = m.get("type")
            if (kind == "welcome" and self.pending["command"] is None
                    and m.get("nonce") == self.nonce and hex_text(m.get("unit"), 8)
                    and m["unit"] != "00000000" and uint(m.get("client")) and m["client"] > 0):
                self.unit, self.client, self.seq = m["unit"], m["client"], 0
                self.pending = None
                if "unconfirmed" not in self.feedback.lower():
                    self.feedback = "Audio unit authenticated"
            elif (m.get("client") == self.client and type(m.get("client")) is int
                  and m.get("seq") == self.seq and type(m.get("seq")) is int
                  and self.pending["command"] is not None):
                if kind == "rehello":
                    command = self.pending["command"]
                    self.pending = None
                    self.unit = self.client = None
                    self.rehello_count += 1
                    if command == "STATUS" and self.rehello_count <= 3:
                        self.queue.insert(0, command)
                    elif command and command.endswith("_R") and self.rehello_count <= 3:
                        self.volume_queue.insert(0, {"command": command[:-2], "pressed": True, "released": True})
                    elif command == "NET_RETRY":
                        self.feedback = "NET_RETRY: reconnecting/request sent; delivery unconfirmed"
                    elif command:
                        self.feedback = "%s: unconfirmed after unit/client restart" % command
                    if command and command.startswith("BLE_") and self.ble.result == "Waiting":
                        self.ble.result = "Unconfirmed (restarted)"
                    self.last_poll = now - 1000
                elif (kind == "state" and m.get("unit") == self.unit
                      and type(m.get("dup")) is bool and valid_np(m.get("np"))):
                    command = self.pending["command"]
                    self.playback.accept(m["np"], now)
                    self.ble.accept(m.get("ble"), now)
                    if command != "STATUS":
                        self.feedback = "%s: sent (reply)" % command
                    self.pending = None
                    self.rehello_count = 0

    def step(self, now):
        self._receive(now)
        self.ble.tick(now)
        if self.pending:
            if self.pending.get("stalled"):
                if now - self.pending["sent"] >= 1000:
                    self._send(now)
                return
            if now - self.pending["sent"] < 150:
                return
            if self.pending["attempts"] < 4:
                self._send(now)
                return
            command = self.pending["command"]
            self.feedback = "%s: no reply" % (command or "Audio unit")
            if command and command.endswith("_R"):
                # Do not advance to a new sequence: that could make the server
                # discard the only release capable of stopping held volume.
                self.pending["stalled"] = True
                self.pending["sent"] = now
                self.last_poll = now
                return
            self.pending = None
            if command is None:
                self.last_poll = now
                return
        if not self.unit:
            if now - self.last_poll >= 1000:
                self.last_poll = now
                self._hello(now)
            return
        if self.seq >= 0xffffffff:
            self.unit = self.client = None
            self._hello(now)
            return
        # Each accepted press owns its release. A second press of the same
        # button cannot overtake the first gesture's release, even in flight.
        command = None
        if self.volume_queue:
            gesture = self.volume_queue[0]
            if not gesture["pressed"]:
                gesture["pressed"] = True
                command = gesture["command"] + "_P"
            elif gesture["released"]:
                self.volume_queue.pop(0)
                command = gesture["command"] + "_R"
        if command is not None:
            pass
        elif self.queue:
            command = self.queue.pop(0)
        elif now - self.last_poll >= 1000:
            self.last_poll = now
            command = "STATUS"
        else:
            return
        self._command(command, now)

    def close(self, now, sleep):
        self.release_volume()
        self.queue = []
        # HOME cleanup is the only bounded wait: finish the release transaction.
        for _ in range(30):
            self.step(now)
            if not self.queue and not self.volume_queue and not self.pending:
                break
            sleep(50)
            now += 50
        if self.volume_queue or (self.pending and self.pending["command"]
                                and self.pending["command"].endswith("_R")):
            print("BM83: volume release unconfirmed; check audio unit")
        self.socket.close()

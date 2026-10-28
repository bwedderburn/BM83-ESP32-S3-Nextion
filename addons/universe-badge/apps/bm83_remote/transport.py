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
        self.release_due = []
        self.rehello_count = 0

    def queue_command(self, token):
        if token not in TOKENS:
            raise ValueError("Unknown remote control")
        if token.endswith("_R"):
            if token not in self.release_due:
                self.release_due.append(token)
            return True
        if len(self.queue) >= 8:
            self.feedback = "Busy - try again"
            return False
        self.queue.append(token)
        return True

    def volume(self, token):
        if self.held_volume == token:
            return
        self.release_volume()
        if self.queue_command(token + "_P"):
            self.held_volume = token

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
        self.pending = {"wire": encode(self.key, message), "token": None,
                        "attempts": 0, "sent": now}
        self._send(now)

    def _command(self, token, now):
        self.seq += 1
        message = {"v": 1, "type": "cmd", "unit": self.unit, "client": self.client,
                   "seq": self.seq, "token": token}
        self.pending = {"wire": encode(self.key, message), "token": token,
                        "attempts": 0, "sent": now}
        if token in ("BLE_PAUSE", "BLE_ENABLE"):
            if not self.ble.begin(token == "BLE_PAUSE", self.client, self.seq, now):
                self.pending = None
                self.feedback = "Fresh BLE status required"
                return
        self._send(now)
        if token != "STATUS":
            self.feedback = "%s: sent" % token

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
            if (kind == "welcome" and self.pending["token"] is None
                    and m.get("nonce") == self.nonce and hex_text(m.get("unit"), 8)
                    and m["unit"] != "00000000" and uint(m.get("client")) and m["client"] > 0):
                self.unit, self.client, self.seq = m["unit"], m["client"], 0
                self.pending = None
                if "unconfirmed" not in self.feedback.lower():
                    self.feedback = "Audio unit authenticated"
            elif (m.get("client") == self.client and type(m.get("client")) is int
                  and m.get("seq") == self.seq and type(m.get("seq")) is int
                  and self.pending["token"] is not None):
                if kind == "rehello":
                    token = self.pending["token"]
                    self.pending = None
                    self.unit = self.client = None
                    self.rehello_count += 1
                    if token == "STATUS" and self.rehello_count <= 3:
                        self.queue.insert(0, token)
                    elif token and token.endswith("_R") and self.rehello_count <= 3:
                        self.queue.insert(0, token)
                    elif token == "NET_RETRY":
                        self.feedback = "NET_RETRY: reconnecting/request sent; delivery unconfirmed"
                    elif token:
                        self.feedback = "%s: unconfirmed after unit/client restart" % token
                    if token and token.startswith("BLE_") and self.ble.result == "Waiting":
                        self.ble.result = "Unconfirmed (restarted)"
                    self.last_poll = now - 1000
                elif (kind == "state" and m.get("unit") == self.unit
                      and type(m.get("dup")) is bool and valid_np(m.get("np"))):
                    token = self.pending["token"]
                    self.playback.accept(m["np"], now)
                    self.ble.accept(m.get("ble"), now)
                    if token != "STATUS":
                        self.feedback = "%s: sent (reply)" % token
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
            token = self.pending["token"]
            self.feedback = "%s: no reply" % (token or "Audio unit")
            if token and token.endswith("_R"):
                # Do not advance to a new sequence: that could make the server
                # discard the only release capable of stopping held volume.
                self.pending["stalled"] = True
                self.pending["sent"] = now
                self.last_poll = now
                return
            self.pending = None
            if token is None:
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
        # A quick tap still sends its press before its paired release. Once the
        # press is sent, releases outrank all unrelated commands.
        queued_press = None
        if self.release_due:
            paired = self.release_due[0].replace("_R", "_P")
            if paired in self.queue:
                queued_press = paired
        if queued_press:
            self.queue.remove(queued_press)
            token = queued_press
        elif self.release_due:
            token = self.release_due.pop(0)
        elif self.queue and self.queue[0].endswith("_P"):
            token = self.queue.pop(0)
        elif self.queue:
            token = self.queue.pop(0)
        elif now - self.last_poll >= 1000:
            self.last_poll = now
            token = "STATUS"
        else:
            return
        self._command(token, now)

    def close(self, now, sleep):
        self.release_volume()
        self.queue = [t for t in self.queue if t.endswith("_P")]
        # HOME cleanup is the only bounded wait: finish the release transaction.
        for _ in range(30):
            self.step(now)
            if not self.queue and not self.release_due and not self.pending:
                break
            sleep(50)
            now += 50
        if self.release_due or (self.pending and self.pending["token"]
                                and self.pending["token"].endswith("_R")):
            print("BM83: volume release unconfirmed; check audio unit")
        self.socket.close()

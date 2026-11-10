"""Authenticated badge actions against the controller's existing BLE policy."""

import binascii
import os

from blehid.host_policy import valid_id
from utils.ticks import ticks_ms, ticks_recent
from .badge_remote import hmac_digest


WINDOWS_KEY_PATH = "/.badge_windows_launch.key"
WIN_POLL = b"BWL1\x01"
WIN_REPLY = b"BWL1\x02"
WIN_FRAME_SIZE = 69
EMPTY_EVENT = bytes(16)
HOST_MODES = {"HOST_DISCONNECT": "PAUSED", "HOST_SELECT": "AUTO", "HOST_ENROLL": "ENROLL"}
FLAGS = ("ready", "advertising", "connected", "encrypted", "bonded", "hid_ready",
         "persisted", "last_disconnect_local", "filter_ready")


def windows_key(path=WINDOWS_KEY_PATH):
    try:
        with open(path, "rb") as stream:
            value = stream.read(65).strip()
        key = binascii.unhexlify(value) if len(value) == 64 else None
        return key if key != bytes(32) else None
    except (OSError, ValueError):
        return None


class WindowsLaunch:
    """One pending event, delivered only in response to a keyed Windows poll."""

    def __init__(self, key, clock=ticks_ms, random=os.urandom):
        self.key, self.clock, self.random = key, clock, random
        self.seen = self.nonce = self.started = None
        self.client = self.seq = None
        self.event = EMPTY_EVENT
        self.result = "OFFLINE"

    def observe(self, now):
        if self.result == "PENDING" and not ticks_recent(now, self.started, 10000):
            self.event, self.result = EMPTY_EVENT, "UNCONFIRMED"
        ready = ticks_recent(now, self.seen, 5000) and self.result != "PENDING"
        result = self.result if self.client is not None else "READY" if ready else "OFFLINE"
        return ready, result

    def request(self, client, seq):
        now = self.clock()
        ready, _ = self.observe(now)
        if not ready:
            return False
        self.event = self.random(16)
        if self.event == EMPTY_EVENT:
            return False
        self.started, self.client, self.seq, self.result = now, client, seq, "PENDING"
        return True

    def poll(self, wire, now):
        if self.key is None or len(wire) != WIN_FRAME_SIZE or wire[:5] != WIN_POLL:
            return None
        body, given = wire[:37], wire[37:]
        expected = hmac_digest(self.key, body)
        difference = 0
        for a, b in zip(given, expected):
            difference |= a ^ b
        nonce = wire[5:21]
        if difference or nonce == self.nonce:
            return None
        self.observe(now)
        self.nonce, self.seen = nonce, now
        if self.event != EMPTY_EVENT and self.event == wire[21:37]:
            self.event, self.result = EMPTY_EVENT, "OPENED"
        body = WIN_REPLY + nonce + self.event
        return body + hmac_digest(self.key, body)


class BadgeHosts:
    def __init__(self, ble, on_policy, launch=None):
        self.ble, self.on_policy = ble, on_policy
        self.launch = WindowsLaunch(windows_key()) if launch is None else launch
        self.origin = self.operation = None

    def supersede(self):
        self.origin = self.operation = None

    def note_tick(self):
        if self.origin is not None and self.operation is None:
            self.operation = self.ble.snapshot_host_status().get("request_operation_id", 0)

    def request(self, token, value, client, seq):
        """Return (accepted policy intent, error), with BLE work deferred to tick."""
        if token == "HOST_STATUS":  # nosec B105 - command name, not a credential
            return False, None
        if token == "HOST_OPEN_WINDOWS":  # nosec B105 - command name, not a credential
            return False, None if self.launch.request(client, seq) else "Windows launcher unavailable"
        status = self.ble.snapshot_host_status()
        if status.get("version") != 1 or not status.get("ready"):
            return False, "Volume hosts unavailable"
        target = None
        generation, peers = status.get("peer_generation"), status.get("peers", ())
        coherent = generation is not None and generation == status.get("bond_generation")
        if token == "HOST_SELECT":  # nosec B105 - command name, not a credential
            target, supplied = value.get("target"), value.get("generation")
            if (not valid_id(target) or type(supplied) is not int or not coherent or supplied != generation
                    or not any(peer["id"] == target and peer["resumable"] for peer in peers)):
                return False, "Refresh saved hosts"
        if token == "HOST_ENROLL" and (not coherent or len(peers) >= 8):  # nosec B105 - command name, not a credential
            return False, "No available pairing slot"
        if not self.ble.request_host_policy(HOST_MODES[token], target, 60):
            return False, "Volume host request refused"
        self.origin = (client, seq)
        self.operation = None
        self.on_policy()
        return True, None

    def snapshot(self):
        status = self.ble.snapshot_host_status()
        supported = status.get("version") == 1
        generation = status.get("bond_generation", 0)
        peers = None
        if supported and status.get("peer_generation") == generation:
            peers = [[p["id"], p["alias"], p["resumable"]] for p in status.get("peers", ())]
        operation = status.get("request_operation_id", 0)
        if self.operation is not None and operation != self.operation:
            self.supersede()
        client, seq = self.origin or (None, None)
        owner_error = status.get("owner_error", 0)
        ready, launch = self.launch.observe(self.launch.clock())
        return {
            "state": status.get("state", "ERROR") if supported else "UNSUPPORTED",
            "requested": status.get("requested_mode"), "applied": status.get("applied_mode"),
            "flags": sum(1 << bit for bit, name in enumerate(FLAGS) if status.get(name) is True),
            "target": status.get("target_id"), "connected": status.get("connected_id"),
            "generation": generation, "operation": status.get("operation_id", 0),
            "request_operation": operation if client is not None else 0,
            "req_client": client, "req_seq": seq, "remaining": status.get("enroll_remaining_s", 0),
            "error_domain": "POLICY" if owner_error else status.get("error_domain", "NONE"),
            "error_code": owner_error or status.get("error_code", 0), "peers": peers,
            "launch": launch, "launch_ready": ready,
            "launch_client": self.launch.client, "launch_seq": self.launch.seq,
        }

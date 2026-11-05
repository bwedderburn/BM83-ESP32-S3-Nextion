"""BHC1 commands and bounded BHP1 observations; no secrets, native calls or RF.

BLS2 remains exactly 21 bytes. Integers use big endian and the BMS2 CRC16.
Each BHP1 packet has <=8 fragments of <=64 bytes, expires at the receiver
after 2 seconds, and is scoped to a controller boot session and packet number.
For a new client, LIST's generation field is a one-use recent STATUS packet
sequence. Only observed successful native TX callbacks for every STATUS
fragment issue that challenge; a queued send alone never establishes a client.
"""
from blehid.host_policy import valid_alias, valid_id
from utils.ticks import ticks_add, ticks_diff
from .now_playing import crc16

MAX_PAYLOAD = 360
FRAGMENT_PAYLOAD = 45
PERIOD_MS = 1000
LIST_PERIOD_MS = 4000  # Refresh before the consumer's 5-second freshness limit.
CHALLENGE_MS = 3000
MODES = ("PAUSED", "AUTO", "ENROLL")
STATES = ("PAUSED", "SWITCHING", "WAITING", "ENROLLING", "CONNECTED", "ERROR", "UNSUPPORTED")
DOMAINS = ("NONE", "POLICY", "NVS", "NIMBLE", "SECURITY")


def number(value, size=4):
    return (int(value) & ((1 << (8 * size))-1)).to_bytes(size, "big")


def identity(value):
    if value is None:
        return b"\0" * 8
    if not valid_id(value):
        raise ValueError("Opaque host identity")
    return bytes(int(value[i:i+2], 16) for i in range(0, 16, 2))


def enum(value, vocabulary, default=255):
    return vocabulary.index(value) if value in vocabulary else default


def decode_command(frame):
    if not isinstance(frame, (bytes, bytearray)) or not 32 <= len(frame) <= 56:
        return None
    frame = bytes(frame)
    if (frame[:4] != b"BHC1" or len(frame) != 32 + frame[29] or frame[29] > 24
            or crc16(frame[:-2]) != int.from_bytes(frame[-2:], "big") or frame[16] > 4
            or not int.from_bytes(frame[4:8], "big") or not int.from_bytes(frame[8:12], "big")):
        return None
    target = "".join("%02x" % b for b in frame[21:29])
    target = None if target == "0000000000000000" else target
    payload, opcode = frame[30:-2], frame[16]
    if (opcode in (0, 1, 3) and target is not None or opcode in (2, 4) and not valid_id(target)
            or opcode in (0, 1, 2) and payload
            or opcode == 3 and (len(payload) != 2 or not 5 <= int.from_bytes(payload, "big") <= 120)):
        return None
    if opcode == 4:
        try:
            alias = payload.decode("utf8")
        except UnicodeError:
            return None
        if not valid_alias(alias):
            return None
    return {"controller_session": int.from_bytes(frame[4:8], "big"),
            "client_session": int.from_bytes(frame[8:12], "big"),
            "sequence": int.from_bytes(frame[12:16], "big"), "opcode": opcode,
            "bond_generation": int.from_bytes(frame[17:21], "big"), "target": target,
            "payload": payload}


def encode_command(controller, client, sequence, opcode, generation=0, target=None, payload=b""):
    body = (b"BHC1" + number(controller) + number(client) + number(sequence) + bytes((opcode,))
            + number(generation) + identity(target) + bytes((len(payload),)) + payload)
    frame = body + number(crc16(body), 2)
    if decode_command(frame) is None:
        raise ValueError("Host command fields")
    return frame


def fragments(payload, session, sequence, kind):
    if not payload or len(payload) > MAX_PAYLOAD or kind not in (1, 2) or not session:
        raise ValueError("Host packet bound")
    count = (len(payload) + FRAGMENT_PAYLOAD - 1) // FRAGMENT_PAYLOAD
    result = []
    for index in range(count):
        part = payload[index * FRAGMENT_PAYLOAD:(index + 1) * FRAGMENT_PAYLOAD]
        body = (b"BHP1" + number(session) + number(sequence) + bytes((kind, index, count))
                + number(len(payload), 2) + part)
        result.append(body + number(crc16(body), 2))
    return tuple(result)


def decode_fragment(frame):
    if not isinstance(frame, (bytes, bytearray)) or not 20 <= len(frame) <= 64:
        return None
    frame = bytes(frame)
    if frame[:4] != b"BHP1" or crc16(frame[:-2]) != int.from_bytes(frame[-2:], "big"):
        return None
    session, sequence = int.from_bytes(frame[4:8], "big"), int.from_bytes(frame[8:12], "big")
    kind, index, count, total = frame[12], frame[13], frame[14], int.from_bytes(frame[15:17], "big")
    if (not session or kind not in (1, 2) or not 1 <= count <= 8 or not 0 <= index < count
            or not 1 <= total <= MAX_PAYLOAD or count != (total+44)//45
            or len(frame)-19 != min(45, total-index*45)):
        return None
    return session, sequence, kind, index, count, total, frame[17:-2]


def status_payload(status, client=0, request=0, result=0, error=0, policy_request=False):
    version = 1 if status.get("version") == 1 else 0
    flags = 0
    for field, bit in (("ready", 1), ("advertising", 2), ("connected", 4), ("encrypted", 8),
                       ("bonded", 16), ("hid_ready", 32), ("persisted", 64),
                       ("last_disconnect_local", 128), ("filter_ready", 256)):
        if status.get(field) is True:
            flags |= bit
    operation = status.get("request_operation_id", 0) if policy_request else status.get("operation_id", 0)
    domain = enum(status.get("error_domain"), DOMAINS, 1)
    state = enum(status.get("state"), STATES, 5 if version else 6)
    body = (bytes((version, result, error)) + number(client) + number(request) + number(operation)
            + number(status.get("policy_generation", 0)) + number(status.get("bond_generation", 0))
            + number(status.get("connection_generation", 0))
            + bytes((enum(status.get("requested_mode"), MODES), enum(status.get("applied_mode"), MODES), state))
            + number(flags, 2) + bytes((domain,)) + number(status.get("error_code", 0))
            + number(status.get("last_disconnect_reason", 0)) + number(status.get("last_disconnect_generation", 0))
            + number(status.get("enroll_remaining_s", 0), 2)
            + identity(status.get("target_id")) + identity(status.get("connected_id")))
    if len(body) != 63:
        raise ValueError("Host status length")
    return body


def list_payload(status):
    peers, generation = status.get("peers", ()), status.get("peer_generation")
    if len(peers) > 8 or generation is None or generation != status.get("bond_generation"):
        raise ValueError("Coherent host list unavailable")
    body = bytes((1,)) + number(generation) + bytes((len(peers),))
    for peer in peers:
        if peer["generation"] != generation or not valid_alias(peer["alias"]):
            raise ValueError("Stale host alias/list")
        flags = sum(bit for field, bit in (("our_sec", 1), ("peer_sec", 2), ("cccd", 4),
                                           ("resumable", 8), ("connected", 16)) if peer[field])
        alias = peer["alias"].encode("utf8")
        body += identity(peer["id"]) + bytes((flags, len(alias))) + alias
    return body


class HostPolicyPublisher:
    def __init__(self, remote, ble, session, clock):
        self.remote, self.ble, self.session, self.clock = remote, ble, session, clock
        self.client = self.request = self.result = self.error = 0
        self._last_request = None
        self._retired_clients = []
        self._policy_request = False
        self._alias_pending = False
        self._sequence = 0
        self._frames, self._index = (), 0
        self._started = self._next_status = self._next_list = None
        self._list_dirty = False
        self._last_generation = None
        self._echo_suppressed = False
        self._established = False
        self._handshake = None
        self._challenges = []  # (fully successful STATUS packet sequence, conservative issue time, used)
        self._awaiting = None
        self._packet_kind = self._packet_sequence = 0
        self._last_queued_at = None
        self._rejection = None

    def _observe_completion(self):
        """Only successful native callbacks for every fragment create a challenge."""
        if self._awaiting is None:
            return True
        observe = getattr(self.remote, "tx_completion", None)
        completion = observe(self._awaiting) if observe is not None else False
        if completion is None:
            return False
        self._awaiting = None
        if completion is not True:
            self._frames = ()
            return True
        if self._index == len(self._frames):
            now = self.clock()
            if self._packet_kind == 1:
                self._challenges = [c for c in self._challenges if 0 <= ticks_diff(now, c[1]) <= CHALLENGE_MS]
                if 0 <= ticks_diff(now, self._last_queued_at) <= CHALLENGE_MS:
                    self._challenges.append((self._packet_sequence, self._last_queued_at, False))
                    self._challenges = self._challenges[-4:]
            self._frames = ()
        return True

    def _consume_challenge(self, sequence):
        now = self.clock()
        self._challenges = [c for c in self._challenges if 0 <= ticks_diff(now, c[1]) <= CHALLENGE_MS]
        for index, (saved, issued, used) in enumerate(self._challenges):
            if saved == sequence and not used:
                self._challenges[index] = (saved, issued, True)
                return True
        return False

    def _reject_handshake(self, client, request, error=11):
        # This response does not change the active client's policy correlation.
        self._rejection = (client, request, error)
        self._next_status = None

    def note_legacy_request(self):
        self._echo_suppressed = True
        self._policy_request = self._alias_pending = False
        self.result = self.error = 0
        self._next_status = None

    def snapshot(self):
        getter = getattr(self.ble, "snapshot_host_status", None)
        try:
            return getter() if getter is not None else {"version": 0, "ready": False}
        except Exception:
            return {"version": 0, "ready": False, "owner_error": 10}

    def request_host(self, command):
        """No BLE operations here; return True only for accepted policy intent."""
        if command is None:
            return False
        client, request = command["client_session"], command["sequence"]
        if command["controller_session"] != self.session:
            return False  # A stale controller packet cannot supersede a current result.
        self._observe_completion()
        status = self.snapshot()
        if not self._established or client != self.client:
            if (status.get("version") != 1 or not status.get("ready")
                    or status.get("peer_generation") is None
                    or status.get("peer_generation") != status.get("bond_generation")
                    or command["opcode"] != 0 or not self._consume_challenge(command["bond_generation"])):
                self._reject_handshake(client, request, 1 if status.get("version") != 1 else 11)
                return False
            if self._established:
                self._retired_clients = [c for c in self._retired_clients if c != self.client]
                self._retired_clients.append(self.client)
                self._retired_clients = self._retired_clients[-8:]
            self._retired_clients = [c for c in self._retired_clients if c != client]
            self._last_request = None
            self._established = True
            self._handshake = (client, request, command["bond_generation"])
        elif self._handshake == (client, request, command["bond_generation"]) and command["opcode"] == 0:
            if self._last_request == request:
                self._list_dirty, self._next_status = True, None
            return False  # Idempotent exact registration retry; never replaces a newer operation.
        if self._last_request is not None and not 0 < ((request-self._last_request) & 0xFFFFFFFF) < 0x80000000:
            return False  # Retransmission/replay is idempotent; retain the original result.
        self.client, self.request, self._last_request = client, request, request
        self._rejection = None
        self._echo_suppressed = False
        self.result, self.error, self._policy_request, self._alias_pending = 2, 0, False, False
        self._next_status = None
        if status.get("version") != 1:
            self.error = 1
            return False
        try:
            return self._request_action(command, status)
        except Exception:
            # A host-control failure must not stop the media and UART loop.
            self.result, self.error = 2, 10
            self._policy_request = self._alias_pending = False
            return False

    def _request_action(self, command, status):
        opcode, target = command["opcode"], command["target"]
        peers = status.get("peers", ())
        if opcode in (2, 4):
            if not status.get("ready"):
                self.error = 10
                return False
            if (status.get("peer_generation") != status.get("bond_generation")
                    or command["bond_generation"] != status.get("bond_generation")):
                self.error = 4
                return False
            # CircuitPython's next() accepts no default argument.
            peer = None
            for candidate in peers:
                if candidate["id"] == target:
                    peer = candidate
                    break
            if peer is None or opcode == 2 and not peer["resumable"]:
                self.error = 5
                return False
        if opcode == 0:
            self.result, self._list_dirty = 4, True
            return False
        if opcode == 4:
            okay = self.ble.request_host_alias(target, command["payload"].decode("utf8"))
            self._alias_pending = bool(okay)
            self._policy_request = bool(okay)  # Alias also has a native operation identity.
        else:
            mode = {1: "PAUSED", 2: "AUTO", 3: "ENROLL"}[opcode]
            timeout = int.from_bytes(command["payload"], "big") if opcode == 3 else 60
            okay = self.ble.request_host_policy(mode, target, timeout)
            self._policy_request = bool(okay)
        self.result, self.error = (1, 0) if okay else (2, 6)
        return bool(okay and opcode in (1, 2, 3))

    def tick(self):
        sender = getattr(self.remote, "send_host_policy_frame", None)
        if sender is None:
            return False
        if not self._observe_completion():
            return False
        now, status = self.clock(), self.snapshot()
        if self.result == 1 and status.get("owner_error"):
            self.result, self.error = 2, status["owner_error"]
        if self._alias_pending and status.get("alias_complete"):
            self._alias_pending = False
            if not status.get("owner_error"):
                self.result, self._list_dirty, self._next_status = 3, True, None
        generation = status.get("peer_generation")
        if generation != self._last_generation:
            self._last_generation, self._list_dirty = generation, True
        if self._frames and ticks_diff(now, self._started) >= 2000:
            self._frames = ()
        if not self._frames:
            if self._next_status is None or ticks_diff(now, self._next_status) >= 0:
                if self._rejection is not None:
                    client, request, error = self._rejection
                    self._rejection = None
                    result, policy_request = 2, False
                else:
                    client, request = (0, 0) if self._echo_suppressed else (self.client, self.request)
                    result, error, policy_request = self.result, self.error or status.get("owner_error", 0), self._policy_request
                payload, kind = status_payload(status, client, request, result, error, policy_request), 1
                self._next_status = ticks_add(now, PERIOD_MS)
            elif (status.get("version") == 1 and generation is not None
                  and (self._list_dirty or self._next_list is None or ticks_diff(now, self._next_list) >= 0)):
                payload, kind = list_payload(status), 2
                self._list_dirty, self._next_list = False, ticks_add(now, LIST_PERIOD_MS)
            else:
                return False
            self._sequence = (self._sequence + 1) & 0xFFFFFFFF
            self._frames, self._index, self._started = fragments(payload, self.session, self._sequence, kind), 0, now
            self._packet_kind, self._packet_sequence = kind, self._sequence
        if not sender(self._frames[self._index]):
            self._frames = ()
            return False
        self._index += 1
        self._awaiting = getattr(self.remote, "last_tx_ticket", None)
        self._last_queued_at = now
        if self._awaiting is None:
            self._frames = ()  # An unobservable enqueue is never an issued handshake challenge.
        return True

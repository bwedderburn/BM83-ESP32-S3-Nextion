"""Validated playback snapshots and independently fresh BLE confirmation."""

from protocol import hex_text, uint


def newer(candidate, baseline):
    return 0 < ((candidate - baseline) & 0xffffffff) < 0x80000000


def elapsed(now, then):
    return (now - then) & 0xffffffff


def clamp_setting_index(index, count):
    return max(0, min(index, count - 1)) if count > 0 else 0


def valid_np(value):
    if not isinstance(value, dict):
        return False
    for name in ("power_on", "connected", "aux", "clock_advancing"):
        if type(value.get(name)) is not bool:
            return False
    if not uint(value.get("play_status"), 255) or value["play_status"] not in (0, 1, 2, 3, 4, 255):
        return False
    if not uint(value.get("eq_index"), 255):
        return False
    for name in ("duration_ms", "position_ms", "position_age_ms"):
        if name not in value or (value[name] is not None
                                 and not uint(value[name], 0xfffffffe)):
            return False
    return all(isinstance(value.get(name), str) and len(value[name]) <= limit
               for name, limit in (("title", 96), ("artist", 96), ("album", 96), ("eq", 48)))


SOURCE_LABELS = {"avrcp": "via AVRCP", "mac": "via Mac Wi-Fi"}


def source_label(value):
    # Optional np["src"] names the receiver's proven text origin; never guess one.
    src = value.get("src") if isinstance(value, dict) else None
    return SOURCE_LABELS.get(src, "") if isinstance(src, str) else ""


def valid_ble(value):
    if not isinstance(value, dict):
        return False
    if not all(uint(value.get(k)) for k in ("session", "sequence")):
        return False
    mode, flags, error = value.get("mode"), value.get("flags"), value.get("error")
    if not uint(mode, 3) or not uint(flags, 15) or not uint(error, 7):
        return False
    if ((mode == 0 and (not flags & 1 or error))
            or (mode == 1 and (flags & 1 or error))
            or (mode == 2 and (flags != 2 or error))
            or (mode == 3 and not error)):
        return False
    return all(value.get(k) is None or uint(value[k]) for k in ("req_client", "req_seq"))


class Playback:
    def __init__(self):
        self.state = None
        self.received = 0
        self.paused_position = None

    def accept(self, value, now):
        if not valid_np(value):
            return False
        old = self.state
        boundary = (not self.fresh(now) or old["play_status"] != 2
                    or value["play_status"] != 2
                    or any(old[k] != value[k] for k in ("power_on", "connected", "aux"))
                    or any(old[k] and old[k] != value[k] for k in ("title", "artist", "album")))
        valid = (value["power_on"] and value["connected"] and not value["aux"]
                 and value["position_ms"] is not None
                 and value["position_age_ms"] is not None and value["position_age_ms"] <= 5000)
        if boundary or not valid:
            self.paused_position = None
        if value["play_status"] == 2 and valid and self.paused_position is None:
            self.paused_position = value["position_ms"]
        self.state, self.received = value, now
        return True

    def fresh(self, now):
        return self.state is not None and elapsed(now, self.received) < 6000

    def position(self, now):
        s = self.state
        if (not self.fresh(now) or not s["power_on"] or not s["connected"]
                or s["aux"] or s["position_ms"] is None or s["position_age_ms"] is None):
            return None
        age = s["position_age_ms"] + elapsed(now, self.received)
        if age > 5000:
            return None
        position = self.paused_position if s["play_status"] == 2 else s["position_ms"]
        if position is None:
            return None
        if s["play_status"] == 1 and s["clock_advancing"]:
            position += age
        return min(position, s["duration_ms"]) if s["duration_ms"] is not None else position


class BleControl:
    def __init__(self):
        self.state = None
        self.received = 0
        self.retired = []
        self.result = ""
        self.request = None

    def fresh(self, now):
        return self.state is not None and elapsed(now, self.received) < 3000

    def available(self, now):
        return (self.result != "Waiting" and self.fresh(now)
                and self.state["flags"] & 2 and self.state["mode"] != 1)

    def begin(self, pause, client, seq, now):
        if not self.available(now):
            return False
        self.request = (pause, client, seq, self.state["session"], self.state["sequence"], now)
        self.result = "Waiting"
        return True

    def accept(self, value, now):
        if not valid_ble(value) or value["session"] in self.retired:
            return
        if self.state:
            if value["session"] == self.state["session"]:
                if not newer(value["sequence"], self.state["sequence"]):
                    return
            else:
                self.retired = (self.retired + [self.state["session"]])[-8:]
        self.state, self.received = value, now

    def tick(self, now):
        if self.result != "Waiting":
            return
        pause, client, seq, session, baseline, started = self.request
        s = self.state
        if self.fresh(now):
            if s["session"] != session:
                self.result = "Unconfirmed (restarted)"
                return
            if newer(s["sequence"], baseline):
                if s.get("req_client") != client or s.get("req_seq") != seq:
                    self.result = "Unconfirmed (superseded)"
                    return
                if s["mode"] == 3:
                    self.result = "Failed"
                elif ((pause and s["mode"] == 2)
                      or (not pause and s["mode"] == 0 and s["flags"] & 2
                          and s["flags"] & 12)):
                    self.result = "Confirmed"
        if self.result == "Waiting" and elapsed(now, started) >= 6500:
            self.result = "Unconfirmed"


HOST_STATES = ("PAUSED", "SWITCHING", "WAITING", "ENROLLING", "CONNECTED", "ERROR", "UNSUPPORTED")
HOST_MODES = (None, "PAUSED", "AUTO", "ENROLL")
HOST_ERRORS = ("NONE", "POLICY", "NVS", "NIMBLE", "SECURITY")
LAUNCH_STATES = ("OFFLINE", "READY", "PENDING", "OPENED", "UNCONFIRMED")
HOST_TIMEOUTS = {"disconnect": 6500, "select": 30000, "enroll": 70000, "open_windows": 12000}
READY, ADVERTISING, CONNECTED, PERSISTED = 1, 2, 4, 64
HID_READY_FLAGS = CONNECTED | 8 | 16 | 32 | PERSISTED | 256


def _host_id(value):
    return hex_text(value, 16) and value != "0000000000000000"


def _valid_origin(value, client_field, sequence_field):
    client, seq = value.get(client_field), value.get(sequence_field)
    return (client is None and seq is None
            or uint(client) and client > 0 and uint(seq) and seq > 0)


def valid_hosts(value):
    if not isinstance(value, dict):
        return False
    if (value.get("state") not in HOST_STATES or value.get("requested") not in HOST_MODES
            or value.get("applied") not in HOST_MODES or value.get("error_domain") not in HOST_ERRORS
            or value.get("launch") not in LAUNCH_STATES or type(value.get("launch_ready")) is not bool
            or not uint(value.get("flags"), 511)
            or not uint(value.get("remaining"), 120)
            or not all(uint(value.get(key)) for key in ("generation", "operation", "request_operation"))
            or type(value.get("error_code")) is not int or not -0x80000000 <= value["error_code"] < 0x80000000
            or not _valid_origin(value, "req_client", "req_seq")
            or not _valid_origin(value, "launch_client", "launch_seq")
            or any(value.get(key) is not None and not _host_id(value[key]) for key in ("target", "connected"))):
        return False
    peers = value.get("peers")
    if peers is None:
        return True
    if not isinstance(peers, list) or len(peers) > 8:
        return False
    identities = []
    for peer in peers:
        if not isinstance(peer, list) or len(peer) != 3:
            return False
        identity, alias, resumable = peer
        if (not _host_id(identity) or identity in identities
                or type(resumable) is not bool or not isinstance(alias, str)
                or any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in alias)
                or len(alias.encode("utf8")) > 24):
            return False
        identities.append(identity)
    return True


class HostControls:
    """Report a host change only after observing its own native operation."""

    def __init__(self):
        self.state = None
        self.received = 0
        self.request = None
        self.result = ""
        self.observed = False

    @property
    def busy(self):
        return self.request is not None

    def fresh(self, now):
        return self.state is not None and elapsed(now, self.received) < 4000

    def unavailable(self, command, target, now):
        if not self.fresh(now):
            return "Waiting for fresh volume hosts"
        if self.busy and command != "disconnect":
            return "Volume host request in progress"
        s = self.state
        if command == "open_windows":
            return None if s["launch_ready"] and s["launch"] != "PENDING" else "Windows launcher unavailable"
        if s["state"] == "UNSUPPORTED":
            return "Update audio unit for volume hosts"
        if not s["flags"] & READY:
            return "Volume hosts are not ready"
        peers = s.get("peers")
        if command == "select" and (peers is None or not any(
                peer["id"] == target and peer["resumable"] for peer in peers)):
            return "Select an available saved host"
        if command == "enroll" and (peers is None or len(peers) >= 8):
            return "Saved hosts unavailable or full"
        return None

    def begin(self, command, target, client, seq, now):
        self.request = command, target, client, seq, self.state["operation"], now
        self.observed = False
        self.result = "Waiting for confirmation"

    def finish(self, text):
        self.request = None
        self.result = text

    def invalidate(self, text):
        self.state = None
        if self.busy:
            self.finish(text)

    def accept(self, value, now):
        if not valid_hosts(value):
            return False
        self.state = dict(value)
        rows = value.get("peers")
        self.state["peers"] = ([{"id": identity, "alias": alias, "resumable": resumable}
                                for identity, alias, resumable in rows] if rows is not None else None)
        self.received = now
        if not self.request:
            if self.result == "Volume hosts: no reply":
                self.result = ""
            return True
        command, target, client, seq, baseline, _ = self.request
        if command == "open_windows":
            own = value.get("launch_client") == client and value.get("launch_seq") == seq
            if own and value["launch"] == "OPENED":
                self.finish("BM83 Volume Remote opened")
            elif own and value["launch"] == "UNCONFIRMED":
                self.finish("Windows app launch unconfirmed")
            elif own:
                self.observed = True
            elif self.observed:
                self.finish("Windows app launch superseded")
            return True
        if value.get("req_client") != client or value.get("req_seq") != seq:
            if self.observed:
                self.finish("Volume host request superseded")
            return True
        self.observed = True
        operation, expected, flags = value["operation"], value["request_operation"], value["flags"]
        if not expected and value["error_domain"] == "POLICY" and value["error_code"]:
            self.finish("Volume host request failed")
            return True
        if operation == baseline or not operation or operation != expected:
            return True
        if value["state"] == "ERROR":
            self.finish("Volume host request failed")
            return True
        if not flags & READY:
            return True
        paused = (value["state"] == value["requested"] == value["applied"] == "PAUSED"
                  and flags & PERSISTED and not flags & (CONNECTED | ADVERTISING))
        connected = (value["state"] == "CONNECTED" and value["requested"] == value["applied"] == "AUTO"
                     and flags & HID_READY_FLAGS == HID_READY_FLAGS and value.get("target") is not None
                     and value["target"] == value.get("connected"))
        if command == "enroll" and paused and not value["remaining"] and (
                value["error_domain"] == "NONE" or (value["error_domain"], value["error_code"]) == ("POLICY", 6)):
            self.finish("Pairing window closed")
        elif value["error_domain"] != "NONE" or value["error_code"]:
            self.finish("Volume host request failed")
        elif command == "disconnect" and paused:
            self.finish("Disconnected. Pairings kept.")
        elif connected and (command == "enroll" or command == "select" and target == value["target"]):
            self.finish("Volume host connected")
        elif command == "select" and target == value.get("target") and value["state"] == "WAITING":
            self.result = "Waiting for saved host"
        elif command == "enroll" and value["state"] == "ENROLLING":
            self.result = "Pairing window open"
        return True

    def tick(self, now):
        if self.request and elapsed(now, self.request[-1]) >= HOST_TIMEOUTS[self.request[0]]:
            self.finish("Windows app launch unconfirmed" if self.request[0] == "open_windows"
                        else "Volume host result unconfirmed")


def display_text(text):
    substitutions = {0x2018: "'", 0x2019: "'", 0x201c: '"', 0x201d: '"',
                     0x2026: "...", 0x2212: "-"}
    # MicroPython's str case methods are ASCII-only, so both cases are listed.
    accents = "aaaaaaceeeeiiiinoooooouuuuyyAAAAAACEEEEIIIINOOOOOOUUUUYY"
    originals = "àáâãäåçèéêëìíîïñòóôõöøùúûüýÿÀÁÂÃÄÅÇÈÉÊËÌÍÎÏÑÒÓÔÕÖØÙÚÛÜÝŸ"
    ligatures = {"æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ß": "ss",
                 "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th"}
    out = ""
    for char in text.replace("o\u0308", "ö").replace("O\u0308", "Ö"):
        code = ord(char)
        if code > 127 and char in originals:
            out += accents[originals.index(char)]
        elif char in ligatures:
            out += ligatures[char]
        elif code in substitutions:
            out += substitutions[code]
        elif 0x2010 <= code <= 0x2014:
            out += "-"
        elif code in (0x200b, 0x2060, 0xfeff) or 0x300 <= code <= 0x36f:
            continue
        else:
            out += char if 32 <= code < 127 else (" " if char.isspace() else "?")
    return " ".join(out.split())


def clock_text(value):
    return "--:--" if value is None else "%d:%02d" % (value // 60000, value // 1000 % 60)

"""Validated playback snapshots and independently fresh BLE confirmation."""

from protocol import uint


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


def display_text(text):
    substitutions = {0x2018: "'", 0x2019: "'", 0x201c: '"', 0x201d: '"',
                     0x2026: "...", 0x2212: "-"}
    accents = "aaaaaaaceeeeiiiinoooooouuuuyy"
    originals = "àáâãäåçèéêëìíîïñòóôõöøùúûüýÿ"
    out = ""
    for char in text.replace("o\u0308", "ö").replace("O\u0308", "Ö"):
        code = ord(char)
        if char.lower() in originals:
            replacement = accents[originals.index(char.lower())]
            out += replacement.upper() if char.isupper() else replacement
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

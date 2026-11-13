"""Owner for the project native BLE policy API and explicit single-host Forget.

The adapter owns persistence, admission and enrollment deadlines. UI calls only
queue intent here; native calls happen from the UART-first main-loop tail.
"""

MODES = ("PAUSED", "AUTO", "ENROLL")
STATES = ("PAUSED", "SWITCHING", "WAITING", "ENROLLING", "CONNECTED", "ERROR")
DOMAINS = ("NONE", "POLICY", "NVS", "NIMBLE", "SECURITY")
BOOL_FIELDS = ("advertising", "connected", "encrypted", "bonded", "hid_ready",
               "persisted", "filter_ready", "last_disconnect_local")
GEN_FIELDS = ("operation_id", "policy_generation", "connection_generation",
              "bond_generation", "last_disconnect_generation", "subscription_generation")
DIAG_UINT_FIELDS = ("event_sequence", "connect_events", "connect_successes", "connect_failures",
                    "admission_attempts", "admissions", "refused_unsynced", "refused_store_guard",
                    "refused_conn_missing", "refused_resolver", "refused_policy", "refused_slot",
                    "refused_auto_identity", "refused_saved_identity", "refused_candidate",
                    "saved_irk_matches", "attach_failures", "refused_adapter_slot", "adapter_publications", "adv_complete_events",
                    "adv_complete_zero_reason", "adv_complete_nonzero_reason", "policy_stop_calls", "policy_stop_errors",
                    "vm_stop_requests", "vm_stop_active", "vm_stop_errors",
                    "last_connect_source", "last_refusal_reason", "last_adv_cause")
DIAG_INT_FIELDS = ("last_connect_status", "last_adv_complete_reason", "last_stop_result")


def valid_id(value):
    return (isinstance(value, str) and len(value) == 16
            and all(c in "0123456789abcdef" for c in value) and value != "0000000000000000")


def valid_alias(value):
    return (isinstance(value, str) and len(value.encode("utf8")) <= 24
            and all(ord(c) >= 32 and not 127 <= ord(c) <= 159 for c in value))


def u32(value):
    return type(value) is int and 0 <= value <= 0xFFFFFFFF


def checked_diagnostics(value):
    """Optional scalar-only native observations; no peer identity or key export.

    Missing, malformed or future diagnostics do not change policy readiness.
    The cache is populated from an existing host_status read, never an extra call.
    """
    if (not isinstance(value, dict) or type(value.get("diag_version")) is not int or value["diag_version"] != 1
            or any(not u32(value.get("diag_" + key)) for key in DIAG_UINT_FIELDS)
            or any(type(value.get("diag_" + key)) is not int
                   or not -0x80000000 <= value["diag_" + key] <= 0x7FFFFFFF for key in DIAG_INT_FIELDS)):
        return None
    result = {key: value["diag_" + key] for key in DIAG_UINT_FIELDS + DIAG_INT_FIELDS}
    result["version"] = 1
    return result


def checked_refusal_identity(value):
    """Optional public opaque identity, read from the same native status object.

    This is the last actual saved-host refusal, scoped to its recorded operation;
    a later window without a refusal does not relabel the older observation.
    """
    if type(value) is not dict or type(value.get("saved_refusal_version")) is not int or value["saved_refusal_version"] != 1:
        return None
    identity = value.get("last_saved_refusal_id")
    source = value.get("last_saved_refusal_source")
    operation = value.get("last_saved_refusal_operation_id")
    count = value.get("saved_refusal_window_count")
    if not u32(operation) or not u32(count):
        return None
    if identity is None:
        if source is not None or operation != 0 or count != 0:
            return None
    elif (type(identity) is not str or not valid_id(identity) or type(source) is not str
          or source not in ("descriptor", "software") or operation == 0 or count == 0):
        return None
    return dict(version=1, id=identity, source=source, operation_id=operation, window_count=count)


def clean_paused(status):
    return bool(status and status.get("state") == "PAUSED"
                and status.get("requested_mode") == status.get("applied_mode") == "PAUSED"
                and status.get("persisted") is True
                and status.get("connected") is False and status.get("advertising") is False
                and status.get("error_domain") == "NONE" and status.get("error_code") == 0)


def checked_status(value):
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("Native host status version")
    if (value.get("requested_mode") not in MODES or value.get("applied_mode") not in MODES
            or value.get("state") not in STATES or value.get("error_domain") not in DOMAINS
            or any(type(value.get(k)) is not bool for k in BOOL_FIELDS)
            or any(not u32(value.get(k)) for k in GEN_FIELDS)
            or type(value.get("error_code")) is not int or not -0x80000000 <= value["error_code"] <= 0xFFFFFFFF
            or not u32(value.get("last_disconnect_reason"))
            or type(value.get("enroll_remaining_s")) is not int or not 0 <= value["enroll_remaining_s"] <= 120
            or any(value.get(k) is not None and not valid_id(value[k]) for k in ("target_id", "connected_id"))):
        raise ValueError("Native host status fields")
    return {k: value[k] for k in ("version", "requested_mode", "applied_mode", "state",
            "target_id", "connected_id", "error_domain", "error_code", "last_disconnect_reason",
            "enroll_remaining_s") + BOOL_FIELDS + GEN_FIELDS}


def checked_peers(values, generation):
    if not isinstance(values, (tuple, list)) or len(values) > 8:
        raise ValueError("Native peer bound")
    peers, seen = [], set()
    for peer in values:
        if (not isinstance(peer, dict) or not valid_id(peer.get("id")) or peer["id"] in seen
                or not valid_alias(peer.get("alias")) or not u32(peer.get("generation")) or peer["generation"] != generation
                or any(type(peer.get(k)) is not bool for k in ("our_sec", "peer_sec", "cccd", "resumable", "connected"))):
            raise ValueError("Native peer snapshot")
        seen.add(peer["id"])
        peers.append({k: peer[k] for k in ("id", "alias", "generation", "our_sec", "peer_sec",
                                          "cccd", "resumable", "connected")})
    return tuple(peers)


class NativeHostPolicy:
    def __init__(self, adapter):
        self.adapter = adapter
        self.version = 0
        self.claimed = False
        self.status = None
        self.diagnostics = None
        self.refusal_identity = None
        self.peers = ()
        self.peer_generation = None
        self.pending = None
        self.expected_operation = None
        self.input_generation = 0
        self.owner_error = 0
        self._input_identity = None
        self._peer_connection_generation = None
        self._expected_alias = None
        self._expected_forget = None
        self._expected_clear = None
        self._input_blocked = False
        self._operation_failed = False
        try:
            version = adapter.host_policy_version
            self.claimed = True
            if (type(version) is int and version == 1 and callable(adapter.set_host_policy)
                    and callable(adapter.set_host_alias) and callable(adapter.arm_host_input)):
                self.version = 1
            else:
                self.owner_error = 1
        except AttributeError:
            pass  # Old runtime: honest unsupported capability, unchanged legacy path.
        except Exception:
            self.claimed = True
            self.owner_error = 10
        try:
            self.forget_supported = self.version == 1 and callable(getattr(adapter, "forget_host", None))
        except Exception:
            self.forget_supported = False
        try:
            self.clear_supported = self.version == 1 and callable(getattr(adapter, "clear_saved_hosts", None))
        except Exception:
            self.clear_supported = False

    def request(self, mode, target=None, timeout_s=60):
        if self.version != 1 or mode not in MODES:
            return False
        if mode == "AUTO" and target is not None and not valid_id(target):
            return False
        if mode != "AUTO" and target is not None:
            return False
        if mode == "ENROLL" and (type(timeout_s) is not int or not 5 <= timeout_s <= 120):
            return False
        self.pending = (mode, target, timeout_s)
        self._input_blocked = True
        self.expected_operation = None
        self._expected_alias = None
        self._expected_forget = None
        self._expected_clear = None
        self.owner_error = 0
        self._operation_failed = False
        self.input_generation = (self.input_generation + 1) & 0xFFFFFFFF
        return True

    def alias(self, identity, alias):
        if self.version != 1 or self.pending is not None or not valid_id(identity) or not valid_alias(alias):
            return False
        self.pending = ("ALIAS", identity, alias)
        self.expected_operation = None
        self._expected_alias = (identity, alias)
        self._expected_forget = None
        self._expected_clear = None
        self.owner_error = 0
        self._operation_failed = False
        return True

    def forget(self, identity, generation):
        if (not self.forget_supported or not self.ready() or not clean_paused(self.status)
                or not valid_id(identity) or not u32(generation)
                or generation != self.status["bond_generation"] or self.peer_generation != generation):
            return False
        target = None
        for peer in self.peers:
            if peer["id"] == identity:
                target = peer
                break
        if target is None or target["connected"]:
            return False
        self.pending = ("FORGET", identity, generation)
        self.expected_operation = None
        self._expected_forget = (identity, generation)
        self._expected_clear = None
        self._expected_alias = None
        self.owner_error = 0
        self._operation_failed = False
        return True

    def clear_saved_hosts(self, generation):
        """Explicit owner maintenance; no startup or UI path calls this automatically."""
        if (not self.clear_supported or not self.ready() or not clean_paused(self.status)
                or not u32(generation) or generation != self.status["bond_generation"]
                or self.peer_generation != generation or any(p["connected"] for p in self.peers)):
            return False
        self.pending = ("CLEAR_PEERS", None, generation)
        self.expected_operation = None
        self._expected_clear = generation
        self._expected_forget = None
        self._expected_alias = None
        self.owner_error = 0
        self._operation_failed = False
        return True

    def tick(self):
        if self.version != 1:
            return
        native_call = False
        try:
            if self.pending is not None:
                action, target, extra = self.pending
                self.pending = None  # Exactly one native enqueue/call, including failures.
                native_call = True
                if action == "ALIAS":
                    operation = self.adapter.set_host_alias(target, extra)
                    self.peer_generation = None
                elif action == "FORGET":
                    operation = self.adapter.forget_host(target, extra)
                    self.peer_generation = None
                elif action == "CLEAR_PEERS":
                    operation = self.adapter.clear_saved_hosts(extra)
                    self.peer_generation = None
                else:
                    operation = self.adapter.set_host_policy(action, target_id=target, timeout_s=extra)
                if not u32(operation) or operation == 0:
                    raise ValueError("Native operation identity")
                self.expected_operation = operation
                native_call = False
            status_raw = self.adapter.host_status
            status = checked_status(status_raw)
            if (self.peer_generation != status["bond_generation"]
                    or self._peer_connection_generation != status["connection_generation"]):
                peers = checked_peers(self.adapter.bonded_peers, status["bond_generation"])
                status_raw = self.adapter.host_status
                after = checked_status(status_raw)
                if (after["bond_generation"] != status["bond_generation"]
                        or after["connection_generation"] != status["connection_generation"]):
                    raise ValueError("Bond snapshot changed")
                self.peers, self.peer_generation, status = peers, status["bond_generation"], after
                self._peer_connection_generation = after["connection_generation"]
            # Disconnect/identity publication can change live membership without
            # changing either catalog generation. Never retain a connected bit
            # from that cached catalog or mutate an already returned snapshot.
            connected_id = status["connected_id"] if status["connected"] else None
            if any(p["connected"] != (p["id"] == connected_id) for p in self.peers):
                self.peers = tuple(dict(p, connected=p["id"] == connected_id) for p in self.peers)
            identity = (status["connection_generation"], status["subscription_generation"],
                        status["operation_id"], status["policy_generation"],
                        status["connected_id"], status["hid_ready"],
                        status["applied_mode"], status["state"])
            if identity != self._input_identity:
                self._input_identity = identity
                self.input_generation = (self.input_generation + 1) & 0xFFFFFFFF
            self.status = status
            self.diagnostics = checked_diagnostics(status_raw)
            self.refusal_identity = checked_refusal_identity(status_raw)
            self._input_blocked = False  # Main observes input_generation and cancels holds after this tick.
            if not self._operation_failed:
                self.owner_error = 0
        except Exception:
            self.diagnostics = None
            self.refusal_identity = None
            # Do not log native objects or retry admission/persistence operations.
            self._operation_failed = self._operation_failed or native_call
            self.owner_error = 7 if self._operation_failed else 10
            self.input_generation = (self.input_generation + 1) & 0xFFFFFFFF

    def ready(self):
        return (self.version == 1 and self.status is not None and not self.owner_error
                and self.pending is None and (self.expected_operation is None
                or self.status["operation_id"] == self.expected_operation))

    def allows_advertising(self):
        s = self.status
        return bool(self.ready() and s["filter_ready"] and not s["connected"]
                    and s["error_domain"] == "NONE" and not s["error_code"]
                    and s["requested_mode"] == s["applied_mode"]
                    and ((s["applied_mode"] == "AUTO" and s["state"] == "WAITING" and s["persisted"])
                         or (s["applied_mode"] == "ENROLL" and s["state"] == "ENROLLING")))

    def allows_input(self):
        s = self.status
        return bool(not self._input_blocked and self.ready() and s["state"] == "CONNECTED" and s["applied_mode"] == "AUTO"
                    and s["error_domain"] == "NONE" and not s["error_code"]
                    and s["requested_mode"] == "AUTO" and s["persisted"] and s["filter_ready"]
                    and s["connected"] and s["encrypted"] and s["bonded"] and s["hid_ready"]
                    and s["connected_id"] is not None and s["connected_id"] == s["target_id"])

    def validate_input(self):
        """Recheck native generations at send time, after asynchronous GAP callbacks."""
        if not self.allows_input():
            return False
        try:
            current = checked_status(self.adapter.host_status)
            fields = ("connection_generation", "subscription_generation", "policy_generation", "operation_id", "connected_id", "target_id",
                      "connected", "encrypted", "bonded", "hid_ready", "filter_ready", "requested_mode", "applied_mode",
                      "state", "persisted", "error_domain", "error_code")
            if any(current[k] != self.status[k] for k in fields):
                self.status = current
                self._input_blocked = True
                self.input_generation = (self.input_generation + 1) & 0xFFFFFFFF
                return False
            return True
        except Exception:
            self.owner_error = 10
            self._input_blocked = True
            self.input_generation = (self.input_generation + 1) & 0xFFFFFFFF
            return False

    def arm_input(self):
        """Bind this report batch to its validated origin, never a later reused handle."""
        if not self.allows_input():
            return False
        s = self.status
        try:
            armed = self.adapter.arm_host_input(s["operation_id"], s["policy_generation"],
                                                s["connection_generation"], s["subscription_generation"])
        except Exception:
            self.owner_error = 10
            armed = False
        if armed is not True:
            self._input_blocked = True
            self.input_generation = (self.input_generation + 1) & 0xFFFFFFFF
            return False
        return True  # Origin lease only; neither queued nor delivered input is acknowledged here.

    def snapshot(self):
        value = dict(self.status) if self.status is not None else {}
        value.update(version=self.version, ready=self.ready(), owner_error=self.owner_error,
                     request_operation_id=self.expected_operation or 0,
                     request_pending=self.pending is not None,
                     peers=self.peers, peer_generation=self.peer_generation,
                     forget_supported=self.forget_supported)
        value["forget_complete"] = bool(self._expected_forget is not None
            and self.expected_operation is not None and self.ready() and clean_paused(self.status)
            and self.status["operation_id"] == self.expected_operation
            and self.peer_generation == self.status["bond_generation"] != self._expected_forget[1]
            and self.status["target_id"] != self._expected_forget[0]
            and all(p["id"] != self._expected_forget[0] for p in self.peers))
        value["clear_complete"] = bool(self._expected_clear is not None
            and self.expected_operation is not None and self.ready() and clean_paused(self.status)
            and self.status["operation_id"] == self.expected_operation
            and self.peer_generation == self.status["bond_generation"] != self._expected_clear
            and self.status["target_id"] is None and not self.peers)
        value["alias_complete"] = bool(self._expected_alias is not None and self.ready()
            and self.status["persisted"] and self.status["state"] != "ERROR"
            and self.status["error_domain"] == "NONE" and not self.status["error_code"]
            and any(p["id"] == self._expected_alias[0]
            and p["alias"] == self._expected_alias[1] for p in self.peers))
        return value

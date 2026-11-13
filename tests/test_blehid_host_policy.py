"""Native-owner fault/race tests use the production Python owner and HID gate."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from blehid.ble import BleHid
from blehid.host_policy import (NativeHostPolicy, checked_peers, checked_diagnostics, checked_refusal_identity,
                               DIAG_UINT_FIELDS, DIAG_INT_FIELDS)

HOST = "0102030405060708"
OTHER = "1112131415161718"


def observed(**changes):
    value = dict(version=1, requested_mode="PAUSED", applied_mode="PAUSED", state="PAUSED",
                 target_id=HOST, connected_id=None, operation_id=1, policy_generation=1,
                 connection_generation=1, bond_generation=1, advertising=False, connected=False,
                 subscription_generation=1,
                 encrypted=False, bonded=False, hid_ready=False, persisted=True, filter_ready=False,
                 error_domain="NONE", error_code=0, last_disconnect_reason=0x213,
                 last_disconnect_generation=0, last_disconnect_local=False, enroll_remaining_s=0)
    value.update(changes)
    return value


def peer(identity=HOST, **changes):
    value = dict(id=identity, alias="", generation=1, our_sec=True, peer_sec=True, cccd=True,
                 resumable=True, connected=False)
    value.update(changes)
    return value


class Adapter:
    host_policy_version = 1
    def __init__(self):
        self.status = observed()
        self.peers = [peer(), peer(OTHER)]
        self.calls = []
        self.next_operation = 2
        self.fail = False
        self.race = False
        self.arm_calls = []
        self.arm_race = None
    @property
    def host_status(self): return deepcopy(self.status)
    @property
    def bonded_peers(self):
        peers = deepcopy(self.peers)
        if self.race: self.status["bond_generation"] += 1
        return tuple(peers)
    def set_host_policy(self, mode, target_id=None, timeout_s=60):
        self.calls.append((mode, target_id, timeout_s))
        if self.fail: raise RuntimeError("injected queue/NVS fault")
        operation = self.next_operation
        self.next_operation += 1
        return operation
    def set_host_alias(self, identity, alias):
        self.calls.append(("ALIAS", identity, alias))
        return self.next_operation
    def arm_host_input(self, operation, policy, connection, subscription):
        self.arm_calls.append((operation, policy, connection, subscription))
        if self.arm_race is not None: self.arm_race(self.status)
        return (operation, policy, connection, subscription) == tuple(self.status[k] for k in (
            "operation_id", "policy_generation", "connection_generation", "subscription_generation"))


def test_explicit_clear_saved_hosts_is_single_dispatch_and_requires_verified_empty_new_generation():
    class ClearAdapter(Adapter):
        def clear_saved_hosts(self, generation):
            self.calls.append(("CLEAR_PEERS", generation))
            if self.fail:
                raise RuntimeError("inert failure")
            return self.next_operation
    adapter = ClearAdapter()
    owner = NativeHostPolicy(adapter)
    owner.tick()
    assert owner.clear_supported and owner.clear_saved_hosts(1)
    owner.tick()
    assert adapter.calls == [("CLEAR_PEERS", 1)] and not owner.snapshot()["clear_complete"]
    owner.tick()
    assert adapter.calls == [("CLEAR_PEERS", 1)]
    adapter.status.update(operation_id=2, bond_generation=2, target_id=None)
    adapter.peers = []
    owner.tick()
    assert owner.snapshot()["clear_complete"] and owner.ready()
    assert not NativeHostPolicy(Adapter()).clear_supported
    assert not owner.clear_saved_hosts(True) and not owner.clear_saved_hosts(1)
    adapter.fail = True
    assert owner.clear_saved_hosts(2)
    owner.tick()
    assert owner.owner_error == 7 and not owner.snapshot()["clear_complete"]
    owner.tick()
    assert adapter.calls == [("CLEAR_PEERS", 1), ("CLEAR_PEERS", 2)]


@pytest.mark.parametrize("action", ("forget", "clear"))
def test_disconnect_derives_peer_connected_from_live_status_without_catalog_read_or_snapshot_mutation(action):
    class CountedAdapter(Adapter):
        peer_reads = 0
        def forget_host(self, identity, generation):
            self.calls.append(("FORGET", identity, generation))
            return self.next_operation
        def clear_saved_hosts(self, generation):
            self.calls.append(("CLEAR_PEERS", generation))
            return self.next_operation
        @property
        def bonded_peers(self):
            self.peer_reads += 1
            return tuple(dict(p, connected=self.status["connected"] and p["id"] == self.status["connected_id"])
                         for p in self.peers)
    adapter = CountedAdapter()
    adapter.status.update(requested_mode="AUTO", applied_mode="AUTO", state="CONNECTED",
                          connected=True, connected_id=HOST, encrypted=True, bonded=True, hid_ready=True)
    owner = NativeHostPolicy(adapter)
    owner.tick()
    before = owner.snapshot()
    assert before["peers"][0]["connected"] and adapter.peer_reads == 1
    adapter.status.update(requested_mode="PAUSED", applied_mode="PAUSED", state="PAUSED",
                          operation_id=2, policy_generation=2, connected=False, connected_id=None,
                          encrypted=False, bonded=False, hid_ready=False)
    owner.tick()
    assert owner.ready() and not any(p["connected"] for p in owner.peers)
    assert adapter.peer_reads == 1 and before["peers"][0]["connected"]
    queued = owner.forget(HOST, 1) if action == "forget" else owner.clear_saved_hosts(1)
    assert queued and not adapter.calls


def test_peer_connected_identity_publication_uses_fresh_status_and_read_failure_stays_unready():
    class PublishedAdapter(Adapter):
        peer_reads = 0
        fail_status = False
        @property
        def host_status(self):
            if self.fail_status:
                raise RuntimeError("inert status failure")
            return deepcopy(self.status)
        @property
        def bonded_peers(self):
            self.peer_reads += 1
            return tuple(deepcopy(self.peers))
    adapter = PublishedAdapter()
    adapter.status.update(connected=True, connected_id=HOST)
    owner = NativeHostPolicy(adapter)
    owner.tick()
    original = owner.snapshot()
    assert [p["connected"] for p in owner.peers] == [True, False]
    adapter.status["connected_id"] = OTHER
    owner.tick()
    assert [p["connected"] for p in owner.peers] == [False, True]
    assert [p["connected"] for p in original["peers"]] == [True, False]
    assert adapter.peer_reads == 1
    adapter.fail_status = True
    adapter.status.update(connected=False, connected_id=None)
    owner.tick()
    assert not owner.ready() and owner.owner_error == 10
    assert owner.status["connected"] and not owner.forget(OTHER, 1) and not adapter.calls


def test_optional_admission_diagnostics_are_cached_without_extra_native_reads_or_policy_changes():
    class CountedAdapter(Adapter):
        def __init__(self):
            super().__init__()
            self.status_reads = 0
        @property
        def host_status(self):
            self.status_reads += 1
            return super().host_status
    adapter = CountedAdapter()
    owner = NativeHostPolicy(adapter)
    owner.tick()
    assert owner.ready() and owner.diagnostics is None and adapter.status_reads == 2
    before = owner.snapshot()
    raw = dict(diag_version=1, **{"diag_" + key: 0 for key in DIAG_UINT_FIELDS + DIAG_INT_FIELDS})
    raw.update(diag_connect_events=0xFFFFFFFF, diag_connect_failures=3, diag_last_connect_status=0x213)
    raw["diag_peer_address"] = "synthetic-excluded-private-field"
    adapter.status.update(raw)
    owner.tick()
    assert adapter.status_reads == 3 and owner.ready() and owner.snapshot() == before
    assert owner.diagnostics == dict(version=1, **{key: raw["diag_" + key] for key in DIAG_UINT_FIELDS + DIAG_INT_FIELDS})
    assert "peer_address" not in owner.diagnostics and not adapter.calls
    # Malformed/future diagnostics never change the existing policy decision.
    adapter.status["diag_version"] = True
    owner.tick()
    assert adapter.status_reads == 4 and owner.ready() and owner.diagnostics is None and owner.snapshot() == before
    adapter.status["diag_version"] = 2
    owner.tick()
    assert adapter.status_reads == 5 and owner.ready() and owner.diagnostics is None and not adapter.calls


@pytest.mark.parametrize("key", DIAG_UINT_FIELDS + DIAG_INT_FIELDS)
@pytest.mark.parametrize("invalid", [None, True, 1.0, "1", -0x80000001, 0x100000000])
def test_admission_diagnostic_scalar_validation_is_exact_and_never_exports_extra_fields(key, invalid):
    raw = dict(diag_version=1, **{"diag_" + name: 0 for name in DIAG_UINT_FIELDS + DIAG_INT_FIELDS})
    assert checked_diagnostics(raw)["version"] == 1
    raw["diag_" + key] = invalid
    assert checked_diagnostics(raw) is None


def refusal_identity_raw(identity=HOST, source="software", operation=18, count=3):
    return dict(saved_refusal_version=1, last_saved_refusal_id=identity,
                last_saved_refusal_source=source, last_saved_refusal_operation_id=operation,
                saved_refusal_window_count=count)


def test_saved_refusal_identity_cache_reuses_the_same_coherent_status_read():
    class CountedAdapter(Adapter):
        status_reads = 0
        @property
        def host_status(self):
            self.status_reads += 1
            return deepcopy(self.status)
        @property
        def bonded_peers(self):
            self.status.update(refusal_identity_raw(OTHER, "descriptor", 19, 2))
            return tuple(deepcopy(self.peers))
    adapter = CountedAdapter()
    adapter.status.update(refusal_identity_raw())
    owner = NativeHostPolicy(adapter)
    assert owner.refusal_identity is None
    owner.tick()
    assert adapter.status_reads == 2 and owner.ready() and not adapter.calls
    assert owner.refusal_identity == dict(version=1, id=OTHER, source="descriptor", operation_id=19, window_count=2)
    # Current native operation differs: do not relabel the last actual refusal.
    adapter.status["operation_id"] = 20
    adapter.status["private_address"] = "never exported"
    owner.tick()
    assert adapter.status_reads == 3 and owner.refusal_identity["operation_id"] == 19
    assert set(owner.refusal_identity) == {"version", "id", "source", "operation_id", "window_count"}
    assert "refusal_identity" not in owner.snapshot()
    before = owner.snapshot()
    adapter.status["saved_refusal_version"] = 2
    owner.tick()
    assert adapter.status_reads == 4 and owner.refusal_identity is None and owner.snapshot() == before


def test_saved_refusal_identity_empty_and_absent_capabilities_do_not_change_policy():
    adapter = Adapter()
    owner = NativeHostPolicy(adapter)
    owner.tick()
    assert owner.ready() and owner.refusal_identity is None
    adapter.status.update(refusal_identity_raw(None, None, 0, 0))
    owner.tick()
    assert owner.refusal_identity == dict(version=1, id=None, source=None, operation_id=0, window_count=0)
    adapter.status["version"] = 0
    owner.tick()
    assert owner.refusal_identity is None


@pytest.mark.parametrize("field,invalid", [
    ("saved_refusal_version", True), ("saved_refusal_version", 2),
    ("last_saved_refusal_id", "0000000000000000"), ("last_saved_refusal_id", "ABCD"),
    ("last_saved_refusal_id", 1), ("last_saved_refusal_id", None),
    ("last_saved_refusal_source", "address"), ("last_saved_refusal_source", None),
    ("last_saved_refusal_operation_id", 0), ("last_saved_refusal_operation_id", True),
    ("last_saved_refusal_operation_id", 0x100000000), ("saved_refusal_window_count", 0),
    ("saved_refusal_window_count", -1), ("saved_refusal_window_count", 1.0),
])
def test_saved_refusal_identity_rejects_malformed_public_fields(field, invalid):
    raw = refusal_identity_raw()
    assert checked_refusal_identity(raw)["id"] == HOST
    raw[field] = invalid
    assert checked_refusal_identity(raw) is None


def connected(adapter, operation=1, identity=HOST):
    adapter.status.update(requested_mode="AUTO", applied_mode="AUTO", state="CONNECTED", target_id=identity,
                          connected_id=identity, operation_id=operation, connected=True, encrypted=True,
                          bonded=True, hid_ready=True, filter_ready=True)


def test_same_target_request_cannot_complete_or_send_against_old_native_operation():
    adapter = Adapter(); connected(adapter)
    owner = NativeHostPolicy(adapter); owner.tick()
    assert owner.allows_input()
    old_epoch = owner.input_generation
    assert owner.request("AUTO", HOST)
    assert owner.input_generation != old_epoch and not owner.allows_input()
    assert adapter.calls == []  # UI/control callback performs no native work.
    owner.tick()
    assert adapter.calls == [("AUTO", HOST, 60)]
    assert not owner.ready() and not owner.allows_input()  # Old CONNECTED state cannot satisfy new op.
    adapter.status["operation_id"] = 2
    owner.tick()
    assert owner.allows_input()
    owner.tick()
    assert len(adapter.calls) == 1


def test_unexpected_loss_allows_only_applied_target_filter_and_never_enrolls():
    adapter = Adapter()
    owner = NativeHostPolicy(adapter); owner.tick()
    assert not owner.allows_advertising()
    adapter.status.update(requested_mode="AUTO", applied_mode="AUTO", state="WAITING", filter_ready=True)
    owner.tick()
    assert owner.allows_advertising()
    adapter.status["filter_ready"] = False
    owner.tick()
    assert not owner.allows_advertising()
    assert adapter.calls == []


def test_native_enqueue_fault_is_one_shot_and_cannot_resume_old_connected_owner():
    adapter = Adapter(); connected(adapter)
    owner = NativeHostPolicy(adapter); owner.tick()
    adapter.fail = True
    assert owner.request("PAUSED")
    owner.tick(); owner.tick()
    assert adapter.calls == [("PAUSED", None, 60)]
    assert owner.snapshot()["owner_error"] and not owner.allows_input() and not owner.allows_advertising()
    assert [p["id"] for p in adapter.peers] == [HOST, OTHER]


def test_coherent_peer_snapshot_rejects_generation_race_and_never_exposes_partial_list():
    adapter = Adapter(); adapter.race = True
    owner = NativeHostPolicy(adapter); owner.tick()
    assert owner.peers == () and owner.peer_generation is None and not owner.ready()
    assert adapter.calls == []
    with pytest.raises(ValueError): checked_peers([peer(), peer()], 1)
    with pytest.raises(ValueError): checked_peers([peer(alias="\u0085")], 1)
    with pytest.raises(ValueError): checked_peers([peer(str(i+1).zfill(16)) for i in range(9)], 1)


def test_alias_is_not_saved_on_enqueue_or_stale_persisted_state():
    adapter = Adapter()
    owner = NativeHostPolicy(adapter); owner.tick()
    assert owner.alias(HOST, "B-Intel")
    owner.tick()
    assert not owner.snapshot()["alias_complete"]
    adapter.status.update(operation_id=2, bond_generation=2, policy_generation=2)
    adapter.peers = [peer(alias="B-Intel", generation=2), peer(OTHER, generation=2)]
    owner.tick()
    assert owner.snapshot()["alias_complete"]
    assert adapter.calls == [("ALIAS", HOST, "B-Intel")]


def test_send_time_generation_change_suppresses_old_held_report_before_hid_send():
    adapter = Adapter(); connected(adapter)
    owner = NativeHostPolicy(adapter); owner.tick()
    ble = BleHid(True, "unchanged")
    sent = []
    ble._host_policy, ble._ready = owner, True
    ble._ble = SimpleNamespace(connected=True)
    ble._cc, ble._CCC = SimpleNamespace(send=sent.append), SimpleNamespace(VOLUME_INCREMENT=1, VOLUME_DECREMENT=2)
    adapter.status.update(connection_generation=2, connected_id=OTHER, target_id=OTHER)
    ble.volume(True)
    ble.volume(False)  # A second old input in the same dispatch batch is blocked too.
    assert sent == [] and owner.input_generation > 1
    assert not owner.allows_input() or owner.status["connection_generation"] == 2


def test_claimed_unknown_capability_never_uses_legacy_advertiser_or_bond_erase():
    owner = NativeHostPolicy(SimpleNamespace(host_policy_version=2))
    assert owner.claimed and not owner.version
    ble = BleHid(True, "unchanged")
    calls = []
    ble._host_policy, ble._ready = owner, True
    ble._ble = SimpleNamespace(connected=False, advertising=False, start_advertising=lambda *_: calls.append("adv"))
    ble._adv = object()
    ble.tick(); ble.request_erase_bonds(); ble._start_adv(force=True)
    assert calls == [] and not ble.request_enable()


def test_enroll_bounds_and_no_target_resume_are_separate_from_pairing():
    adapter = Adapter(); owner = NativeHostPolicy(adapter)
    assert not owner.request("ENROLL", timeout_s=121)
    assert not owner.request("ENROLL", HOST)
    assert owner.request("AUTO")
    owner.tick()
    assert adapter.calls == [("AUTO", None, 60)]
    assert owner.request("ENROLL", timeout_s=60)
    owner.tick()
    assert adapter.calls[-1] == ("ENROLL", None, 60)


def test_legacy_bls2_does_not_mislabel_queued_disconnect_as_completed_or_error():
    from remote.ble_status import encode_status
    adapter = Adapter(); connected(adapter)
    owner = NativeHostPolicy(adapter); owner.tick()
    ble = BleHid(True, "unchanged")
    ble._host_policy, ble._ready = owner, True
    assert ble.request_pause()
    queued = ble.snapshot_status()
    assert queued["mode"] == 1 and queued["error"] == 0 and not queued["intent_enabled"]
    assert len(encode_status(queued, 1, 1)) == 21
    owner.tick()
    assert ble.snapshot_status()["mode"] == 1
    adapter.status = observed(operation_id=2)
    owner.tick()
    assert ble.snapshot_status()["mode"] == 2


@pytest.mark.parametrize("changes", [dict(hid_ready=False), dict(encrypted=False), dict(persisted=False),
                                     dict(state="ERROR"), dict(error_domain="NVS", error_code=0x501)])
def test_send_time_security_or_durability_loss_blocks_without_reusing_cached_readiness(changes):
    adapter = Adapter(); connected(adapter)
    owner = NativeHostPolicy(adapter); owner.tick()
    assert owner.allows_input()
    adapter.status.update(changes)
    assert not owner.validate_input()
    assert not owner.validate_input()


def test_validated_origin_is_passed_to_native_arm_and_is_not_a_delivery_ack():
    adapter = Adapter(); connected(adapter)
    owner = NativeHostPolicy(adapter); owner.tick()
    assert owner.validate_input() and owner.arm_input()
    assert adapter.arm_calls == [(1, 1, 1, 1)]
    assert adapter.calls == []  # Arming does not enqueue a policy operation or claim delivery.


@pytest.mark.parametrize("field", ["operation_id", "policy_generation", "connection_generation", "subscription_generation"])
def test_change_after_python_validation_before_native_arm_cannot_relabel_old_report(field):
    adapter = Adapter(); connected(adapter)
    owner = NativeHostPolicy(adapter); owner.tick()
    ble = BleHid(True, "unchanged"); sent = []
    ble._host_policy, ble._ready = owner, True
    ble._ble = SimpleNamespace(connected=True)
    ble._cc, ble._CCC = SimpleNamespace(send=sent.append), SimpleNamespace(VOLUME_INCREMENT=1)
    def move(status): status[field] += 1
    adapter.arm_race = move
    ble.volume(True)
    assert sent == [] and adapter.arm_calls == [(1, 1, 1, 1)]
    assert adapter.calls == []  # A stale gesture never pauses the newly healthy host.
    assert not owner.allows_input()


def test_subscription_epoch_change_cancels_input_even_when_flags_recover_between_polls():
    adapter = Adapter(); connected(adapter)
    owner = NativeHostPolicy(adapter); owner.tick()
    old = owner.input_generation
    adapter.status["subscription_generation"] += 2
    owner.tick()
    assert owner.input_generation != old
    assert owner.validate_input() and owner.arm_input()
    assert adapter.arm_calls == [(1, 1, 1, 3)]


def test_claimed_first_candidate_without_origin_arm_api_is_unsupported_not_legacy():
    adapter = Adapter(); adapter.arm_host_input = None
    owner = NativeHostPolicy(adapter)
    assert owner.claimed and not owner.version and not owner.ready()


def test_arm_observation_failure_blocks_gesture_without_native_pause_or_repeated_policy_call():
    adapter = Adapter(); connected(adapter)
    owner = NativeHostPolicy(adapter); owner.tick()
    def fail(*_args): raise RuntimeError("injected native arm failure")
    adapter.arm_host_input = fail
    assert not owner.arm_input() and owner.owner_error == 10
    assert adapter.calls == [] and not owner.allows_input()
    adapter.arm_host_input = lambda *_args: True
    owner.tick()  # Read-only observation recovery; an old gesture remains cancelled by its epoch.
    assert owner.allows_input() and adapter.calls == []


class ForgetAdapter(Adapter):
    def forget_host(self, identity, generation):
        self.calls.append(("FORGET", identity, generation))
        if self.fail:
            raise RuntimeError("injected native forget refusal")
        operation = self.next_operation
        self.next_operation += 1
        return operation


def forget_owner():
    adapter = ForgetAdapter()
    owner = NativeHostPolicy(adapter)
    owner.tick()
    return adapter, owner


def finish_forget(adapter, owner):
    adapter.status.update(operation_id=2, bond_generation=2, policy_generation=2, target_id=None)
    adapter.peers = [peer(OTHER, generation=2)]
    owner.tick()


def test_forget_is_optional_on_claimed_version_one_and_capability_fault_keeps_owner():
    adapter = Adapter()
    owner = NativeHostPolicy(adapter)
    owner.tick()
    assert owner.claimed and owner.version == 1 and owner.ready()
    assert owner.snapshot()["forget_supported"] is False
    assert owner.forget(HOST, 1) is False and adapter.calls == []
    assert owner.request("PAUSED")
    owner.tick()
    assert adapter.calls == [("PAUSED", None, 60)]

    class FaultyCapability(Adapter):
        @property
        def forget_host(self):
            raise RuntimeError("optional capability getter")

    owner = NativeHostPolicy(FaultyCapability())
    owner.tick()
    assert owner.claimed and owner.version == 1 and owner.ready()
    assert owner.snapshot()["forget_supported"] is False


def test_forget_queues_once_and_completes_only_after_its_new_coherent_observation():
    adapter, owner = forget_owner()
    assert owner.snapshot()["forget_supported"] is True
    assert owner.forget(HOST, 1)
    assert owner.pending == ("FORGET", HOST, 1) and adapter.calls == []
    assert not owner.snapshot()["forget_complete"]
    owner.tick()
    assert adapter.calls == [("FORGET", HOST, 1)]
    assert owner.expected_operation == 2 and not owner.snapshot()["forget_complete"]
    assert owner.peer_generation == 1  # Re-read after native call, even with the same cached generation.
    adapter.status["operation_id"] = 2
    owner.tick()
    assert not owner.snapshot()["forget_complete"]  # The host is still present.
    finish_forget(adapter, owner)
    assert owner.snapshot()["forget_complete"]
    owner.tick()
    assert adapter.calls == [("FORGET", HOST, 1)]
    assert owner.snapshot()["state"] == owner.snapshot()["requested_mode"] == owner.snapshot()["applied_mode"] == "PAUSED"


@pytest.mark.parametrize("changes", [
    dict(state="WAITING"), dict(requested_mode="AUTO"), dict(applied_mode="AUTO"),
    dict(persisted=False), dict(connected=True), dict(advertising=True),
    dict(error_domain="NVS"), dict(error_code=1),
])
def test_forget_refuses_each_unclean_paused_observation_without_queue_or_native_call(changes):
    adapter, owner = forget_owner()
    adapter.status.update(changes)
    owner.tick()
    assert not owner.forget(HOST, 1)
    assert owner.pending is None and adapter.calls == []


@pytest.mark.parametrize("identity,generation", [
    (None, 1), ("", 1), ("0000000000000000", 1), ("not-an-identity", 1),
    (HOST, True), (HOST, 1.0), (HOST, "1"), (HOST, -1), (HOST, 0x100000000),
    (HOST, 0), (HOST, 2), ("9999999999999999", 1),
])
def test_forget_refuses_invalid_unlisted_or_stale_identity_and_generation(identity, generation):
    adapter, owner = forget_owner()
    assert not owner.forget(identity, generation)
    assert owner.pending is None and adapter.calls == []


@pytest.mark.parametrize("block", ["pending", "operation", "owner_error", "list", "connected_peer"])
def test_forget_refuses_pending_busy_faulted_or_unconnected_list_race(block):
    adapter, owner = forget_owner()
    if block == "pending":
        assert owner.alias(HOST, "pending alias")
    elif block == "operation":
        owner.expected_operation = 99
    elif block == "owner_error":
        owner.owner_error = 10
    elif block == "list":
        owner.peer_generation = None
    else:
        owner.peers = (peer(connected=True), peer(OTHER))
    before = owner.pending
    assert not owner.forget(HOST, 1)
    assert owner.pending == before and adapter.calls == []


def test_forget_accepts_a_listed_nonresumable_peer_and_refreshes_equal_generation_list():
    adapter, owner = forget_owner()
    adapter.peers[0]["resumable"] = False
    owner.peers = (peer(resumable=False), peer(OTHER))
    assert owner.forget(HOST, 1)
    # The native call may fail after a partial delete. Force a re-read even when the
    # first post-call native status still carries the previous bond generation.
    adapter.peers = [peer(alias="observed after call", resumable=False), peer(OTHER)]
    owner.tick()
    assert owner.peers[0]["alias"] == "observed after call"
    assert adapter.calls == [("FORGET", HOST, 1)]


@pytest.mark.parametrize("change", ["operation", "missing_operation", "generation", "peer_generation",
                                   "target", "present", "state", "requested", "applied",
                                   "persisted", "connected", "advertising", "domain", "error", "owner_error"])
def test_forget_completion_requires_every_observed_condition(change):
    adapter, owner = forget_owner()
    assert owner.forget(HOST, 1)
    owner.tick()
    finish_forget(adapter, owner)
    assert owner.snapshot()["forget_complete"]
    if change == "operation":
        owner.status["operation_id"] = 99
    elif change == "missing_operation":
        owner.expected_operation = None
    elif change == "generation":
        owner._expected_forget = (HOST, 2)
    elif change == "peer_generation":
        owner.peer_generation = None
    elif change == "target":
        owner.status["target_id"] = HOST
    elif change == "present":
        owner.peers = (peer(generation=2), peer(OTHER, generation=2))
    elif change == "state":
        owner.status["state"] = "WAITING"
    elif change == "requested":
        owner.status["requested_mode"] = "AUTO"
    elif change == "applied":
        owner.status["applied_mode"] = "AUTO"
    elif change == "persisted":
        owner.status["persisted"] = False
    elif change == "connected":
        owner.status["connected"] = True
    elif change == "advertising":
        owner.status["advertising"] = True
    elif change == "domain":
        owner.status["error_domain"] = "NVS"
    elif change == "error":
        owner.status["error_code"] = 1
    else:
        owner.owner_error = 7
    assert not owner.snapshot()["forget_complete"]


def test_request_alias_and_forget_clear_other_operation_expectations():
    adapter, owner = forget_owner()
    assert owner.forget(HOST, 1)
    assert owner.request("PAUSED")
    assert owner._expected_forget is None
    owner.tick()
    adapter.status["operation_id"] = 2
    owner.tick()
    assert owner.forget(HOST, 1)
    owner.tick()
    adapter.status["operation_id"] = 3
    owner.tick()
    assert owner.alias(HOST, "new alias")
    assert owner._expected_forget is None
    owner.tick()
    adapter.status["operation_id"] = 4
    owner.tick()
    assert owner._expected_alias == (HOST, "new alias")
    assert owner.forget(HOST, 1)
    assert owner._expected_alias is None


def test_forget_native_exception_is_owner_error_seven_with_no_retry():
    adapter, owner = forget_owner()
    adapter.fail = True
    assert owner.forget(HOST, 1)
    owner.tick()
    owner.tick()
    assert adapter.calls == [("FORGET", HOST, 1)]
    assert owner.pending is None and owner.owner_error == 7
    assert not owner.snapshot()["forget_complete"]


def test_ble_forget_wrapper_and_claim_query_do_not_use_legacy_erase():
    adapter, owner = forget_owner()
    ble = BleHid(True, "unchanged")
    assert not ble.host_policy_claimed() and not ble.request_host_forget(HOST, 1)
    ble._host_policy = owner
    assert ble.host_policy_claimed()
    assert ble.request_host_forget(HOST, 1)
    assert adapter.calls == []
    owner.tick()
    assert adapter.calls == [("FORGET", HOST, 1)]
    ble._erase_stage = "busy"
    assert not ble.request_host_forget(OTHER, 1)

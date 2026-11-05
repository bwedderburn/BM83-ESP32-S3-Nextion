"""Native-owner fault/race tests use the production Python owner and HID gate."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from blehid.ble import BleHid
from blehid.host_policy import NativeHostPolicy, checked_peers

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

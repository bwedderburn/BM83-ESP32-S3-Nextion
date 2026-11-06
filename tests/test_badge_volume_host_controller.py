import hmac

from remote.badge_hosts import BadgeHosts, EMPTY_EVENT, WindowsLaunch
from remote.badge_remote import BadgeRemote, encode


KEY = bytes(range(32))
TARGET = "1234567890abcdef"


class Ble:
    def __init__(self):
        self.calls = []
        self.state = dict(version=1, ready=True, state="PAUSED", requested_mode="PAUSED",
                          applied_mode="PAUSED", peer_generation=3, bond_generation=3,
                          operation_id=7, request_operation_id=7, persisted=True,
                          peers=({"id": TARGET, "alias": "B-Intel", "resumable": True},))

    def snapshot_host_status(self):
        return self.state

    def request_host_policy(self, mode, target, timeout):
        self.calls.append((mode, target, timeout))
        self.state.update(ready=False, request_operation_id=0)
        return True


def test_duplicate_stale_and_superseded_requests():
    ble = Ble()
    hosts = BadgeHosts(ble, lambda: None, WindowsLaunch(None))
    remote = BadgeRemote(hosts=hosts)
    remote.unit = "12345678"
    remote._clients = [[23, 0, 0, False, None, None]]
    request = dict(type="cmd", unit=remote.unit, client=23, seq=1, token="HOST_SELECT",
                   target=TARGET, generation=2)
    reply, token = remote._handle(request, None)
    assert reply["denied"] and token is None and not ble.calls
    request.update(seq=2, generation=3)
    reply, token = remote._handle(request, None)
    assert token == b"BADGE_HOST"
    assert reply["hosts"]["req_client"] == 23 and reply["hosts"]["request_operation"] == 0
    assert not reply["hosts"]["flags"] & 1
    ble.state.update(request_operation_id=8, operation_id=8, ready=True)
    reply, token = remote._handle(request, None)
    assert reply["dup"] and token is None and reply["hosts"]["request_operation"] == 8
    assert ble.calls == [("AUTO", TARGET, 60)]
    hosts.supersede()
    assert hosts.snapshot()["req_client"] is None


def test_maximum_saved_host_list_fits_single_authenticated_packet():
    ble = Ble()
    maximum = (1 << 32) - 1
    ble.state.update(peer_generation=maximum, bond_generation=maximum, operation_id=maximum,
                     request_operation_id=maximum, state="DISCONNECTING", requested_mode="ENROLL",
                     applied_mode="PAUSED", target_id=TARGET, connected_id=TARGET,
                     enroll_remaining_s=120, error_domain="SECURITY", error_code=-2147483648,
                     peers=tuple({"id": "%016x" % index, "alias": '"' * 24, "resumable": False}
                                 for index in range(1, 9)))
    launch = WindowsLaunch(KEY)
    launch.client = launch.seq = maximum
    launch.result = "UNCONFIRMED"
    hosts = BadgeHosts(ble, lambda: None, launch)
    hosts.origin = (maximum, maximum)
    remote = BadgeRemote(hosts=hosts)
    remote.unit = "12345678"
    wire = encode(KEY, remote._host_state(maximum, maximum, False, None))
    assert len(wire) <= 1200


def test_launch_requires_authentication_and_current_event_ack():
    now = [30]
    event = b"e" * 16
    launch = WindowsLaunch(KEY, lambda: now[0], lambda _: event)

    def poll(nonce, ack=EMPTY_EVENT, key=KEY):
        body = b"BWL1\x01" + bytes([nonce]) * 16 + ack
        return launch.poll(body + hmac.digest(key, body, "sha256"), now[0])

    assert poll(1, key=bytes(32)) is None
    assert not launch.request(1, 2)
    assert poll(2)[21:37] == EMPTY_EVENT
    assert launch.request(1, 2)
    assert poll(2, event) is None
    assert poll(3, b"x" * 16)[21:37] == event
    assert launch.observe(now[0]) == (False, "PENDING")
    assert poll(4, event)[21:37] == EMPTY_EVENT
    assert launch.observe(now[0]) == (True, "OPENED")
    assert launch.request(1, 3)
    now[0] += 10001
    assert poll(5, event)[21:37] == EMPTY_EVENT
    assert launch.observe(now[0]) == (True, "UNCONFIRMED")

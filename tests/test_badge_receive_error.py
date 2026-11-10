"""BM83-only receive-error recovery through the real badge transport."""
import errno
from unittest.mock import patch

from tests.test_badge_bm83_remote import FakeSocket, KEY, PEER, protocol, snapshot, transport


def test_status_receive_error_preserves_pending_and_recovers_on_valid_reply():
    class ReceiveErrorSocket(FakeSocket):
        fail_receive = False

        def recvfrom(self, size):
            if self.fail_receive:
                self.fail_receive = False
                raise OSError(errno.ECONNRESET, "injected receive failure")
            return super().recvfrom(size)

    sock = ReceiveErrorSocket()
    with patch.object(transport.socket, "socket", return_value=sock):
        remote = transport.Remote(PEER[0], PEER[1], KEY)
    remote.step(0)
    welcome = {"v": 1, "type": "welcome", "nonce": remote.nonce,
               "unit": "01020304", "client": 7}
    sock.incoming.append((protocol.encode(KEY, welcome, 1200), PEER))
    remote.step(1)
    assert remote.unit == welcome["unit"] and remote.client == welcome["client"]

    assert remote.queue_command("STATUS")
    remote.step(2)
    pending = remote.pending
    assert pending is not None and pending["command"] == "STATUS"
    before = dict(pending)
    sent = list(sock.sent)
    sock.fail_receive = True
    remote.step(3)

    assert not sock.fail_receive
    assert remote.feedback.startswith("UDP receive error:")
    # Same record, unchanged retry state: attempts, send and start times, no stall flag.
    assert remote.pending is pending and remote.pending == before
    assert sock.sent == sent

    # No reply by the first retry window, 150 ms after the send: one resend of the same wire.
    remote.step(152)
    assert remote.pending is pending
    assert sock.sent == sent + [(pending["wire"], PEER)]

    state = {"v": 1, "type": "state", "unit": remote.unit,
             "client": remote.client, "seq": remote.seq, "dup": False,
             "np": snapshot()}
    sock.incoming.append((protocol.encode(KEY, state, 1200), PEER))
    remote.step(153)

    assert remote.feedback == "Audio unit responding"
    assert remote.pending is None

"""Native context ownership and safe refusal without board/network access."""
import hashlib
import hmac
from types import SimpleNamespace

import pytest

from remote import badge_remote
from tests.test_badge_remote import profile, ServerSocket


@pytest.mark.parametrize("failure", [None, "update", "digest", "deinit"])
def test_sha256_always_closes_patched_native_context(monkeypatch, failure):
    calls = []

    class Hash:
        def update(self, data):
            calls.append(("update", data))
            if failure == "update":
                raise RuntimeError("synthetic native update error")

        def digest(self):
            calls.append("digest")
            if failure == "digest":
                raise RuntimeError("synthetic native digest error")
            return b"synthetic digest"

        def deinit(self):
            calls.append("deinit")
            if failure == "deinit":
                raise RuntimeError("synthetic native cleanup error")

    monkeypatch.setattr(badge_remote, "sys", SimpleNamespace(implementation=SimpleNamespace(name="circuitpython")))
    monkeypatch.setattr(badge_remote, "hashlib", SimpleNamespace(_deinit_supported=True, new=lambda name: Hash()))
    if failure:
        with pytest.raises(RuntimeError):
            badge_remote._sha256(b"abc")
    else:
        assert badge_remote._sha256(b"abc") == b"synthetic digest"
    assert calls[-1] == "deinit" and calls.count("deinit") == 1


@pytest.mark.parametrize("implementation", ["circuitpython", "micropython", "unknown"])
def test_unsupported_native_runtime_refuses_before_socket_or_hash_creation(monkeypatch, implementation):
    def forbidden_new(*_args):
        pytest.fail("an unsupported runtime must not allocate a native hash probe")

    monkeypatch.setattr(badge_remote, "sys", SimpleNamespace(implementation=SimpleNamespace(name=implementation)))
    monkeypatch.setattr(badge_remote, "hashlib", SimpleNamespace(new=forbidden_new))
    sock, logs = ServerSocket(), []
    receiver = badge_remote.BadgeRemote(profile=profile(), socket=sock, log=logs.append)
    for _ in range(10):
        assert not receiver.setup()
        with pytest.raises(RuntimeError, match="reviewed runtime"):
            badge_remote._sha256(b"abc")
    assert not receiver.enabled and sock.bound is None
    assert any("native hash cleanup unavailable" in line for line in logs)


def test_native_hash_close_preserves_hmac_and_closes_both_operations(monkeypatch):
    payload, key = b"synthetic authenticated message", bytes(range(32))
    expected = hmac.digest(key, payload, "sha256")[:16].hex().encode()
    opened = []

    class Hash:
        def __init__(self):
            self.native = hashlib.sha256()
            self.closed = False
            opened.append(self)

        def update(self, data):
            assert not self.closed
            self.native.update(data)

        def digest(self):
            assert not self.closed
            return self.native.digest()

        def deinit(self):
            assert not self.closed
            self.closed = True

    monkeypatch.setattr(badge_remote, "sys", SimpleNamespace(implementation=SimpleNamespace(name="circuitpython")))
    monkeypatch.setattr(badge_remote, "hashlib", SimpleNamespace(_deinit_supported=True, new=lambda name: Hash()))
    assert badge_remote.tag(key, payload) == expected
    assert len(opened) == 2 and all(obj.closed for obj in opened)

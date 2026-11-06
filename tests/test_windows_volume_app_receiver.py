import hashlib
import hmac
import importlib.util
from pathlib import Path


path = Path(__file__).resolve().parents[1] / "tools/windows_volume_app_receiver.py"
spec = importlib.util.spec_from_file_location("windows_volume_app_receiver", path)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

KEY = bytes(range(32))
EVENT = bytes(range(16, 32))


class Panel:
    def __init__(self, event=EVENT, wrong_nonce=False, forged=False):
        self.event = event
        self.wrong_nonce = wrong_nonce
        self.forged = forged
        self.acks = []

    def send(self, frame):
        body = frame[:37]
        assert body[:5] == b"BWL1\x01"
        assert hmac.new(KEY, body, hashlib.sha256).digest() == frame[37:]
        self.acks.append(body[21:37])
        nonce = app.EMPTY if self.wrong_nonce else body[5:21]
        self.response = b"BWL1\x02" + nonce + self.event

    def recv(self, _):
        key = bytes(32) if self.forged else KEY
        return self.response + hmac.new(key, self.response, hashlib.sha256).digest()


def test_valid_event_opens_once_and_only_then_acknowledges():
    opened = []
    receiver = app.Receiver(KEY, lambda: opened.append(True) or True)
    panel = Panel()
    receiver.poll(panel)
    receiver.poll(panel)
    assert opened == [True]
    assert panel.acks == [app.EMPTY, EVENT]


def test_forged_stale_and_empty_events_do_not_launch_or_acknowledge():
    opened = []
    receiver = app.Receiver(KEY, lambda: opened.append(True) or True)
    for panel in (Panel(forged=True), Panel(wrong_nonce=True), Panel(event=app.EMPTY)):
        receiver.poll(panel)
        assert panel.acks == [app.EMPTY]
    assert opened == []
    assert receiver.acknowledged == app.EMPTY


def test_unconfirmed_window_is_not_acknowledged_or_retried_for_same_tap():
    attempts = []
    receiver = app.Receiver(KEY, lambda: attempts.append(True) or False)
    panel = Panel()
    receiver.poll(panel)
    receiver.poll(panel)
    assert attempts == [True]
    assert panel.acks == [app.EMPTY, app.EMPTY]
    panel.event = b"new-button-tap!!"
    receiver.poll(panel)
    assert len(attempts) == 2


def test_setup_defaults_to_the_bundled_companion_on_any_windows_host(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(app.sys, "platform", "win32")
    monkeypatch.setattr(app.sys, "argv", [str(path), "--configure"])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(app.socket, "gethostname", lambda: "another-windows-host")
    monkeypatch.setattr(app, "configure", lambda profile, companion: calls.append((profile, companion)))
    app.main()
    assert calls == [(tmp_path / "BM83VolumeRemote/.bm83_windows_receiver.json",
                      path.with_name("bm83-windows-volume-host.py"))]


def test_existing_receiver_and_companion_paths_still_work(monkeypatch, tmp_path):
    calls = []
    profile = tmp_path / "receiver.json"
    companion = tmp_path / "existing/bm83-windows-volume-host.py"
    monkeypatch.setattr(app.sys, "platform", "win32")
    monkeypatch.setattr(app.sys, "argv", [str(path), "--config", str(profile), "--configure", str(companion)])
    monkeypatch.setattr(app, "configure", lambda *args: calls.append(args))
    app.main()
    assert calls == [(profile, companion)]

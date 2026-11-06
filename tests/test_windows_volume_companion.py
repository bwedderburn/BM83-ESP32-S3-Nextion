import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "tools/bm83-windows-volume-host.py"


@pytest.fixture
def companion(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("bm83_windows_companion_test", SCRIPT)
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    return app


def test_companion_runs_offline_from_the_repository():
    result = subprocess.run([sys.executable, str(SCRIPT), "--dry-run"], check=True,
                            capture_output=True, text=True, timeout=10)
    assert "Controller status: Enabled." in result.stdout
    assert "The unit confirms PAUSED with its HID link and advertising off." in result.stdout
    assert "Controller status: Paused." in result.stdout


def test_companion_reads_its_own_controller_profile(companion, tmp_path):
    path = tmp_path / ".bm83_windows_companion.json"
    key = bytes(range(32))
    path.write_text(json.dumps({"v": 1, "host": "192.168.1.50", "key": key.hex(),
                                "client_ip": "192.168.1.51"}), encoding="utf-8")
    assert companion.load_profile(path) == ("192.168.1.50", 8767, key, "192.168.1.51")


def test_companion_rejects_a_nonprivate_controller_without_connecting(companion, monkeypatch, tmp_path):
    path = tmp_path / ".bm83_windows_companion.json"
    key = bytes(range(32))
    path.write_text(json.dumps({"v": 1, "host": "203.0.113.10", "key": key.hex()}), encoding="utf-8")
    monkeypatch.setattr(companion.socket, "getaddrinfo", lambda host, port, *_:
                        [(None, None, None, None, (host, port))])

    class Wire:
        def connect(self, _):
            pytest.fail("the companion must reject an address outside the LAN ranges")

        def close(self):
            pass

    monkeypatch.setattr(companion.socket, "socket", lambda *_: Wire())
    with pytest.raises(OSError, match="private LAN address"):
        companion.live_client(path)

"""Safety/error-path checks for the offline native-build crypto verifier."""
import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest


PATH = Path(__file__).resolve().parents[1] / "tools/circuitpython-runtime/verify_host_tools.py"
SPEC = importlib.util.spec_from_file_location("runtime_host_tools", PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.mark.parametrize("name,args", [
    ("esptool", ["--chip", "esp32s3", "write-flash", "0x10000", "fixture.bin"]),
    ("esptool", ["--chip", "esp32s3", "image-info", "fixture.bin", "--port", "device"]),
    ("esptool", ["--chip", "esp32s3", "read-flash", "0", "1", "fixture.bin"]),
    ("espsecure", ["unknown-command"]),
    ("arbitrary_module", ["generate"]),
])
def test_device_or_unknown_commands_are_rejected_before_start(tmp_path, name, args):
    with patch.object(module.subprocess, "run") as run:
        with pytest.raises(module.VerificationError):
            module.run_tool("unsafe", name, args, tmp_path)
        run.assert_not_called()


def test_offline_module_runs_without_shell_and_discards_sensitive_output(tmp_path):
    result = SimpleNamespace(returncode=3, stdout=b"private key", stderr=b"private path")
    with patch.object(module.subprocess, "run", return_value=result) as run:
        with pytest.raises(module.VerificationError) as error:
            module.run_tool("sign", "espsecure", ["sign-data", "data.bin"], tmp_path)
    assert str(error.value) == "sign"
    assert error.value.returncode == 3
    args, options = run.call_args
    assert args[0] == [module.sys.executable, "-m", "espsecure", "sign-data", "data.bin"]
    assert options["capture_output"] is True
    assert options["timeout"] == 60
    assert "shell" not in options


def test_expected_tamper_rejection_must_actually_fail(tmp_path):
    with patch.object(module.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
        with pytest.raises(module.VerificationError):
            module.run_tool("tamper", "espsecure", ["verify-signature"], tmp_path, expect_failure=True)
    with patch.object(module.subprocess, "run", return_value=SimpleNamespace(returncode=2)):
        module.run_tool("tamper", "espsecure", ["verify-signature"], tmp_path, expect_failure=True)


def test_timeout_is_sanitized(tmp_path):
    error = subprocess.TimeoutExpired(["private path"], 60, output=b"private key")
    with patch.object(module.subprocess, "run", side_effect=error):
        with pytest.raises(module.VerificationError) as caught:
            module.run_tool("bounded", "espsecure", ["sign-data"], tmp_path)
    assert str(caught.value) == "bounded"
    assert caught.value.returncode is None


def test_roundtrip_rejects_missing_empty_or_different_outputs(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for first, second in ((None, None), (b"", b""), (b"abc", b"abd")):
        for path, data in ((a, first), (b, second)):
            if data is not None:
                path.write_bytes(data)
        with pytest.raises(module.VerificationError):
            module.require_same("roundtrip", a, b)
    a.write_bytes(b"abc")
    b.write_bytes(b"abc")
    assert module.require_same("roundtrip", a, b) == module.hashlib.sha256(b"abc").hexdigest()


def test_main_failure_report_does_not_emit_subprocess_contents(capsys):
    with patch.object(module, "verify", side_effect=module.VerificationError("sign", 3)):
        assert module.main([]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report == {"schema_version": 1, "ok": False, "failed_check": "sign",
                      "returncode": 3, "hardware_access": False}

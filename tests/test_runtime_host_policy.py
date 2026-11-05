"""Production native policy fault injection and reviewed patch/provenance linkage.

These host checks do not claim NimBLE/RF, live flash, OS HID or hardware proof.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import re

import pytest

RECIPE = Path(__file__).resolve().parents[1] / "tools/circuitpython-runtime"


def test_production_core_fault_injection(tmp_path):
    compiler = shutil.which("gcc")
    if compiler is None:
        pytest.skip("Production C host harness requires the established Linux/WSL GCC builder")
    executable = tmp_path / "native-host-policy-tests"
    command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(RECIPE / "native"),
               str(RECIPE / "native/HostPolicyCore.c"), str(RECIPE / "tests/host_policy_core_test.c"),
               "-o", str(executable)]
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    result = subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=10)
    assert "PASS production host-policy core" in result.stdout


def test_production_esp32_bridge_bodies_with_fault_injection(tmp_path):
    compiler = shutil.which("gcc")
    if compiler is None:
        pytest.skip("Production ESP32 bridge harness requires established Linux/WSL GCC")
    source = (RECIPE / "native/HostPolicy.c").read_text()
    header = (RECIPE / "native/HostPolicy.h").read_text()
    # Replace only EXTERNAL headers/types/APIs with faithful host stubs. Every
    # production function body (queues, service, NVS verification, filters,
    # snapshots and GAP callbacks) is compiled verbatim, not reimplemented.
    strip_headers = lambda value: "\n".join(line for line in value.splitlines()
                                            if not line.startswith(("#include", "#pragma once"))) + "\n"
    qstrs = set(re.findall(r"MP_QSTR_(\w+)", source))
    qstrs.update(re.findall(r"HP_(?:UINT|BOOL)\((\w+)\)", source))
    declarations = "enum {" + ",".join("MP_QSTR_" + value for value in sorted(qstrs)) + "};\n"
    combined = tmp_path / "production-port-under-test.c"
    combined.write_text('#include "host_policy_port_stubs.h"\n' + declarations +
                        strip_headers(header) + strip_headers(source) +
                        (RECIPE / "tests/host_policy_port_test.c").read_text())
    executable = tmp_path / "production-port-tests"
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    "-I", str(RECIPE / "native"), "-I", str(RECIPE / "tests"),
                    str(RECIPE / "native/HostPolicyCore.c"), str(combined), "-o", str(executable)],
                   check=True, capture_output=True, text=True, timeout=30)
    result = subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=10)
    assert "PASS production ESP32 bridge bodies" in result.stdout


@pytest.mark.parametrize("name", ["HostPolicy.c", "HostPolicy.h", "HostPolicyCore.c", "HostPolicyCore.h"])
def test_harness_helpers_are_exact_production_patch_inputs(name):
    """A passing alternate model cannot silently replace production policy tests."""
    pins = json.loads((RECIPE / "source-pins.json").read_text())
    patch = (RECIPE / "host-policy.patch").read_bytes()
    assert hashlib.sha256(patch).hexdigest() == pins["runtime_patches"]["host_policy"]["sha256"]
    target = "ports/espressif/common-hal/_bleio/" + name
    marker = "diff --git a/" + target + " b/" + target + "\n"
    section = patch.decode().split(marker, 1)[1].split("diff --git ", 1)[0]
    assert "new file mode 100644" in section
    added = "".join(line[1:] for line in section.splitlines(keepends=True)
                    if line.startswith("+") and not line.startswith("+++"))
    data = (RECIPE / "native" / name).read_bytes()
    assert added.encode() == data
    assert hashlib.sha256(data).hexdigest() == pins["runtime_patches"]["host_policy"]["files"][target]


def test_native_patch_preserves_admission_and_no_deletion_guards():
    patch = (RECIPE / "host-policy.patch").read_text()
    added = "\n".join(line[1:] for line in patch.splitlines()
                      if line.startswith("+") and not line.startswith("+++"))
    assert added.count(".filter_policy = host_mode == HP_AUTO ? BLE_HCI_ADV_FILT_CONN : BLE_HCI_ADV_FILT_NONE") == 2
    assert "bleio_host_policy_advertising_guard()" in added
    assert "bleio_host_policy_queue_input(conn_handle, self->handle" in added
    assert "bleio_host_policy_input_value(conn_handle, self->handle" in added
    assert "connection->connection_obj != MP_OBJ_NULL && connection->connection_obj != mp_const_none" in added
    assert "int disconnect_reason" in added
    assert "return BLE_GAP_REPEAT_PAIRING_IGNORE" in added
    assert "host_policy_patch_sha256" in (RECIPE / "record-build.py").read_text()
    for destructive in ("ble_store_util_delete_peer(", "ble_store_util_status_rr", "BLE_GAP_REPEAT_PAIRING_RETRY", "nvs_flash_erase(", "nvs_erase_all("):
        assert destructive not in added


def test_peripheral_admission_precedes_circuitpython_connection_publication():
    patch = (RECIPE / "host-policy.patch").read_text()

    def postimage(name):
        target = "ports/espressif/common-hal/_bleio/" + name
        section = patch.split(f"diff --git a/{target} b/{target}\n", 1)[1].split("diff --git ", 1)[0]
        return "\n".join(line[1:] for line in section.splitlines()
                         if line.startswith((" ", "+")) and not line.startswith("+++"))

    # An unadmitted provisional link may get CONNECT failure and no DISCONNECT.
    # It cannot leave a stale CircuitPython handle that prevents advertising.
    adapter = postimage("Adapter.c")
    gate = adapter.index("bleio_host_policy_connect(conn_handle)")
    attach = adapter.index("ble_gap_set_event_cb(conn_handle")
    attach_failure = adapter.index("bleio_host_policy_connection_attach_failed(")
    publish = adapter.index("connection->conn_handle = conn_handle")
    exchange = adapter.index("ble_gattc_exchange_mtu(conn_handle")
    assert gate < attach < attach_failure < publish < exchange
    assert "return BLE_HS_EREJECT;" in adapter[gate:attach]
    assert "return rc;" in adapter[attach_failure:publish]

    # When an admitted provisional link fails early, CircuitPython must release
    # the matching wrapper as well as letting native policy close the generation.
    connection = postimage("Connection.c")
    identity_guard = connection.index("event->connect.conn_handle != connection->conn_handle")
    native_event = connection.index("bleio_host_policy_event(event, connection->host_generation)")
    connect_failure = connection.index("case BLE_GAP_EVENT_CONNECT:")
    invalidation = connection.index("connection->conn_handle = BLEIO_HANDLE_INVALID")
    assert identity_guard < native_event < connect_failure < invalidation
    assert "event->connect.status != 0" in connection[:identity_guard]
    assert "MP_FALLTHROUGH;" in connection[connect_failure:invalidation]
    assert "connection->host_generation = 0" in connection


def test_native_hid_identity_and_gatt_descriptor_are_not_patch_targets():
    pins = json.loads((RECIPE / "source-pins.json").read_text())
    assert pins["sources"]["circuitpython"]["commit"] == "c9dee12beed76e4ffa11d2d6d99ff104fc976c3a"
    assert pins["configuration"] == {
        "CONFIG_BT_NIMBLE_MAX_BONDS": 8, "CONFIG_BT_NIMBLE_MAX_CCCDS": 24,
        "CONFIG_BT_NIMBLE_ENABLE_CONN_REATTEMPT": False,
    }
    files = pins["runtime_patches"]["host_policy"]["files"]
    assert not any("HIDService" in name or "hid_report" in name.lower() for name in files)
    # Policy enforcement hooks are separate from the existing application report map.
    assert "hashlib_close" in pins["runtime_patches"]

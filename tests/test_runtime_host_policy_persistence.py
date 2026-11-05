"""Exercise production NVS matching with synthetic NimBLE records."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "tools/circuitpython-runtime/native/HostPolicy.c"

# These record fields and bitfields follow pinned esp-nimble's ble_store.h.
# Only the NVS transport is stubbed. No real bond data enters this test.
STUBS = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

enum { BLE_STORE_OBJ_TYPE_OUR_SEC = 1, BLE_STORE_OBJ_TYPE_PEER_SEC, BLE_STORE_OBJ_TYPE_CCCD,
       BLE_STORE_OBJ_TYPE_PEER_ADDR = 6, BLE_STORE_OBJ_TYPE_LOCAL_IRK, BLE_STORE_OBJ_TYPE_CSFC };
enum { NVS_READONLY, ESP_ERR_NVS_NOT_FOUND = 0x1102, BLE_HS_ESTORE_FAIL = 28 };
typedef unsigned nvs_handle_t;
typedef struct { uint8_t type, val[6]; } ble_addr_t;
struct ble_store_value_sec {
    ble_addr_t peer_addr;
    uint16_t bond_count;
    uint8_t key_size;
    uint16_t ediv;
    uint64_t rand_num;
    uint8_t ltk[16], ltk_present:1;
    uint8_t irk[16], irk_present:1;
    uint8_t csrk[16], csrk_present:1;
    uint32_t sign_counter;
    unsigned authenticated:1;
    uint8_t sc:1;
};
struct ble_store_value_cccd {
    ble_addr_t peer_addr;
    uint16_t chr_val_handle, flags;
    unsigned value_changed:1;
};
struct ble_store_value_csfc { ble_addr_t peer_addr; uint8_t csfc[1]; };
struct ble_store_value_local_irk { ble_addr_t addr; uint8_t irk[16]; };
struct ble_store_value_rpa_rec { ble_addr_t peer_rpa_addr, peer_addr; };
union ble_store_value {
    struct ble_store_value_sec sec;
    struct ble_store_value_cccd cccd;
    struct ble_store_value_csfc csfc;
    struct ble_store_value_local_irk local_irk;
    struct ble_store_value_rpa_rec rpa_rec;
};

static union ble_store_value nvs_records[2];
static size_t nvs_sizes[2];
static unsigned opened, closed;

static int nvs_open(const char *name, int mode, nvs_handle_t *handle) {
    assert(!strcmp(name, "nimble_bond") && mode == NVS_READONLY);
    *handle = ++opened;
    return 0;
}
static int nvs_get_blob(nvs_handle_t handle, const char *key, void *out, size_t *size) {
    assert(handle == opened && closed + 1 == opened);
    int index = !strcmp(key, "our_sec_1") ? 0 : !strcmp(key, "our_sec_2") ? 1 : -1;
    if (index < 0 || !nvs_sizes[index]) { return ESP_ERR_NVS_NOT_FOUND; }
    assert(*size >= nvs_sizes[index]);
    *size = nvs_sizes[index];
    memcpy(out, &nvs_records[index], *size);
    return 0;
}
static void nvs_close(nvs_handle_t handle) {
    assert(handle == opened);
    closed++;
}
"""

CASES = r"""
static const ble_addr_t peer = {1, {1,2,3,4,5,6}};

static void security(union ble_store_value *record, unsigned representation) {
    memset(record, representation, sizeof(*record));
    struct ble_store_value_sec *sec = &record->sec;
    sec->peer_addr = peer;
    sec->bond_count = 8;
    sec->key_size = 16;
    sec->ediv = 19;
    sec->rand_num = 23;
    memset(sec->ltk, 0x31, sizeof(sec->ltk));
    sec->ltk_present = 1;
    sec->irk_present = 0; // The intentionally different inactive IRK is not a key.
    memset(sec->csrk, 0x32, sizeof(sec->csrk));
    sec->csrk_present = 1;
    sec->sign_counter = 42;
    sec->authenticated = 1;
    sec->sc = 1;
}

int main(void) {
    union ble_store_value a, b;
    security(&a, 0x00);
    security(&b, 0xfe);
    // Inactive key contents AND representation bits differ. The active keys
    // and all fields used by the runtime are the same.
    assert(memcmp(&a, &b, sizeof(a.sec)) != 0);
    assert(memcmp(a.sec.irk, b.sec.irk, sizeof(a.sec.irk)) != 0);
    assert(same_store_record(BLE_STORE_OBJ_TYPE_OUR_SEC, &a, &b));
    assert(same_store_record(BLE_STORE_OBJ_TYPE_PEER_SEC, &a, &b));

    b.sec.ltk[0] ^= 1;
    assert(!same_store_record(BLE_STORE_OBJ_TYPE_OUR_SEC, &a, &b));
    memcpy(&nvs_records[0], &b, sizeof(b));
    b.sec.ltk[0] ^= 1;
    memcpy(&nvs_records[1], &b, sizeof(b));
    nvs_sizes[0] = nvs_sizes[1] = sizeof(a.sec);
    assert(persistent_match(BLE_STORE_OBJ_TYPE_OUR_SEC, &a) == 0);
    assert(opened == 1 && closed == 1);
    nvs_records[1].sec.authenticated = 0;
    assert(persistent_match(BLE_STORE_OBJ_TYPE_OUR_SEC, &a) == BLE_HS_ESTORE_FAIL);
    nvs_sizes[0]--;
    memcpy(&nvs_records[1], &b, sizeof(b));
    assert(persistent_match(BLE_STORE_OBJ_TYPE_OUR_SEC, &a) == BLE_HS_ESTORE_FAIL);
    assert(opened == 3 && closed == 3);

    b.sec.csrk[0] ^= 1;
    assert(!same_store_record(BLE_STORE_OBJ_TYPE_PEER_SEC, &a, &b));
    b.sec.csrk[0] ^= 1;
    b.sec.irk_present = 1;
    assert(!same_store_record(BLE_STORE_OBJ_TYPE_PEER_SEC, &a, &b));
    a.sec.irk_present = 1;
    assert(!same_store_record(BLE_STORE_OBJ_TYPE_PEER_SEC, &a, &b));
    a.sec.irk_present = b.sec.irk_present = 0;
    b.sec.bond_count++;
    assert(!same_store_record(BLE_STORE_OBJ_TYPE_OUR_SEC, &a, &b));

    memset(&a, 0x00, sizeof(a));
    memset(&b, 0xfe, sizeof(b));
    a.cccd.peer_addr = b.cccd.peer_addr = peer;
    a.cccd.chr_val_handle = b.cccd.chr_val_handle = 17;
    a.cccd.flags = b.cccd.flags = 1;
    a.cccd.value_changed = b.cccd.value_changed = 0;
    assert(memcmp(&a.cccd, &b.cccd, sizeof(a.cccd)) != 0);
    assert(same_store_record(BLE_STORE_OBJ_TYPE_CCCD, &a, &b));
    b.cccd.value_changed = 1;
    assert(!same_store_record(BLE_STORE_OBJ_TYPE_CCCD, &a, &b));
    b.cccd.value_changed = 0;
    b.cccd.flags = 0;
    assert(!same_store_record(BLE_STORE_OBJ_TYPE_CCCD, &a, &b));
    b.cccd.flags = 1;
    b.cccd.chr_val_handle++;
    assert(!same_store_record(BLE_STORE_OBJ_TYPE_CCCD, &a, &b));

    a.csfc.peer_addr = b.csfc.peer_addr = peer;
    a.csfc.csfc[0] = b.csfc.csfc[0] = 1;
    assert(same_store_record(BLE_STORE_OBJ_TYPE_CSFC, &a, &b));
    b.csfc.csfc[0] = 0;
    assert(!same_store_record(BLE_STORE_OBJ_TYPE_CSFC, &a, &b));

    a.local_irk.addr = b.local_irk.addr = peer;
    memset(a.local_irk.irk, 0x24, sizeof(a.local_irk.irk));
    memset(b.local_irk.irk, 0x24, sizeof(b.local_irk.irk));
    assert(same_store_record(BLE_STORE_OBJ_TYPE_LOCAL_IRK, &a, &b));
    b.local_irk.irk[0] ^= 1;
    assert(!same_store_record(BLE_STORE_OBJ_TYPE_LOCAL_IRK, &a, &b));

    a.rpa_rec.peer_addr = b.rpa_rec.peer_addr = peer;
    a.rpa_rec.peer_rpa_addr = b.rpa_rec.peer_rpa_addr = peer;
    assert(same_store_record(BLE_STORE_OBJ_TYPE_PEER_ADDR, &a, &b));
    b.rpa_rec.peer_rpa_addr.type ^= 1;
    assert(!same_store_record(BLE_STORE_OBJ_TYPE_PEER_ADDR, &a, &b));
    b.rpa_rec.peer_rpa_addr.type ^= 1;
    b.rpa_rec.peer_addr.val[0] ^= 1;
    assert(!same_store_record(BLE_STORE_OBJ_TYPE_PEER_ADDR, &a, &b));
    assert(!same_store_record(99, &a, &a));
    return 0;
}
"""


def test_production_nvs_matching_uses_semantic_records(tmp_path):
    compiler = shutil.which("gcc")
    if compiler is None:
        pytest.skip("Production persistence test requires the established Linux/WSL GCC builder")
    source = SOURCE.read_text()
    bodies = []
    for name in ("store_size", "store_prefix", "same_store_address", "same_store_record", "persistent_match"):
        definition = re.search(rf"^static [^\n]*\b{name}\([^\n]*\).*?^\}}", source, re.M | re.S)
        assert definition is not None, name
        bodies.append(definition.group())
    c_file = tmp_path / "native-persistence.c"
    c_file.write_text(STUBS + "\n".join(bodies) + CASES)
    executable = tmp_path / "native-persistence"
    subprocess.run([compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", str(c_file), "-o", str(executable)],
                   check=True, capture_output=True, text=True, timeout=30)
    subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=10)

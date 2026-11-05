"""Exercise the pinned NimBLE patch's exact same-slot CSFC updater."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest


PATCH = Path(__file__).resolve().parents[1] / "tools/circuitpython-runtime/nimble-csfc-upsert.patch"


def _new_side(path):
    section = PATCH.read_text().split(f"diff --git a/{path} b/{path}\n", 1)[1]
    section = section.split("\ndiff --git ", 1)[0]
    return "\n".join(line[1:] for line in section.splitlines()
                     if line.startswith((" ", "+")) and not line.startswith("+++"))


def test_csfc_gatt_write_stays_on_the_guarded_store_path():
    source = _new_side("nimble/host/src/ble_gatts.c")
    assert "ble_store_delete_csfc" not in source
    gate = source.index("if (conn->bhc_sec_state.bonded)")
    encryption = source.index("if (!conn->bhc_sec_state.encrypted)", gate)
    identity = source.index("value_csfc.peer_addr = conn->bhc_peer_addr;", encryption)
    guarded = source.index("rc = ble_gatts_write_peer_csfc(&value_csfc);", identity)
    publish = source.index("memcpy(conn->bhc_gatt_svr.peer_cl_sup_feat, feat", guarded)
    assert gate < encryption < identity < guarded < publish
    assert "ble_gatts_write_peer_csfc(&csfc);" in source
    assert source.index("value->peer_addr = saved.peer_addr;") < source.index("ble_store_write_csfc(value)")
    assert "ble_hs_misc_peer_addr_type_to_id(conn->bhc_peer_addr.type)" in source


def test_csfc_vendor_upsert_updates_one_verified_slot(tmp_path):
    compiler = shutil.which("gcc")
    if compiler is None:
        pytest.skip("NimBLE CSFC fixture requires the Linux/WSL GCC builder")
    def body(path, name):
        source = _new_side(f"nimble/host/store/config/src/{path}")
        match = re.search(rf"{name}\(.*?\n\}}", source, re.S)
        assert match is not None
        return "static int\n" + match.group() + "\n"

    fixture = tmp_path / "csfc.c"
    fixture.write_text(STUBS +
                       body("ble_store_config_priv.h", "ble_store_config_csfc_same_peer") +
                       body("ble_store_config.c", "ble_store_config_find_csfc") +
                       body("ble_store_nvs.c", "ble_store_config_persist_csfc_update") + CASES)
    executable = tmp_path / "csfc"
    compiled = subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                               str(fixture), "-o", str(executable)],
                              capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    subprocess.run([str(executable)], check=True, capture_output=True, timeout=10)


STUBS = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define MYNEWT_VAL(x) 8
#define NIMBLE_NVS_STR_NAME_MAX_LEN 16

enum { ESP_OK = 0, ESP_ERR_NVS_NOT_FOUND = 0x1102, BLE_HS_ENOENT = 5, BLE_HS_EREJECT = 16,
       BLE_HS_ESTORE_FAIL = 28, BLE_STORE_OBJ_TYPE_CSFC = 8, BLE_ADDR_RANDOM_ID = 3 };
typedef struct { uint8_t type, val[6]; } ble_addr_t;
static const ble_addr_t any = {255, {0}};
#define BLE_ADDR_ANY (&any)
struct ble_store_key_csfc { ble_addr_t peer_addr; uint8_t idx; };
struct ble_store_value_csfc { ble_addr_t peer_addr; uint8_t csfc[1]; };
union ble_store_value { struct ble_store_value_csfc csfc; };

static struct ble_store_value_csfc nvs[MYNEWT_VAL(BLE_STORE_MAX_CSFCS)];
static unsigned occupied, reads, writes, fail_slot, fail_write;

static int ble_addr_cmp(const ble_addr_t *a, const ble_addr_t *b) {
    return a->type != b->type || memcmp(a->val, b->val, sizeof a->val);
}

static void get_nvs_key_string(int type, int slot, char *key) {
    assert(type == BLE_STORE_OBJ_TYPE_CSFC && slot >= 1 && slot <= 8);
    snprintf(key, NIMBLE_NVS_STR_NAME_MAX_LEN, "csfc_sec_%d", slot);
}

static unsigned slot_for(const char *key) {
    unsigned index;
    assert(sscanf(key, "csfc_sec_%u", &index) == 1 && index >= 1 && index <= 8);
    return index - 1;
}

static int get_nvs_db_value(int type, char *key, union ble_store_value *saved) {
    assert(type == BLE_STORE_OBJ_TYPE_CSFC);
    unsigned slot = slot_for(key);
    reads++;
    if (fail_slot == slot + 1) { return BLE_HS_ESTORE_FAIL; }
    if (!(occupied & (1U << slot))) { return ESP_ERR_NVS_NOT_FOUND; }
    saved->csfc = nvs[slot];
    return ESP_OK;
}

static int ble_nvs_write_key_value(char *key, const void *value, size_t size) {
    assert(size == sizeof nvs[0] && occupied & (1U << slot_for(key)));
    writes++;
    if (fail_write) { return BLE_HS_ESTORE_FAIL; }
    memcpy(&nvs[slot_for(key)], value, size);
    return ESP_OK;
}
"""


CASES = r"""

int main(void) {
    const struct ble_store_value_csfc old = { {3, {1,2,3,4,5,6}}, {1} };
    struct ble_store_value_csfc alias = old;
    alias.peer_addr.type = 1;
    struct ble_store_key_csfc key = {alias.peer_addr, 0};
    struct ble_store_value_csfc ram[] = {old, alias};
    int index;
    assert(ble_store_config_find_csfc(&key, ram, 1, &index) == ESP_OK && index == 0);
    assert(ram[index].peer_addr.type == 3);
    assert(ble_store_config_find_csfc(&key, ram, 2, &index) == BLE_HS_ESTORE_FAIL);
    key.peer_addr = *BLE_ADDR_ANY;
    key.idx = 1;
    assert(ble_store_config_find_csfc(&key, ram, 2, &index) == ESP_OK && index == 1);

    struct ble_store_value_csfc next = old;
    next.csfc[0] = 3;
    struct ble_store_value_csfc other = old;
    other.peer_addr.type = 0;
    nvs[1] = other;
    nvs[6] = old;
    occupied = (1U << 1) | (1U << 6);

    assert(ble_store_config_persist_csfc_update(&old, &other) == BLE_HS_EREJECT);
    assert(!reads && !writes);

    fail_slot = 8;
    assert(ble_store_config_persist_csfc_update(&old, &next) == BLE_HS_ESTORE_FAIL);
    fail_slot = 0;
    assert(!writes && nvs[6].csfc[0] == 1);

    nvs[7] = alias;
    occupied |= 1U << 7;
    assert(ble_store_config_persist_csfc_update(&old, &next) == BLE_HS_ESTORE_FAIL);
    occupied &= ~(1U << 7);
    assert(!writes);

    nvs[6].csfc[0] = 2;
    assert(ble_store_config_persist_csfc_update(&old, &next) == BLE_HS_ESTORE_FAIL);
    assert(!writes);
    nvs[6] = old;

    occupied &= ~(1U << 6);
    assert(ble_store_config_persist_csfc_update(&old, &next) == BLE_HS_ESTORE_FAIL);
    assert(!writes);
    occupied |= 1U << 6;

    fail_write = 1;
    assert(ble_store_config_persist_csfc_update(&old, &next) == BLE_HS_ESTORE_FAIL);
    assert(writes == 1 && nvs[6].csfc[0] == 1);
    fail_write = 0;

    assert(ble_store_config_persist_csfc_update(&old, &next) == ESP_OK);
    assert(writes == 2 && nvs[6].csfc[0] == 3 && nvs[6].peer_addr.type == 3);
    assert(!memcmp(&nvs[1], &other, sizeof other));
    assert(occupied == ((1U << 1) | (1U << 6)));
    return 0;
}
"""

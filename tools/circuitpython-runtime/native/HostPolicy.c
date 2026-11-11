// SPDX-License-Identifier: MIT
// BM83 ESP32-only capability. No key material is exposed to Python or logging.
#include "common-hal/_bleio/HostPolicy.h"
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include "py/objstr.h"
#include "py/runtime.h"
#include "shared-bindings/_bleio/__init__.h"
#include "shared-bindings/time/__init__.h"
#include "shared/runtime/interrupt_char.h"
#include "supervisor/shared/tick.h"
#include "common-hal/_bleio/Adapter.h"
#include "common-hal/_bleio/Connection.h"
#include "host/ble_hs.h"
#include "host/ble_gatt.h"
#include "host/ble_hs_pvcy.h"
#include "host/ble_store.h"
#include "../../esp-idf/components/bt/host/nimble/nimble/nimble/host/store/config/include/store/config/ble_store_config.h"
#include "../../esp-idf/components/bt/host/nimble/nimble/nimble/host/store/config/src/ble_store_config_priv.h"
#include "nimble/hci_common.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_npl.h"
#include "freertos/FreeRTOS.h"
#include "esp_timer.h"
#include "nvs.h"

#if !MYNEWT_VAL(BLE_WHITELIST) || !MYNEWT_VAL(BLE_HS_PVCY) || MYNEWT_VAL(BLE_HOST_BASED_PRIVACY)
#error BM83 host policy requires controller privacy and an accept list
#endif
#if CONFIG_BT_NIMBLE_MAX_BONDS != 8 || CONFIG_BT_NIMBLE_MAX_CCCDS != 24 || !CONFIG_BT_NIMBLE_NVS_PERSIST
#error BM83 host policy requires the reviewed persistent 8-bond 24-CCCD configuration
#endif
#if defined(CONFIG_BT_NIMBLE_HANDLE_REPEAT_PAIRING_DELETION) && CONFIG_BT_NIMBLE_HANDLE_REPEAT_PAIRING_DELETION
#error BM83 host policy must never enable repeat-pair deletion
#endif
#if defined(CONFIG_BT_NIMBLE_ENABLE_CONN_REATTEMPT) && CONFIG_BT_NIMBLE_ENABLE_CONN_REATTEMPT
#error BM83 host policy owns all advertising restarts
#endif

// Exported pinned NimBLE internal functions. Exact signatures are pinned/hashed
// with this recipe; no private key is copied outside this native translation unit.
extern int ble_hs_pvcy_add_entry(const uint8_t *, uint8_t, const uint8_t *);
extern int ble_hs_pvcy_remove_entry(uint8_t, const uint8_t *);
extern int ble_hs_hci_cmd_tx(uint16_t, const void *, uint8_t, void *, uint8_t);
extern int ble_hs_pvcy_rpa_ah(const uint8_t[16], const uint8_t[3], uint8_t[3]);
extern void ble_hs_lock(void);
extern void ble_hs_unlock(void);

static hp_core_t core;
static hp_status_t observed;
static hp_peer_t observed_peers[HP_MAX_PEERS];
static size_t observed_count;
static uint16_t observed_handle=HP_INVALID_HANDLE;
static portMUX_TYPE policy_mux=portMUX_INITIALIZER_UNLOCKED;
static volatile bool initialized, synced, processing, policy_busy, timer_ready, fault_pending;
static hp_queue_t command_queue;
static hp_input_queue_t input_queue;
static hp_input_report_t last_input;
static bool last_input_valid;
static uint16_t observed_input_handle;
static hp_status_t input_origin;
static uint16_t origin_handle,origin_input_handle;
static bool input_origin_valid;
#define HP_ADV_MAX_BYTES 1650
#define HP_ADV_VM_WAIT_MS 200
typedef struct {
    bool active, finished, cancelled, waiter_gone, connectable, anonymous, user_owned;
    uint32_t token, timeout, result;
    float interval;
    uint16_t data_length, response_length;
    mp_int_t power;
    hp_raw_advertise_fn start;
    uint8_t data[HP_ADV_MAX_BYTES], response[HP_ADV_MAX_BYTES];
} advertising_request_t;
static advertising_request_t advertising_request;
static uint32_t next_advertising_token;
static hp_domain_t pending_fault_domain;
static int pending_fault;
static uint32_t store_generation;
static struct ble_npl_callout policy_timer;
static bool timer_initialized;
static volatile bool store_guard_failed;
typedef hp_command_t policy_request_t;

static int guarded_write(int type, const union ble_store_value *value);
static int guarded_delete(int type, const union ble_store_key *key);

static uint64_t millis(void) { return (uint64_t)esp_timer_get_time()/1000; }
static hp_address_t address(const ble_addr_t *a) {
    hp_address_t result={.type=a->type}; memcpy(result.val,a->val,6); return result;
}
static ble_addr_t native_address(const hp_address_t *a) {
    ble_addr_t result={.type=a->type}; memcpy(result.val,a->val,6); return result;
}
static void publish(void) {
    portENTER_CRITICAL(&policy_mux);
    observed=core.status; observed_count=core.peer_count;
    observed_handle=core.handle;
    observed_input_handle=core.hid_input_handle;
    memcpy(observed_peers,core.peers,sizeof(observed_peers));
    portEXIT_CRITICAL(&policy_mux);
}
static void schedule(void) {
    // The single native 100ms callout services fixed requests. Do NOT put an
    // event from VM/store callbacks: pinned NPL eventq_put can block forever
    // on a full queue, including while a store callback holds the host lock.
}
static void clear_inputs(void) {
    portENTER_CRITICAL(&policy_mux); hp_clear_input(&input_queue); input_origin_valid=false; portEXIT_CRITICAL(&policy_mux);
}
static void fault(hp_domain_t domain, int code) {
    // May run under NimBLE's store lock: latch only; no nested GAP/store call.
    portENTER_CRITICAL(&policy_mux);
    if (!store_guard_failed) {
        fault_pending=true; pending_fault_domain=domain; pending_fault=code;
    }
    observed.filter_ready=false; observed.hid_ready=false;
    hp_clear_input(&input_queue);
    portEXIT_CRITICAL(&policy_mux);
    schedule();
}
static bool check_store_guards(void) {
    portENTER_CRITICAL(&policy_mux);
    bool context_ready=true;
    #if MYNEWT_VAL(BLE_STATIC_TO_DYNAMIC)
    context_ready=ble_store_config_vars!=NULL;
    #endif
    if (!store_guard_failed && (!context_ready || ble_hs_cfg.store_read_cb!=ble_store_config_read ||
        ble_hs_cfg.store_write_cb!=guarded_write || ble_hs_cfg.store_delete_cb!=guarded_delete ||
        ble_hs_cfg.store_status_cb!=bleio_host_policy_store_status)) {
        store_guard_failed=true;
        fault_pending=true;
        pending_fault_domain=HP_DOMAIN_NIMBLE;
        pending_fault=BLE_HS_ESTORE_FAIL;
        observed.filter_ready=false;
        observed.hid_ready=false;
        hp_clear_input(&input_queue);
        input_origin_valid=false;
    }
    bool intact=!store_guard_failed;
    portEXIT_CRITICAL(&policy_mux);
    return intact;
}
static int persist(void *unused, const hp_blob_t *blob) {
    (void)unused;
    nvs_handle_t handle;
    esp_err_t rc=nvs_open("bm83_hid_policy",NVS_READWRITE,&handle);
    if (rc!=ESP_OK) { return rc; }
    rc=nvs_set_blob(handle,"policy_v1",blob,sizeof(*blob));
    if (rc==ESP_OK) { rc=nvs_commit(handle); }
    hp_blob_t checked; size_t size=sizeof(checked);
    if (rc==ESP_OK) { rc=nvs_get_blob(handle,"policy_v1",&checked,&size); }
    if (rc==ESP_OK && (size!=sizeof(checked) || memcmp(&checked,blob,sizeof(checked)) || !hp_blob_valid(&checked))) { rc=ESP_ERR_INVALID_STATE; }
    nvs_close(handle); return rc;
}
static int stop_advertising(void *unused) {
    (void)unused;
    int rc;
    #if MYNEWT_VAL(BLE_EXT_ADV)
    rc=ble_gap_ext_adv_stop(0);
    #else
    rc=ble_gap_adv_stop();
    #endif
    common_hal_bleio_adapter_obj.user_advertising=false;
    return rc==BLE_HS_EALREADY || rc==BLE_HS_EINVAL ? 0 : rc;
}
static int terminate(void *unused, uint16_t handle) {
    (void)unused;
    int rc=ble_gap_terminate(handle,BLE_ERR_REM_USER_CONN_TERM);
    return rc==BLE_HS_ENOTCONN ? HP_TERMINATE_ABSENT : rc;
}
static int submit_input(const hp_input_report_t *report) {
    if (!check_store_guards() || !hp_input_current(&core,report)) { return BLE_HS_EREJECT; }
    struct os_mbuf *buffer=ble_hs_mbuf_from_flat(report->data,report->length);
    if (!buffer) { return BLE_HS_ENOMEM; }
    // This call and all connection/policy callbacks run on the same native host
    // task. Numeric handle reuse cannot interleave validation and submission.
    int rc=ble_gatts_notify_custom(report->handle,report->attribute,buffer);
    if (!rc) { portENTER_CRITICAL(&policy_mux); last_input=*report; last_input_valid=true; portEXIT_CRITICAL(&policy_mux); }
    return rc;
}
static int release_old_input(void) {
    hp_input_report_t release;
    portENTER_CRITICAL(&policy_mux); bool valid=last_input_valid; release=last_input; portEXIT_CRITICAL(&policy_mux);
    if (!valid || !hp_input_current(&core,&release)) { return 0; }
    bool held=false;
    for (unsigned i=0;i<release.length;i++) { held |= release.data[i]!=0; release.data[i]=0; }
    return held ? submit_input(&release) : 0;
}

static size_t store_size(int type) {
    return type==BLE_STORE_OBJ_TYPE_CCCD ? sizeof(struct ble_store_value_cccd) :
           type==BLE_STORE_OBJ_TYPE_CSFC ? sizeof(struct ble_store_value_csfc) :
           type==BLE_STORE_OBJ_TYPE_LOCAL_IRK ? sizeof(struct ble_store_value_local_irk) :
           type==BLE_STORE_OBJ_TYPE_PEER_ADDR ? sizeof(struct ble_store_value_rpa_rec) : sizeof(struct ble_store_value_sec);
}
static const char *store_prefix(int type) {
    switch(type) {
        case BLE_STORE_OBJ_TYPE_OUR_SEC: return "our_sec";
        case BLE_STORE_OBJ_TYPE_PEER_SEC: return "peer_sec";
        case BLE_STORE_OBJ_TYPE_CCCD: return "cccd_sec";
        case BLE_STORE_OBJ_TYPE_CSFC: return "csfc_sec";
        case BLE_STORE_OBJ_TYPE_LOCAL_IRK: return "local_irk";
        case BLE_STORE_OBJ_TYPE_PEER_ADDR: return "rpa_rec";
        default: return NULL;
    }
}
// A stored value's padding and unused bitfield bits are not part of its
// contract. NimBLE copies typed records into iterator storage and the NVS
// blobs can have different padding from those in-memory copies.
static bool same_store_address(const ble_addr_t *a, const ble_addr_t *b) {
    return a->type==b->type && memcmp(a->val,b->val,sizeof(a->val))==0;
}
static bool same_store_record(int type, const union ble_store_value *a, const union ble_store_value *b) {
    switch (type) {
        case BLE_STORE_OBJ_TYPE_OUR_SEC:
        case BLE_STORE_OBJ_TYPE_PEER_SEC:
            return same_store_address(&a->sec.peer_addr,&b->sec.peer_addr) &&
                a->sec.bond_count==b->sec.bond_count && a->sec.key_size==b->sec.key_size &&
                a->sec.ediv==b->sec.ediv && a->sec.rand_num==b->sec.rand_num &&
                a->sec.sign_counter==b->sec.sign_counter && a->sec.authenticated==b->sec.authenticated &&
                a->sec.sc==b->sec.sc && a->sec.ltk_present==b->sec.ltk_present &&
                a->sec.irk_present==b->sec.irk_present && a->sec.csrk_present==b->sec.csrk_present &&
                (!a->sec.ltk_present || memcmp(a->sec.ltk,b->sec.ltk,sizeof(a->sec.ltk))==0) &&
                (!a->sec.irk_present || memcmp(a->sec.irk,b->sec.irk,sizeof(a->sec.irk))==0) &&
                (!a->sec.csrk_present || memcmp(a->sec.csrk,b->sec.csrk,sizeof(a->sec.csrk))==0);
        case BLE_STORE_OBJ_TYPE_CCCD:
            // The pending notification marker can change in RAM while the
            // subscribed peer is absent. Only the key and flags are durable.
            return same_store_address(&a->cccd.peer_addr,&b->cccd.peer_addr) &&
                a->cccd.chr_val_handle==b->cccd.chr_val_handle && a->cccd.flags==b->cccd.flags;
        case BLE_STORE_OBJ_TYPE_CSFC:
            return same_store_address(&a->csfc.peer_addr,&b->csfc.peer_addr) &&
                memcmp(a->csfc.csfc,b->csfc.csfc,sizeof(a->csfc.csfc))==0;
        case BLE_STORE_OBJ_TYPE_LOCAL_IRK:
            return same_store_address(&a->local_irk.addr,&b->local_irk.addr) &&
                memcmp(a->local_irk.irk,b->local_irk.irk,sizeof(a->local_irk.irk))==0;
        case BLE_STORE_OBJ_TYPE_PEER_ADDR:
            return same_store_address(&a->rpa_rec.peer_rpa_addr,&b->rpa_rec.peer_rpa_addr) &&
                same_store_address(&a->rpa_rec.peer_addr,&b->rpa_rec.peer_addr);
        default:
            return false;
    }
}
static bool same_store_key(int type, const union ble_store_value *a, const union ble_store_value *b) {
    switch (type) {
        case BLE_STORE_OBJ_TYPE_OUR_SEC:
        case BLE_STORE_OBJ_TYPE_PEER_SEC:
            return same_store_address(&a->sec.peer_addr,&b->sec.peer_addr);
        case BLE_STORE_OBJ_TYPE_CCCD:
            return same_store_address(&a->cccd.peer_addr,&b->cccd.peer_addr) &&
                a->cccd.chr_val_handle==b->cccd.chr_val_handle;
        case BLE_STORE_OBJ_TYPE_CSFC:
            return same_store_address(&a->csfc.peer_addr,&b->csfc.peer_addr);
        case BLE_STORE_OBJ_TYPE_LOCAL_IRK:
            return same_store_address(&a->local_irk.addr,&b->local_irk.addr);
        case BLE_STORE_OBJ_TYPE_PEER_ADDR:
            return same_store_address(&a->rpa_rec.peer_rpa_addr,&b->rpa_rec.peer_rpa_addr);
        default:
            return false;
    }
}
// Report only family and reason in our policy status. Return the original
// NimBLE/ESP error to the store caller; never emit addresses or record bytes.
enum { DURABLE_SIZE=1, DURABLE_NO_KEY, DURABLE_VALUE_DIFF, DURABLE_CANONICAL_DIFF };
static int durable_error_code(int type, int reason) {
    return -(0x5000 + 16*type + reason);
}
static int persistent_match(int type, const union ble_store_value *value, int *detail) {
    *detail=0;
    const char *prefix=store_prefix(type);
    if (!prefix) { return 0; }
    nvs_handle_t handle;
    int rc=nvs_open("nimble_bond",NVS_READONLY,&handle);
    if (rc) { return rc; }
    unsigned limit=type==BLE_STORE_OBJ_TYPE_CCCD ? 24 : 8;
    int result=BLE_HS_ESTORE_FAIL, reason=DURABLE_NO_KEY;
    for (unsigned i=1;i<=limit;i++) {
        char key[16]; snprintf(key,sizeof(key),"%s_%u",prefix,i);
        union ble_store_value saved; memset(&saved,0,sizeof(saved));
        size_t size=store_size(type);
        rc=nvs_get_blob(handle,key,&saved,&size);
        if (rc==ESP_ERR_NVS_NOT_FOUND) { continue; }
        if (rc || size!=store_size(type)) {
            reason=(!rc || rc==ESP_ERR_NVS_INVALID_LENGTH) ? DURABLE_SIZE : 0;
            result=rc ? rc : BLE_HS_ESTORE_FAIL; break;
        }
        if (same_store_record(type,&saved,value)) { result=0; reason=0; break; }
        if (same_store_key(type,&saved,value)) { reason=DURABLE_VALUE_DIFF; }
    }
    if (reason) { *detail=durable_error_code(type,reason); }
    nvs_close(handle); return result;
}

// Forget runs only on the serialized host task. The host lock keeps each RAM
// family stable while its exact persistent keys are validated and removed.
static int forget_ram_count(int type, unsigned *count) {
    int value;
    switch (type) {
        case BLE_STORE_OBJ_TYPE_OUR_SEC: value=ble_store_config_num_our_secs; break;
        case BLE_STORE_OBJ_TYPE_PEER_SEC: value=ble_store_config_num_peer_secs; break;
        case BLE_STORE_OBJ_TYPE_CCCD: value=ble_store_config_num_cccds; break;
        case BLE_STORE_OBJ_TYPE_CSFC: value=ble_store_config_num_csfcs; break;
        case BLE_STORE_OBJ_TYPE_PEER_ADDR: value=ble_store_config_num_rpa_recs; break;
        default: return HP_STORAGE;
    }
    unsigned limit=type==BLE_STORE_OBJ_TYPE_CCCD ? 24 : 8;
    if (value<0 || (unsigned)value>limit) { return HP_STORAGE; }
    *count=(unsigned)value; return 0;
}
static int forget_ram_row(int type, unsigned index, union ble_store_value *row) {
    memset(row,0,sizeof(*row));
    if (type==BLE_STORE_OBJ_TYPE_PEER_ADDR) {
        *row=(union ble_store_value){.rpa_rec=ble_store_config_rpa_recs[index]};
        return 0;
    }
    union ble_store_key key; memset(&key,0,sizeof(key));
    if (type==BLE_STORE_OBJ_TYPE_CCCD) { key.cccd.peer_addr=*BLE_ADDR_ANY; key.cccd.idx=index; }
    else if (type==BLE_STORE_OBJ_TYPE_CSFC) { key.csfc.peer_addr=*BLE_ADDR_ANY; key.csfc.idx=index; }
    else { key.sec.peer_addr=*BLE_ADDR_ANY; key.sec.idx=index; }
    return ble_store_config_read(type,&key,row);
}
static bool forget_target(int type, const union ble_store_value *row, const hp_address_t *target) {
    const ble_addr_t *native=type==BLE_STORE_OBJ_TYPE_PEER_ADDR ? &row->rpa_rec.peer_addr :
        type==BLE_STORE_OBJ_TYPE_CCCD ? &row->cccd.peer_addr :
        type==BLE_STORE_OBJ_TYPE_CSFC ? &row->csfc.peer_addr : &row->sec.peer_addr;
    hp_address_t a=address(native);
    return hp_address_equal(&a,target);
}
static bool forget_key_matches(int type, const union ble_store_value *key_row,
    const union ble_store_value *other) {
    if (type==BLE_STORE_OBJ_TYPE_PEER_ADDR) {
        hp_address_t key=address(&key_row->rpa_rec.peer_rpa_addr);
        hp_address_t rpa=address(&other->rpa_rec.peer_rpa_addr), peer=address(&other->rpa_rec.peer_addr);
        // Real RPA keys need exact comparison; identity aliases additionally
        // compare normalized forms, without treating an RPA as a host ID.
        return same_store_address(&key_row->rpa_rec.peer_rpa_addr,&other->rpa_rec.peer_rpa_addr) ||
            same_store_address(&key_row->rpa_rec.peer_rpa_addr,&other->rpa_rec.peer_addr) ||
            hp_address_equal(&key,&rpa) || hp_address_equal(&key,&peer);
    }
    if (type==BLE_STORE_OBJ_TYPE_CSFC) {
        hp_address_t a=address(&key_row->csfc.peer_addr), b=address(&other->csfc.peer_addr);
        return hp_address_equal(&a,&b);
    }
    if (type==BLE_STORE_OBJ_TYPE_CCCD) {
        return same_store_address(&key_row->cccd.peer_addr,&other->cccd.peer_addr) &&
            (!key_row->cccd.chr_val_handle || key_row->cccd.chr_val_handle==other->cccd.chr_val_handle);
    }
    return same_store_key(type,key_row,other);
}
static int forget_family(nvs_handle_t handle, int type, const hp_address_t *target,
    bool require_absent) {
    unsigned count; int rc=forget_ram_count(type,&count);
    if (rc) { return rc; }
    uint32_t matched=0; unsigned saved_count=0;
    unsigned limit=type==BLE_STORE_OBJ_TYPE_CCCD ? 24 : 8;
    for (unsigned slot=1;slot<=limit;slot++) {
        char key[16]; snprintf(key,sizeof(key),"%s_%u",store_prefix(type),slot);
        union ble_store_value saved; memset(&saved,0,sizeof(saved));
        size_t size=store_size(type);
        rc=nvs_get_blob(handle,key,&saved,&size);
        if (rc==ESP_ERR_NVS_NOT_FOUND) { continue; }
        if (rc) { return rc==ESP_ERR_NVS_INVALID_LENGTH ? HP_STORAGE : rc; }
        if (size!=store_size(type)) { return HP_STORAGE; }
        unsigned matches=0, found=0;
        for (unsigned i=0;i<count;i++) {
            union ble_store_value row;
            rc=forget_ram_row(type,i,&row);
            if (rc) { return rc; }
            if (same_store_record(type,&saved,&row)) { matches++; found=i; }
        }
        if (matches!=1 || (matched&(1u<<found))) { return HP_STORAGE; }
        matched|=1u<<found; saved_count++;
    }
    if (saved_count!=count || matched!=((1u<<count)-1u)) { return HP_STORAGE; }
    for (unsigned i=0;i<count;i++) {
        union ble_store_value row;
        rc=forget_ram_row(type,i,&row);
        if (rc) { return rc; }
        if (!forget_target(type,&row,target)) { continue; }
        if (require_absent) { return HP_STORAGE; }
        for (unsigned j=0;j<count;j++) {
            if (i==j) { continue; }
            union ble_store_value other;
            rc=forget_ram_row(type,j,&other);
            if (rc) { return rc; }
            if (forget_key_matches(type,&row,&other)) { return HP_STORAGE; }
        }
    }
    return 0;
}
static int forget_records(void *unused, const hp_address_t *target, bool apply) {
    (void)unused;
    static const int families[]={BLE_STORE_OBJ_TYPE_PEER_ADDR,BLE_STORE_OBJ_TYPE_CSFC,
        BLE_STORE_OBJ_TYPE_OUR_SEC,BLE_STORE_OBJ_TYPE_CCCD,BLE_STORE_OBJ_TYPE_PEER_SEC};
    int rc=0; nvs_handle_t handle;
    ble_hs_lock();
    rc=nvs_open("nimble_bond",apply ? NVS_READWRITE : NVS_READONLY,&handle);
    if (rc) { ble_hs_unlock(); return rc; }
    for (unsigned family=0;!rc && family<sizeof(families)/sizeof(families[0]);family++) {
        rc=forget_family(handle,families[family],target,false);
    }
    for (unsigned family=0;apply && !rc && family<sizeof(families)/sizeof(families[0]);family++) {
        int type=families[family];
        unsigned limit=type==BLE_STORE_OBJ_TYPE_CCCD ? 24 : 8;
        for (unsigned slot=1;!rc && slot<=limit;slot++) {
            char key[16]; snprintf(key,sizeof(key),"%s_%u",store_prefix(type),slot);
            union ble_store_value saved; memset(&saved,0,sizeof(saved));
            size_t size=store_size(type);
            rc=nvs_get_blob(handle,key,&saved,&size);
            if (rc==ESP_ERR_NVS_NOT_FOUND) { rc=0; continue; }
            if (rc) { break; }
            if (size!=store_size(type)) { rc=HP_STORAGE; break; }
            if (!forget_target(type,&saved,target)) { continue; }
            rc=nvs_erase_key(handle,key);
            if (!rc) { rc=nvs_commit(handle); }
            if (!rc) {
                union ble_store_value checked; size=store_size(type);
                int readback=nvs_get_blob(handle,key,&checked,&size);
                if (readback!=ESP_ERR_NVS_NOT_FOUND) { rc=readback ? readback : HP_STORAGE; }
            }
            if (rc) { break; }
            union ble_store_key native_key; ble_store_key_from_value(type,&native_key,&saved);
            rc=ble_store_config_delete(type,&native_key);
            if (rc) { break; }
            store_generation++;
            rc=forget_family(handle,type,target,false);
        }
    }
    for (unsigned family=0;apply && !rc && family<sizeof(families)/sizeof(families[0]);family++) {
        rc=forget_family(handle,families[family],target,true);
    }
    nvs_close(handle); ble_hs_unlock(); return rc;
}

typedef struct { hp_peer_t *peers; size_t count; unsigned cccds; int error; } peer_collect_t;
static int collect(int type, union ble_store_value *value, void *cookie) {
    peer_collect_t *ctx=cookie;
    hp_address_t raw=address(type==BLE_STORE_OBJ_TYPE_CCCD ? &value->cccd.peer_addr : &value->sec.peer_addr), a;
    if (!hp_normalize(&a,&raw)) { ctx->error=HP_INVALID; return BLE_HS_EINVAL; }
    size_t index=0;
    for (;index<ctx->count;index++) { if (hp_address_equal(&ctx->peers[index].address,&a)) { break; } }
    if (index==ctx->count) {
        if (ctx->count==HP_MAX_PEERS) { ctx->error=HP_CAPACITY; return BLE_HS_ESTORE_CAP; }
        ctx->count++; ctx->peers[index].address=a; ctx->peers[index].durable=true;
    }
    hp_peer_t *peer=&ctx->peers[index];
    if (type==BLE_STORE_OBJ_TYPE_OUR_SEC) { peer->our_sec=value->sec.ltk_present; }
    else if (type==BLE_STORE_OBJ_TYPE_PEER_SEC) { peer->peer_sec=value->sec.ltk_present || value->sec.irk_present; }
    else {
        ctx->cccds++;
        if ((value->cccd.flags&1) && (!core.hid_input_handle || core.hid_input_handle==value->cccd.chr_val_handle)) { peer->cccd=true; }
    }
    int detail;
    int durable_error=persistent_match(type,value,&detail);
    if (durable_error) { peer->durable=false; ctx->error=detail ? detail : durable_error; return durable_error; }
    return 0;
}
static int peers(void *unused, hp_peer_t *out, size_t *count, unsigned *cccds) {
    (void)unused;
    uint32_t before=store_generation;
    peer_collect_t ctx={.peers=out};
    for (unsigned i=0;i<3;i++) {
        int type=i==0 ? BLE_STORE_OBJ_TYPE_OUR_SEC : i==1 ? BLE_STORE_OBJ_TYPE_PEER_SEC : BLE_STORE_OBJ_TYPE_CCCD;
        int rc=ble_store_iterate(type,collect,&ctx);
        if (rc || ctx.error) { return ctx.error ? ctx.error : rc; }
    }
    if (before!=store_generation || ctx.count>*count) { return HP_STALE; }
    // Sorting makes snapshot generation stable across store enumeration order.
    for (size_t i=0;i<ctx.count;i++) {
        for (size_t j=i+1;j<ctx.count;j++) {
            if (hp_identity_id(&out[j].address)<hp_identity_id(&out[i].address)) { hp_peer_t temp=out[i]; out[i]=out[j]; out[j]=temp; }
        }
    }
    *count=ctx.count; *cccds=ctx.cccds; return 0;
}
typedef struct { hp_address_t target; bool found,irk_present; uint8_t irk[16]; unsigned checked; int error; } target_privacy_t;
static int target_privacy(int type, union ble_store_value *value, void *cookie) {
    (void)type; target_privacy_t *ctx=cookie;
    if (++ctx->checked>HP_MAX_PEERS) { ctx->error=HP_CAPACITY; return 1; }
    hp_address_t raw=address(&value->sec.peer_addr);
    if (!hp_address_equal(&raw,&ctx->target)) { return 0; }
    if (ctx->found && (ctx->irk_present!=value->sec.irk_present || (ctx->irk_present && memcmp(ctx->irk,value->sec.irk,16)))) { ctx->error=HP_INVALID; return 1; }
    ctx->found=true; ctx->irk_present=value->sec.irk_present;
    if (ctx->irk_present) { memcpy(ctx->irk,value->sec.irk,16); }
    return 0;
}
static int filter(void *unused, const hp_address_t *target) {
    (void)unused;
    // All procedures are stopped before configuring admission. Clear only the
    // CONTROLLER'S volatile resolving subset, never NVS bonds/local identity.
    int rc=ble_hs_pvcy_set_resolve_enabled(0);
    if (rc) { return rc; }
    rc=ble_hs_hci_cmd_tx(BLE_HCI_OP(BLE_HCI_OGF_LE,BLE_HCI_OCF_LE_CLR_RESOLV_LIST),NULL,0,NULL,0);
    if (rc) { return rc; }
    if (target) {
        ble_addr_t selected=native_address(target);
        target_privacy_t privacy; memset(&privacy,0,sizeof(privacy)); privacy.target=*target;
        // Match normalized identities, including PUBLIC_ID/RANDOM_ID store
        // types. An exact type0 lookup must not silently miss a type2 IRK.
        rc=ble_store_iterate(BLE_STORE_OBJ_TYPE_PEER_SEC,target_privacy,&privacy);
        if (rc || privacy.error) { memset(privacy.irk,0,sizeof(privacy.irk)); return rc ? rc : privacy.error; }
        // Checked insertion proves this target, rather than relying on sync's
        // best-effort all-peer restore. One selected entry avoids list overflow.
        rc=privacy.irk_present ? ble_hs_pvcy_add_entry(selected.val,selected.type,privacy.irk) : 0;
        memset(privacy.irk,0,sizeof(privacy.irk));
        if (rc) { return rc; }
        rc=ble_gap_wl_set(&selected,1);
    } else {
        rc=ble_gap_wl_set(NULL,0);
    }
    if (rc) { return rc; }
    return ble_hs_pvcy_set_resolve_enabled(1);
}
static int update_existing_cccd(const struct ble_store_value_cccd *existing,
    const struct ble_store_value_cccd *requested) {
    // NimBLE invokes the store callback under its host lock. Its pinned ESP
    // backend skips persistence for an equal CCCD count. Update just the
    // delivery marker under the same lock, without entering the NVS writer.
    if (!same_store_address(&existing->peer_addr,&requested->peer_addr) ||
        existing->chr_val_handle!=requested->chr_val_handle || existing->flags!=requested->flags) {
        int detail=durable_error_code(BLE_STORE_OBJ_TYPE_CCCD,DURABLE_VALUE_DIFF);
        fault(HP_DOMAIN_NVS,detail);
        return BLE_HS_ESTORE_FAIL;
    }
    if (existing->value_changed==requested->value_changed) { return 0; }
    struct ble_store_value_cccd *match=NULL;
    for (int i=0;i<ble_store_config_num_cccds;i++) {
        struct ble_store_value_cccd *row=&ble_store_config_cccds[i];
        if (!same_store_address(&row->peer_addr,&requested->peer_addr) ||
            row->chr_val_handle!=requested->chr_val_handle) { continue; }
        if (match || row->flags!=requested->flags) { return BLE_HS_EREJECT; }
        match=row;
    }
    if (!match) { return BLE_HS_ESTORE_FAIL; }
    match->value_changed=requested->value_changed;
    return 0;
}
static int guarded_write(int type, const union ble_store_value *value) {
    if (!check_store_guards()) { return BLE_HS_ESTORE_FAIL; }
    const char *prefix=store_prefix(type);
    if (core.enrollment_rejected && prefix && type!=BLE_STORE_OBJ_TYPE_LOCAL_IRK) { return BLE_HS_ESTORE_FAIL; }
    if (type==BLE_STORE_OBJ_TYPE_CCCD && (ble_store_config_num_cccds<0 ||
        ble_store_config_num_cccds>MYNEWT_VAL(BLE_STORE_MAX_CCCDS))) {
        fault(HP_DOMAIN_NVS,BLE_HS_ESTORE_FAIL);
        return BLE_HS_ESTORE_FAIL;
    }
    if (type==BLE_STORE_OBJ_TYPE_PEER_ADDR) {
        // The pinned SMP path writes a mapping even for a public or static
        // peer without an RPA. Its zero key can match another saved peer's
        // placeholder. An absent RPA has no mapping to store.
        static const uint8_t absent_rpa[6]={0};
        const ble_addr_t *rpa=&value->rpa_rec.peer_rpa_addr;
        if (memcmp(rpa->val,absent_rpa,sizeof(absent_rpa))==0) { return 0; }
        if (rpa->type!=BLE_ADDR_RANDOM || (rpa->val[5]&0xc0)!=0x40) {
            fault(HP_DOMAIN_SECURITY,HP_INVALID);
            return BLE_HS_ESTORE_FAIL;
        }
    }
    if (prefix && type!=BLE_STORE_OBJ_TYPE_LOCAL_IRK) {
        union ble_store_key key; union ble_store_value existing;
        memset(&key,0,sizeof(key)); memset(&existing,0,sizeof(existing));
        ble_store_key_from_value(type,&key,value);
        int found=ble_store_config_read(type,&key,&existing);
        if (found!=0 && found!=BLE_HS_ENOENT) { fault(HP_DOMAIN_NVS,found); return found; }
        if (type==BLE_STORE_OBJ_TYPE_CCCD && found==0) {
            return update_existing_cccd(&existing.cccd,&value->cccd);
        }
        if (type==BLE_STORE_OBJ_TYPE_PEER_ADDR && found==0) {
            if (!same_store_record(type,&existing,value)) {
                fault(HP_DOMAIN_SECURITY,HP_REPEAT_PAIR);
                return BLE_HS_ESTORE_FAIL;
            }
            int detail;
            int rc=persistent_match(type,&existing,&detail);
            if (rc) { fault(HP_DOMAIN_NVS,detail ? detail : rc); }
            return rc;
        }
        const ble_addr_t *peer=type==BLE_STORE_OBJ_TYPE_CCCD ? &value->cccd.peer_addr : type==BLE_STORE_OBJ_TYPE_CSFC ? &value->csfc.peer_addr : type==BLE_STORE_OBJ_TYPE_PEER_ADDR ? &value->rpa_rec.peer_addr : &value->sec.peer_addr;
        hp_address_t a=address(peer);
        bool security=type==BLE_STORE_OBJ_TYPE_OUR_SEC || type==BLE_STORE_OBJ_TYPE_PEER_SEC;
        bool same=found==0;
        if (same && security) {
            same=existing.sec.ltk_present==value->sec.ltk_present && existing.sec.irk_present==value->sec.irk_present && existing.sec.csrk_present==value->sec.csrk_present && existing.sec.key_size==value->sec.key_size && existing.sec.ediv==value->sec.ediv && existing.sec.rand_num==value->sec.rand_num &&
                 memcmp(existing.sec.ltk,value->sec.ltk,16)==0 && memcmp(existing.sec.irk,value->sec.irk,16)==0 && memcmp(existing.sec.csrk,value->sec.csrk,16)==0;
        }
        portENTER_CRITICAL(&policy_mux); bool blocked=command_queue.pending || processing || fault_pending; portEXIT_CRITICAL(&policy_mux);
        if (blocked || !hp_store_allowed(&core,&a,security,found==0,same)) { fault(HP_DOMAIN_SECURITY,HP_REPEAT_PAIR); return BLE_HS_ESTORE_FAIL; }
    } else if (type==BLE_STORE_OBJ_TYPE_LOCAL_IRK) {
        union ble_store_key key; union ble_store_value existing;
        memset(&key,0,sizeof(key)); memset(&existing,0,sizeof(existing));
        ble_store_key_from_value(type,&key,value);
        int found=ble_store_config_read(type,&key,&existing);
        if (found==0 && !same_store_record(type,&existing,value)) { fault(HP_DOMAIN_SECURITY,HP_REPEAT_PAIR); return BLE_HS_ESTORE_FAIL; }
        if (found!=0 && found!=BLE_HS_ENOENT) { fault(HP_DOMAIN_NVS,found); return found; }
    }
    int rc=ble_store_config_write(type,value), detail=0;
    if (!rc && prefix) {
        // The pinned store assigns bond_count during OUR_SEC/PEER_SEC writes.
        // Verify the canonical POST-write record, never the caller's old count.
        union ble_store_key key; union ble_store_value canonical, expected;
        memset(&key,0,sizeof(key)); memset(&canonical,0,sizeof(canonical));
        ble_store_key_from_value(type,&key,value);
        rc=ble_store_config_read(type,&key,&canonical);
        memset(&expected,0,sizeof(expected));
        // Public NimBLE write helpers may pass a smaller struct through a
        // union pointer. Never read sizeof(union) bytes from that argument.
        memcpy(&expected,value,store_size(type));
        if (type==BLE_STORE_OBJ_TYPE_OUR_SEC || type==BLE_STORE_OBJ_TYPE_PEER_SEC) { expected.sec.bond_count=canonical.sec.bond_count; }
        if (!rc && !same_store_record(type,&expected,&canonical)) {
            rc=BLE_HS_ESTORE_FAIL; detail=durable_error_code(type,DURABLE_CANONICAL_DIFF);
        }
        if (!rc) { rc=persistent_match(type,&canonical,&detail); }
        memset(&canonical,0,sizeof(canonical)); memset(&expected,0,sizeof(expected));
    }
    store_generation++;
    if (rc) { fault(HP_DOMAIN_NVS,detail ? detail : rc); }
    schedule(); return rc;
}
static int guarded_delete(int type, const union ble_store_key *key) {
    if (!check_store_guards()) { return BLE_HS_ESTORE_FAIL; }
    const char *prefix=store_prefix(type);
    if (core.enrollment_rejected && prefix && type!=BLE_STORE_OBJ_TYPE_LOCAL_IRK) { return BLE_HS_ESTORE_FAIL; }
    if (prefix && type!=BLE_STORE_OBJ_TYPE_PEER_ADDR) { fault(HP_DOMAIN_SECURITY,HP_REPEAT_PAIR); return BLE_HS_ESTORE_FAIL; }
    return ble_store_config_delete(type,key);
}
int bleio_host_policy_store_status(struct ble_store_status_event *event, void *arg) {
    (void)event; (void)arg;
    fault(HP_DOMAIN_NVS,BLE_HS_ESTORE_CAP);
    return BLE_HS_ESTORE_CAP; // FULL and OVERFLOW: never round-robin evict a bond/CCCD/CSFC.
}
void bleio_host_policy_install_store_guards(void) {
    // Allow the vendor's known store initialization, or an already intact
    // binding. An unknown callback must never become a write delegate.
    if (ble_hs_cfg.store_read_cb==ble_store_config_read &&
        ble_hs_cfg.store_write_cb==ble_store_config_write && ble_hs_cfg.store_delete_cb==ble_store_config_delete &&
        ble_hs_cfg.store_status_cb==bleio_host_policy_store_status) {
        ble_hs_cfg.store_write_cb=guarded_write;
        ble_hs_cfg.store_delete_cb=guarded_delete;
    }
    (void)check_store_guards();
}
static void service(struct ble_npl_event *event) {
    (void)event;
    if (!synced || !timer_ready) { return; }
    bool guards_ok=check_store_guards();
    policy_request_t local; bool has_request, has_fault; int error; hp_domain_t domain;
    portENTER_CRITICAL(&policy_mux);
    has_request=hp_pop(&command_queue,&local); processing=true;
    has_fault=fault_pending; error=pending_fault; domain=pending_fault_domain; fault_pending=false;
    policy_busy=has_request || has_fault;
    portEXIT_CRITICAL(&policy_mux);
    bool transitioning=has_request || has_fault || core.status.state==HP_SWITCHING;
    if (has_request || has_fault) { clear_inputs(); }
    if (has_fault) {
        if (guards_ok) { (void)release_old_input(); }
        hp_fail(&core,domain,error);
        // A command already queued BEFORE this fault is not a new recovery
        // intent. Publish its terminal error; never erase the fault by applying it.
        if (has_request) { core.status.operation_id=local.operation; if (!local.alias && !local.forget) { core.status.requested_mode=local.mode; } }
    } else if (has_request && guards_ok) {
        int release_error=release_old_input();
        if (release_error) { core.status.operation_id=local.operation; hp_fail(&core,HP_DOMAIN_NIMBLE,release_error); }
        else if (local.forget) { core.status.operation_id=local.operation; hp_forget(&core,local.target,local.generation); }
        else if (local.alias) { core.status.operation_id=local.operation; int rc=hp_set_alias(&core,local.target,local.text,local.length); if (rc) { hp_fail(&core,HP_DOMAIN_NVS,rc); } }
        else { hp_request(&core,local.mode,local.target,local.operation,local.timeout_s,millis()); }
    }
    if (guards_ok) { hp_tick(&core,millis()); }
    // A stop/filter transition and start must run in DIFFERENT NimBLE event
    // contexts. On the next tick, admission is re-evaluated, never cached on VM.
    if (!transitioning || !guards_ok) {
        portENTER_CRITICAL(&policy_mux);
        bool start_pending=advertising_request.active && !advertising_request.finished;
        bool cancelled=advertising_request.cancelled;
        uint32_t token=advertising_request.token;
        portEXIT_CRITICAL(&policy_mux);
        if (start_pending) {
            uint32_t rc=BLE_HS_EREJECT;
            if (guards_ok && !cancelled && hp_advertising_allowed(&core)) {
                common_hal_bleio_adapter_obj.user_advertising=advertising_request.user_owned;
                rc=advertising_request.start(&common_hal_bleio_adapter_obj,
                    advertising_request.connectable,advertising_request.anonymous,
                    advertising_request.timeout,advertising_request.interval,
                    advertising_request.data,advertising_request.data_length,
                    advertising_request.response,advertising_request.response_length,
                    advertising_request.power,NULL);
            }
            portENTER_CRITICAL(&policy_mux);
            cancelled=advertising_request.cancelled || advertising_request.token!=token;
            portEXIT_CRITICAL(&policy_mux);
            if (guards_ok && (cancelled || rc)) {
                int stopped=stop_advertising(NULL);
                if ((cancelled || (rc!=BLE_HS_EREJECT) || stopped) && core.status.state!=HP_ERROR) { hp_fail(&core,HP_DOMAIN_NIMBLE,stopped ? stopped : cancelled ? BLE_HS_ETIMEOUT : (int)rc); }
                rc=cancelled ? BLE_HS_ETIMEOUT : rc;
            }
            portENTER_CRITICAL(&policy_mux);
            if (advertising_request.token==token) {
                advertising_request.result=rc; advertising_request.finished=true;
                if (advertising_request.waiter_gone) { advertising_request.active=false; }
            }
            portEXIT_CRITICAL(&policy_mux);
        }
    }
    // Bounded FIFO service, no ENOMEM retry, no waits and no VM pointers.
    for (unsigned i=0;guards_ok && i<4;i++) {
        hp_input_report_t report;
        portENTER_CRITICAL(&policy_mux);
        bool have=!command_queue.pending && !fault_pending && hp_pop_input(&input_queue,&report);
        portEXIT_CRITICAL(&policy_mux);
        if (!have) { break; }
        if (!hp_input_current(&core,&report)) { continue; }
        int rc=submit_input(&report);
        if (rc) { clear_inputs(); hp_fail(&core,HP_DOMAIN_NIMBLE,rc); break; }
    }
    publish();
    int timer_error=synced ? ble_npl_callout_reset(&policy_timer,ble_npl_time_ms_to_ticks32(100)) : 0;
    if (timer_error) {
        timer_ready=false;
        clear_inputs();
        if (guards_ok) { (void)release_old_input(); hp_fail(&core,HP_DOMAIN_NIMBLE,timer_error); }
        publish();
    }
    portENTER_CRITICAL(&policy_mux); processing=false; policy_busy=false; portEXIT_CRITICAL(&policy_mux);
}
static int reserve_enrollment(void *unused) {
    (void)unused;
    // OUR/PEER bond and CCCD limits are checked by the core. Also reserve one
    // CSFC and one RPA mapping before any new SMP record can be written.
    int types[]={BLE_STORE_OBJ_TYPE_OUR_SEC,BLE_STORE_OBJ_TYPE_PEER_SEC,BLE_STORE_OBJ_TYPE_CSFC};
    for (unsigned i=0;i<sizeof(types)/sizeof(types[0]);i++) {
        int count=0,rc=ble_store_util_count(types[i],&count);
        if (rc) { return rc; }
        if (count<0 || count>=HP_MAX_PEERS) { return BLE_HS_ESTORE_CAP; }
    }
    // The vendor RPA lookup treats BLE_ADDR_ANY as an exact key, so the
    // generic iterator cannot establish how many private mappings exist.
    ble_hs_lock();
    int rpa_count=ble_store_config_num_rpa_recs;
    ble_hs_unlock();
    return rpa_count<0 || rpa_count>=HP_MAX_PEERS ? BLE_HS_ESTORE_CAP : 0;
}
void bleio_host_policy_init(int nvs_error) {
    if (initialized) { return; }
    hp_backend_t backend={.persist=persist,.stop_advertising=stop_advertising,.terminate=terminate,.filter=filter,.peers=peers,.reserve_enrollment=reserve_enrollment,.forget=forget_records};
    hp_blob_t blob; memset(&blob,0,sizeof(blob)); bool present=false;
    if (!nvs_error) {
        nvs_handle_t handle; int rc=nvs_open("bm83_hid_policy",NVS_READONLY,&handle);
        if (!rc) { size_t size=sizeof(blob); rc=nvs_get_blob(handle,"policy_v1",&blob,&size); present=rc==ESP_OK; if (present && size!=sizeof(blob)) { nvs_error=ESP_ERR_NVS_INVALID_LENGTH; } nvs_close(handle); }
        if (rc!=ESP_OK && rc!=ESP_ERR_NVS_NOT_FOUND) { nvs_error=rc; }
    }
    hp_init(&core,&backend,present ? &blob : NULL,nvs_error);
    initialized=true; publish();
}
void bleio_host_policy_sync(void) {
    // Default-IRK setup can reinitialize the vendor store before this callback.
    // Bind again before the adapter publishes readiness to CircuitPython.
    synced=false;
    bleio_host_policy_install_store_guards();
    if (timer_initialized) { ble_npl_callout_stop(&policy_timer); }
    int timer_error=timer_initialized ? 0 :
        ble_npl_callout_init(&policy_timer,nimble_port_get_dflt_eventq(),service,NULL);
    if (timer_error) { timer_ready=false; hp_fail(&core,HP_DOMAIN_NIMBLE,timer_error); publish(); return; }
    timer_initialized=true;
    clear_inputs();
    core.status.filter_ready=false;
    core.status.hid_ready=false;
    if (!store_guard_failed) {
        int rc=hp_refresh(&core);
        if (rc) { hp_fail(&core,HP_DOMAIN_NVS,rc); }
        else if (core.status.state!=HP_ERROR) {
            core.status.applied_mode=HP_PAUSED;
            core.status.state=HP_SWITCHING;
        }
    }
    timer_error=ble_npl_callout_reset(&policy_timer,ble_npl_time_ms_to_ticks32(100));
    timer_ready=timer_error==0;
    if (timer_error) { hp_fail(&core,HP_DOMAIN_NIMBLE,timer_error); }
    publish();
    synced=timer_ready;
}
void bleio_host_policy_disabled(void) {
    synced=false;
    timer_ready=false;
    if (timer_initialized) { ble_npl_callout_stop(&policy_timer); }
    clear_inputs();
}
void bleio_host_policy_deinit(void) {
    // Adapter calls this after the host task has exited, before its event
    // queue and allocator are released by nimble_port_deinit().
    if (timer_initialized) {
        ble_npl_callout_deinit(&policy_timer);
        timer_initialized=false;
    }
}
int bleio_host_policy_advertising_guard(void) {
    // Called only by the raw start on the serialized host task. Actual policy
    // transitions and expiry cannot interleave this check and GAP submission.
    return synced && timer_ready && check_store_guards() && hp_advertising_allowed(&core) ? (int)core.status.applied_mode : -1;
}
uint32_t bleio_host_policy_advertising_timeout_ms(uint32_t requested_ms) {
    if (core.status.applied_mode!=HP_ENROLL) { return requested_ms; }
    uint64_t now=millis();
    uint32_t remaining=now<core.deadline_ms ? (uint32_t)(core.deadline_ms-now) : 1;
    return requested_ms==0 || requested_ms>remaining ? remaining : requested_ms;
}
uint32_t bleio_host_policy_start_advertising(bleio_adapter_obj_t *self, bool connectable, bool anonymous,
    uint32_t timeout, float interval, const uint8_t *data, uint16_t length,
    const uint8_t *response, uint16_t response_length, mp_int_t power,
    const bleio_address_obj_t *directed_to, hp_raw_advertise_fn start) {
    if (self!=&common_hal_bleio_adapter_obj || directed_to!=NULL || anonymous || length>HP_ADV_MAX_BYTES || response_length>HP_ADV_MAX_BYTES) { return BLE_HS_EINVAL; }
    if (!synced || !check_store_guards()) { return BLE_HS_EREJECT; }
    portENTER_CRITICAL(&policy_mux);
    if (!synced || !timer_ready || command_queue.pending || fault_pending || store_guard_failed || !observed.filter_ready || observed.applied_mode==HP_PAUSED || observed.state==HP_ERROR) { portEXIT_CRITICAL(&policy_mux); return BLE_HS_EREJECT; }
    if (advertising_request.active) { portEXIT_CRITICAL(&policy_mux); return BLE_HS_EBUSY; }
    uint32_t token=++next_advertising_token;
    if (!token) { token=++next_advertising_token; }
    // Only fixed native arrays survive the cooperative wait, never VM pointers.
    advertising_request.active=true; advertising_request.finished=false;
    advertising_request.cancelled=false; advertising_request.waiter_gone=false;
    advertising_request.token=token; advertising_request.connectable=connectable;
    advertising_request.anonymous=anonymous; advertising_request.timeout=timeout;
    advertising_request.interval=interval; advertising_request.power=power;
    advertising_request.data_length=length; advertising_request.response_length=response_length;
    advertising_request.user_owned=self->user_advertising; advertising_request.start=start;
    if (length) { memcpy(advertising_request.data,data,length); }
    if (response_length) { memcpy(advertising_request.response,response,response_length); }
    portEXIT_CRITICAL(&policy_mux);
    uint64_t deadline=millis()+HP_ADV_VM_WAIT_MS;
    for (;;) {
        portENTER_CRITICAL(&policy_mux);
        if (advertising_request.token==token && advertising_request.finished) {
            uint32_t rc=advertising_request.result; advertising_request.active=false;
            portEXIT_CRITICAL(&policy_mux); return rc;
        }
        if (millis()>=deadline || mp_hal_is_interrupted()) {
            advertising_request.cancelled=true; advertising_request.waiter_gone=true;
            portEXIT_CRITICAL(&policy_mux); return BLE_HS_ETIMEOUT;
        }
        portEXIT_CRITICAL(&policy_mux);
        RUN_BACKGROUND_TASKS;
        common_hal_time_delay_ms(1);
    }
}
bool bleio_host_policy_input_guard(uint16_t handle) {
    if (!synced || !check_store_guards()) { return false; }
    portENTER_CRITICAL(&policy_mux);
    bool allowed=synced && timer_ready && !command_queue.pending && !policy_busy && !fault_pending && !store_guard_failed && observed.hid_ready && observed.connected && observed.encrypted && observed.bonded && observed.state==HP_CONNECTED && observed.applied_mode==HP_AUTO && observed_handle==handle && observed.connected_id==observed.target_id;
    portEXIT_CRITICAL(&policy_mux); return allowed;
}
int bleio_host_policy_queue_input(uint16_t handle, uint16_t attribute, const uint8_t *data, size_t length) {
    if (!synced || !check_store_guards()) { return BLE_HS_EREJECT; }
    portENTER_CRITICAL(&policy_mux);
    bool origin_current=input_origin_valid && input_origin.operation_id==observed.operation_id &&
        input_origin.policy_generation==observed.policy_generation && input_origin.connection_generation==observed.connection_generation &&
        input_origin.subscription_generation==observed.subscription_generation && input_origin.target_id==observed.target_id &&
        origin_handle==observed_handle && origin_input_handle==observed_input_handle && observed.hid_ready;
    int rc=!synced || !timer_ready || command_queue.pending || policy_busy || fault_pending || store_guard_failed || !origin_current ? HP_UNAUTHORIZED :
        hp_queue_input(&input_queue,&input_origin,origin_handle,origin_input_handle,handle,attribute,data,length);
    portEXIT_CRITICAL(&policy_mux);
    if (rc==HP_QUEUE_FULL) { fault(HP_DOMAIN_NIMBLE,BLE_HS_ENOMEM); return BLE_HS_ENOMEM; }
    return rc ? BLE_HS_EREJECT : 0;
}
mp_obj_t bleio_host_policy_arm_input(mp_obj_t operation, mp_obj_t policy, mp_obj_t connection, mp_obj_t subscription) {
    if (!synced || !check_store_guards()) { return mp_obj_new_bool(false); }
    hp_status_t expected;
    portENTER_CRITICAL(&policy_mux); expected=observed; portEXIT_CRITICAL(&policy_mux);
    // Exact arbitrary-Python-int equality avoids truncating a supplied epoch.
    // All VM allocation/comparison is OUTSIDE the native snapshot lock.
    bool equal=mp_obj_is_int(operation) && mp_obj_is_int(policy) && mp_obj_is_int(connection) && mp_obj_is_int(subscription) &&
        mp_obj_equal(operation,mp_obj_new_int_from_uint(expected.operation_id)) &&
        mp_obj_equal(policy,mp_obj_new_int_from_uint(expected.policy_generation)) &&
        mp_obj_equal(connection,mp_obj_new_int_from_uint(expected.connection_generation)) &&
        mp_obj_equal(subscription,mp_obj_new_int_from_uint(expected.subscription_generation));
    portENTER_CRITICAL(&policy_mux);
    bool allowed=equal && synced && timer_ready && !command_queue.pending && !policy_busy && !fault_pending && !store_guard_failed &&
        observed.state==HP_CONNECTED && observed.applied_mode==HP_AUTO && observed.hid_ready && observed.connected && observed.encrypted && observed.bonded && observed.connected_id==observed.target_id &&
        observed.operation_id==expected.operation_id && observed.policy_generation==expected.policy_generation &&
        observed.connection_generation==expected.connection_generation && observed.subscription_generation==expected.subscription_generation;
    input_origin_valid=allowed;
    if (allowed) { input_origin=expected; origin_handle=observed_handle; origin_input_handle=observed_input_handle; }
    portEXIT_CRITICAL(&policy_mux); return mp_obj_new_bool(allowed);
}
bool bleio_host_policy_input_value(uint16_t handle, uint16_t attribute, uint8_t *out, size_t length) {
    if (length>HP_INPUT_BYTES) { return false; }
    memset(out,0,length);
    portENTER_CRITICAL(&policy_mux);
    bool valid=last_input_valid && !command_queue.pending && !fault_pending && !policy_busy && !store_guard_failed &&
        observed.hid_ready && observed.connected && observed_handle==handle && observed_input_handle==attribute &&
        last_input.handle==handle && last_input.attribute==attribute && last_input.length==length &&
        last_input.connection_generation==observed.connection_generation && last_input.policy_generation==observed.policy_generation &&
        last_input.subscription_generation==observed.subscription_generation &&
        last_input.operation==observed.operation_id && last_input.identity==observed.target_id;
    if (valid) { memcpy(out,last_input.data,length); }
    portEXIT_CRITICAL(&policy_mux); return true;
}
typedef struct { uint8_t rpa[6]; hp_address_t identity; bool found; int error; unsigned checked; } resolution_t;
static int resolve_saved(int type, union ble_store_value *value, void *cookie) {
    (void)type; resolution_t *ctx=cookie;
    if (++ctx->checked>HP_MAX_PEERS) { ctx->error=HP_CAPACITY; return 1; }
    if (!value->sec.irk_present) { return 0; }
    uint8_t hash[3]; int rc=ble_hs_pvcy_rpa_ah(value->sec.irk,ctx->rpa+3,hash);
    if (rc) { ctx->error=rc; return 1; }
    if (memcmp(hash,ctx->rpa,3)) { return 0; }
    hp_address_t raw=address(&value->sec.peer_addr), normalized;
    if (!hp_normalize(&normalized,&raw) || (ctx->found && !hp_address_equal(&ctx->identity,&normalized))) { ctx->error=HP_INVALID; return 1; }
    ctx->identity=normalized; ctx->found=true; return 0;
}
uint32_t bleio_host_policy_connect(uint16_t handle) {
    if (!synced || !check_store_guards()) { terminate(NULL,handle); return 0; }
    portENTER_CRITICAL(&policy_mux); processing=true; portEXIT_CRITICAL(&policy_mux);
    struct ble_gap_conn_desc desc;
    if (ble_gap_conn_find(handle,&desc)) { terminate(NULL,handle); portENTER_CRITICAL(&policy_mux); processing=false; portEXIT_CRITICAL(&policy_mux); return 0; }
    hp_address_t a=address(&desc.peer_id_addr);
    hp_address_t normalized;
    if (!hp_normalize(&normalized,&a) && desc.peer_ota_addr.type==BLE_ADDR_RANDOM && (desc.peer_ota_addr.val[5]&0xc0)==0x40) {
        // ENROLL clears the volatile resolving subset. Recognize and refuse an
        // existing bonded host's RPA before it can latch the new-host slot.
        // Bounded eight-record native software resolution; no keys leave C.
        resolution_t ctx; memset(&ctx,0,sizeof(ctx)); memcpy(ctx.rpa,desc.peer_ota_addr.val,6);
        int rc=ble_store_iterate(BLE_STORE_OBJ_TYPE_PEER_SEC,resolve_saved,&ctx);
        if (rc || ctx.error) {
            terminate(NULL,handle); fault(HP_DOMAIN_SECURITY,rc ? rc : ctx.error);
            portENTER_CRITICAL(&policy_mux); processing=false; portEXIT_CRITICAL(&policy_mux); return 0;
        }
        if (ctx.found) { a=ctx.identity; }
    }
    uint32_t generation=hp_connect(&core,handle,&a); if (generation) { clear_inputs(); } publish(); portENTER_CRITICAL(&policy_mux); processing=false; portEXIT_CRITICAL(&policy_mux); return generation;
}
void bleio_host_policy_connection_attach_failed(uint16_t handle, uint32_t generation, int error) {
    if (handle!=core.handle || !generation || generation!=core.status.connection_generation) { return; }
    clear_inputs();
    if (error==BLE_HS_ENOTCONN) {
        // Callback registration confirms the raw link is already absent.
        hp_disconnect(&core,handle,generation,error);
    } else {
        hp_fail(&core,HP_DOMAIN_NIMBLE,error);
    }
    publish();
}
void bleio_host_policy_event(struct ble_gap_event *event, uint32_t generation) {
    bool connect_failed=event->type==BLE_GAP_EVENT_CONNECT && event->connect.status!=0;
    if (!connect_failed && event->type!=BLE_GAP_EVENT_DISCONNECT && event->type!=BLE_GAP_EVENT_IDENTITY_RESOLVED && event->type!=BLE_GAP_EVENT_ENC_CHANGE && event->type!=BLE_GAP_EVENT_REPEAT_PAIRING) { return; }
    if (!check_store_guards() && !connect_failed && event->type!=BLE_GAP_EVENT_DISCONNECT) { return; }
    portENTER_CRITICAL(&policy_mux); processing=true; portEXIT_CRITICAL(&policy_mux);
    hp_status_t before=core.status;
    struct ble_gap_conn_desc desc; uint16_t handle=HP_INVALID_HANDLE;
    switch(event->type) {
        case BLE_GAP_EVENT_CONNECT:
            // NimBLE reports an early peripheral link loss as CONNECT failure
            // and suppresses DISCONNECT until its first successful CONNECT.
            hp_disconnect(&core,event->connect.conn_handle,generation,event->connect.status); break;
        case BLE_GAP_EVENT_DISCONNECT:
            hp_disconnect(&core,event->disconnect.conn.conn_handle,generation,event->disconnect.reason); break;
        case BLE_GAP_EVENT_IDENTITY_RESOLVED:
            handle=event->identity_resolved.conn_handle;
            if (handle!=core.handle || generation!=core.status.connection_generation || core.enrollment_rejected) { break; }
            if (!ble_gap_conn_find(handle,&desc)) { hp_address_t a=address(&desc.peer_id_addr); hp_identity(&core,handle,generation,&a); } else { fault(HP_DOMAIN_SECURITY,HP_UNAUTHORIZED); }
            break;
        case BLE_GAP_EVENT_ENC_CHANGE:
            handle=event->enc_change.conn_handle;
            if (handle!=core.handle || generation!=core.status.connection_generation || core.enrollment_rejected) { break; }
            if (!ble_gap_conn_find(handle,&desc)) { hp_address_t a=address(&desc.peer_id_addr); hp_identity(&core,handle,generation,&a); hp_security(&core,handle,generation,desc.sec_state.encrypted,desc.sec_state.bonded,event->enc_change.status); } else { fault(HP_DOMAIN_SECURITY,HP_UNAUTHORIZED); }
            break;
        case BLE_GAP_EVENT_REPEAT_PAIRING:
            handle=event->repeat_pairing.conn_handle;
            if (handle==core.handle && generation==core.status.connection_generation && core.status.state!=HP_ERROR &&
                !hp_reject_enrollment_link(&core,handle,generation)) { fault(HP_DOMAIN_SECURITY,HP_REPEAT_PAIR); }
            break;
        default: return;
    }
    if (before.connection_generation!=core.status.connection_generation || before.connected_id!=core.status.connected_id || before.connected!=core.status.connected || before.encrypted!=core.status.encrypted || before.bonded!=core.status.bonded || before.state!=core.status.state) { clear_inputs(); }
    publish(); portENTER_CRITICAL(&policy_mux); processing=false; portEXIT_CRITICAL(&policy_mux); schedule();
}
void bleio_host_policy_subscription(uint16_t handle, uint32_t generation, uint16_t input_handle, bool enabled) {
    if (!synced || !check_store_guards()) { return; }
    portENTER_CRITICAL(&policy_mux); processing=true; portEXIT_CRITICAL(&policy_mux);
    uint32_t before=core.status.subscription_generation;
    hp_subscribe(&core,handle,generation,input_handle,enabled); if (before!=core.status.subscription_generation) { clear_inputs(); } publish(); portENTER_CRITICAL(&policy_mux); processing=false; portEXIT_CRITICAL(&policy_mux); schedule();
}
static uint64_t parse_id(mp_obj_t value, bool optional) {
    if (value==mp_const_none && optional) { return 0; }
    if (!mp_obj_is_str(value)) { mp_raise_ValueError(MP_ERROR_TEXT("Host id must be text")); }
    size_t length; const char *text=mp_obj_str_get_data(value,&length);
    if (length!=16) { mp_raise_ValueError(MP_ERROR_TEXT("Host id must contain 16 lowercase hex digits")); }
    uint64_t result=0;
    for (unsigned i=0;i<16;i++) { unsigned digit=text[i]>='0' && text[i]<='9' ? text[i]-'0' : text[i]>='a' && text[i]<='f' ? text[i]-'a'+10 : 16; if (digit>15) { mp_raise_ValueError(MP_ERROR_TEXT("Invalid host id")); } result=(result<<4)|digit; }
    if (!result) { mp_raise_ValueError(MP_ERROR_TEXT("Invalid host id")); } return result;
}
static mp_obj_t id_object(uint64_t id) { if (!id) { return mp_const_none; } char text[17]; snprintf(text,sizeof(text),"%016" PRIx64,id); return mp_obj_new_str(text,16); }
static mp_obj_t enqueue(policy_request_t *next) {
    if (!synced || !timer_ready || !check_store_guards()) { mp_raise_RuntimeError(MP_ERROR_TEXT("BLE host policy unavailable")); }
    portENTER_CRITICAL(&policy_mux);
    if (store_guard_failed) { portEXIT_CRITICAL(&policy_mux); mp_raise_RuntimeError(MP_ERROR_TEXT("BLE host policy unavailable")); }
    int rc=hp_submit(&command_queue,next);
    if (rc) { portEXIT_CRITICAL(&policy_mux); mp_raise_RuntimeError(MP_ERROR_TEXT("BLE host policy queue full")); }
    hp_clear_input(&input_queue);
    input_origin_valid=false;
    portEXIT_CRITICAL(&policy_mux); schedule(); return mp_obj_new_int_from_uint(next->operation);
}
mp_obj_t bleio_host_policy_request(mp_obj_t mode, mp_obj_t target, mp_int_t timeout_s) {
    policy_request_t next; memset(&next,0,sizeof(next));
    if (!mp_obj_is_str(mode)) { mp_raise_ValueError(MP_ERROR_TEXT("Host policy must be text")); }
    const char *name=mp_obj_str_get_str(mode);
    if (!strcmp(name,"PAUSED")) { next.mode=HP_PAUSED; }
    else if (!strcmp(name,"AUTO")) { next.mode=HP_AUTO; }
    else if (!strcmp(name,"ENROLL")) { next.mode=HP_ENROLL; }
    else { mp_raise_ValueError(MP_ERROR_TEXT("Unknown BLE host policy")); }
    next.target=parse_id(target,true);
    if ((next.mode!=HP_AUTO && next.target) || timeout_s<5 || timeout_s>120) { mp_raise_ValueError(MP_ERROR_TEXT("Invalid host policy target or timeout")); }
    next.timeout_s=(uint32_t)timeout_s; return enqueue(&next);
}
mp_obj_t bleio_host_policy_alias(mp_obj_t target, mp_obj_t alias) {
    policy_request_t next; memset(&next,0,sizeof(next)); next.alias=true; next.target=parse_id(target,false);
    if (!mp_obj_is_str(alias)) { mp_raise_ValueError(MP_ERROR_TEXT("Host alias must be text")); }
    const char *text=mp_obj_str_get_data(alias,&next.length);
    if (!hp_alias_valid(text,next.length)) { mp_raise_ValueError(MP_ERROR_TEXT("Host alias must be printable UTF-8, at most 24 bytes")); }
    memcpy(next.text,text,next.length); return enqueue(&next);
}
mp_obj_t bleio_host_policy_forget(mp_obj_t target, mp_obj_t generation) {
    policy_request_t next; memset(&next,0,sizeof(next)); next.forget=true;
    next.target=parse_id(target,false);
    hp_status_t status; uint16_t handle; bool busy, available;
    portENTER_CRITICAL(&policy_mux);
    status=observed; handle=observed_handle;
    busy=command_queue.pending || processing || policy_busy || fault_pending || store_guard_failed ||
        (advertising_request.active && !advertising_request.finished);
    available=initialized && synced && timer_ready;
    portEXIT_CRITICAL(&policy_mux);
    // VM object conversion, exceptions and stack inspection stay outside mux.
    if (!available || busy || !hp_forget_allowed(&status,handle) ||
        !mp_obj_is_int(generation) ||
        !mp_obj_equal(generation,mp_obj_new_int_from_uint(status.bond_generation))) {
        mp_raise_ValueError(MP_ERROR_TEXT("Forget requires clean PAUSED and the current bond generation"));
    }
    #if MYNEWT_VAL(BLE_EXT_ADV)
    bool advertising=ble_gap_ext_adv_active(0);
    #else
    bool advertising=ble_gap_adv_active();
    #endif
    if (advertising) { mp_raise_ValueError(MP_ERROR_TEXT("Disconnect before forgetting a saved host")); }
    next.generation=status.bond_generation;
    return enqueue(&next);
}
static void put(mp_obj_t dict, qstr key, mp_obj_t value) { mp_obj_dict_store(dict,MP_OBJ_NEW_QSTR(key),value); }
mp_obj_t bleio_host_policy_peers(void) {
    hp_peer_t peers_copy[HP_MAX_PEERS]; size_t count; hp_status_t status;
    portENTER_CRITICAL(&policy_mux); count=observed_count; status=observed; memcpy(peers_copy,observed_peers,sizeof(peers_copy)); portEXIT_CRITICAL(&policy_mux);
    mp_obj_t items[HP_MAX_PEERS];
    for (size_t i=0;i<count;i++) {
        hp_peer_t *peer=&peers_copy[i]; mp_obj_t item=mp_obj_new_dict(0);
        put(item,MP_QSTR_id,id_object(peer->id)); put(item,MP_QSTR_alias,mp_obj_new_str(peer->alias,strlen(peer->alias)));
        put(item,MP_QSTR_generation,mp_obj_new_int_from_uint(status.bond_generation));
        put(item,MP_QSTR_our_sec,mp_obj_new_bool(peer->our_sec)); put(item,MP_QSTR_peer_sec,mp_obj_new_bool(peer->peer_sec));
        put(item,MP_QSTR_cccd,mp_obj_new_bool(peer->cccd)); put(item,MP_QSTR_resumable,mp_obj_new_bool(peer->our_sec && peer->durable));
        put(item,MP_QSTR_connected,mp_obj_new_bool(status.connected && status.connected_id==peer->id)); items[i]=item;
    }
    return mp_obj_new_tuple(count,items);
}
mp_obj_t bleio_host_policy_status(void) {
    hp_status_t status; bool request_pending;
    portENTER_CRITICAL(&policy_mux); status=observed; request_pending=command_queue.pending || policy_busy || fault_pending; portEXIT_CRITICAL(&policy_mux);
    static const char *modes[]={"PAUSED","AUTO","ENROLL"};
    static const char *states[]={"PAUSED","SWITCHING","WAITING","ENROLLING","CONNECTED","ERROR"};
    static const char *domains[]={"NONE","POLICY","NVS","NIMBLE","SECURITY"};
    mp_obj_t result=mp_obj_new_dict(0);
    put(result,MP_QSTR_version,MP_OBJ_NEW_SMALL_INT(1));
    put(result,MP_QSTR_requested_mode,mp_obj_new_str(modes[status.requested_mode],strlen(modes[status.requested_mode])));
    put(result,MP_QSTR_applied_mode,mp_obj_new_str(modes[status.applied_mode],strlen(modes[status.applied_mode])));
    put(result,MP_QSTR_state,mp_obj_new_str(request_pending ? "SWITCHING" : states[status.state],strlen(request_pending ? "SWITCHING" : states[status.state])));
    put(result,MP_QSTR_error_domain,mp_obj_new_str(domains[status.error_domain],strlen(domains[status.error_domain])));
    put(result,MP_QSTR_error_code,mp_obj_new_int(status.error_code));
    put(result,MP_QSTR_target_id,id_object(status.target_id)); put(result,MP_QSTR_connected_id,id_object(status.connected_id));
    #define HP_UINT(field) put(result,MP_QSTR_##field,mp_obj_new_int_from_uint(status.field))
    HP_UINT(operation_id); HP_UINT(policy_generation); HP_UINT(connection_generation); HP_UINT(subscription_generation); HP_UINT(bond_generation); HP_UINT(last_disconnect_generation); HP_UINT(enroll_remaining_s);
    #undef HP_UINT
    #define HP_BOOL(field) put(result,MP_QSTR_##field,mp_obj_new_bool(status.field))
    HP_BOOL(connected); HP_BOOL(encrypted); HP_BOOL(bonded); HP_BOOL(persisted); HP_BOOL(last_disconnect_local);
    #undef HP_BOOL
    put(result,MP_QSTR_filter_ready,mp_obj_new_bool(status.filter_ready && !request_pending));
    put(result,MP_QSTR_hid_ready,mp_obj_new_bool(status.hid_ready && !request_pending));
    put(result,MP_QSTR_last_disconnect_reason,mp_obj_new_int(status.last_disconnect_reason));
    #if MYNEWT_VAL(BLE_EXT_ADV)
    bool advertising=synced && ble_gap_ext_adv_active(0);
    #else
    bool advertising=synced && ble_gap_adv_active();
    #endif
    put(result,MP_QSTR_advertising,mp_obj_new_bool(advertising));
    return result;
}

// SPDX-License-Identifier: MIT
// External-system stubs ONLY. The test compiles the unmodified production C
// function bodies; these are not an alternate policy/store/queue implementation.
#pragma once
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include "HostPolicyCore.h"
#define MYNEWT_VAL(name) MYNEWT_VAL_##name
#define MYNEWT_VAL_BLE_WHITELIST 1
#define MYNEWT_VAL_BLE_HS_PVCY 1
#define MYNEWT_VAL_BLE_HOST_BASED_PRIVACY 0
#define MYNEWT_VAL_BLE_EXT_ADV 0
#define CONFIG_BT_NIMBLE_MAX_BONDS 8
#define CONFIG_BT_NIMBLE_MAX_CCCDS 24
#define CONFIG_BT_NIMBLE_NVS_PERSIST 1
#define ESP_OK 0
#define ESP_ERR_NVS_NOT_FOUND 0x1102
#define ESP_ERR_NVS_INVALID_LENGTH 0x110c
#define ESP_ERR_INVALID_STATE 0x103
#define NVS_READONLY 0
#define NVS_READWRITE 1
typedef int esp_err_t;
typedef int nvs_handle_t;
typedef uintptr_t mp_obj_t;
typedef intptr_t mp_int_t;
typedef int qstr;
typedef struct { bool user_advertising; } bleio_adapter_obj_t;
typedef struct { uint8_t type,val[6]; } bleio_address_obj_t;
extern bleio_adapter_obj_t common_hal_bleio_adapter_obj;
typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
extern unsigned test_lock_depth;
#define portENTER_CRITICAL(mux) do { (void)(mux); test_lock_depth++; } while (0)
#define portEXIT_CRITICAL(mux) do { (void)(mux); assert(test_lock_depth); test_lock_depth--; } while (0)
#define BLE_ADDR_RANDOM 1
typedef struct { uint8_t type,val[6]; } ble_addr_t;
enum { BLE_HS_ENOENT=5,BLE_HS_ENOMEM=6,BLE_HS_ENOTCONN=7,BLE_HS_EINVAL=3,BLE_HS_EBUSY=15,BLE_HS_EREJECT=16,BLE_HS_ETIMEOUT=13,BLE_HS_EALREADY=2,BLE_HS_ESTORE_CAP=27,BLE_HS_ESTORE_FAIL=28 };
#define BLE_ERR_REM_USER_CONN_TERM 0x13
#define BLE_HCI_OP(group,command) (((group)<<10)|(command))
#define BLE_HCI_OGF_LE 8
#define BLE_HCI_OCF_LE_CLR_RESOLV_LIST 0x29
enum { BLE_STORE_OBJ_TYPE_OUR_SEC=1,BLE_STORE_OBJ_TYPE_PEER_SEC,BLE_STORE_OBJ_TYPE_CCCD,BLE_STORE_OBJ_TYPE_CSFC,BLE_STORE_OBJ_TYPE_LOCAL_IRK,BLE_STORE_OBJ_TYPE_PEER_ADDR };
struct ble_store_key_sec { ble_addr_t peer_addr; uint8_t idx; };
struct ble_store_key_cccd { ble_addr_t peer_addr; uint16_t chr_val_handle; uint8_t idx; };
struct ble_store_key_csfc { ble_addr_t peer_addr; uint8_t idx; };
struct ble_store_key_local_irk { ble_addr_t addr; uint8_t idx; };
struct ble_store_key_rpa_rec { ble_addr_t peer_rpa_addr; uint8_t idx; };
struct ble_store_value_sec { ble_addr_t peer_addr; uint16_t bond_count; uint8_t key_size; uint16_t ediv; uint64_t rand_num; uint8_t ltk[16]; uint8_t ltk_present:1; uint8_t irk[16]; uint8_t irk_present:1; uint8_t csrk[16]; uint8_t csrk_present:1; uint32_t sign_counter; unsigned authenticated:1; uint8_t sc:1; };
struct ble_store_value_cccd { ble_addr_t peer_addr; uint16_t chr_val_handle,flags; unsigned value_changed:1; };
struct ble_store_value_csfc { ble_addr_t peer_addr; uint8_t csfc[1]; };
struct ble_store_value_local_irk { ble_addr_t addr; uint8_t irk[16]; };
struct ble_store_value_rpa_rec { ble_addr_t peer_rpa_addr,peer_addr; };
union ble_store_key { struct ble_store_key_sec sec; struct ble_store_key_cccd cccd; struct ble_store_key_csfc csfc; struct ble_store_key_local_irk local_irk; struct ble_store_key_rpa_rec rpa_rec; };
union ble_store_value { struct ble_store_value_sec sec; struct ble_store_value_cccd cccd; struct ble_store_value_csfc csfc; struct ble_store_value_local_irk local_irk; struct ble_store_value_rpa_rec rpa_rec; };
struct ble_store_status_event { int event_code; union { struct {int obj_type;} full; struct {int obj_type;} overflow;}; };
typedef int ble_store_read_fn(int,const union ble_store_key *,union ble_store_value *);
typedef int ble_store_write_fn(int,const union ble_store_value *);
typedef int ble_store_delete_fn(int,const union ble_store_key *);
struct { ble_store_read_fn *store_read_cb; ble_store_write_fn *store_write_cb; ble_store_delete_fn *store_delete_cb; } ble_hs_cfg;
struct ble_gap_conn_desc { uint16_t conn_handle; ble_addr_t peer_id_addr,peer_ota_addr; struct { unsigned encrypted:1; unsigned bonded:1; } sec_state; };
enum { BLE_GAP_EVENT_DISCONNECT=1,BLE_GAP_EVENT_IDENTITY_RESOLVED,BLE_GAP_EVENT_ENC_CHANGE,BLE_GAP_EVENT_REPEAT_PAIRING };
struct ble_gap_event { int type; union { struct {struct ble_gap_conn_desc conn; int reason;} disconnect; struct {uint16_t conn_handle;} identity_resolved; struct {uint16_t conn_handle; int status;} enc_change; struct {uint16_t conn_handle;} repeat_pairing;}; };
struct os_mbuf { uint8_t data[HP_INPUT_BYTES]; uint16_t length; };
struct ble_npl_event { int unused; };
struct ble_npl_eventq { int unused; };
struct ble_npl_callout { void (*fn)(struct ble_npl_event *); };
int nvs_open(const char *,int,nvs_handle_t *);
int nvs_set_blob(nvs_handle_t,const char *,const void *,size_t);
int nvs_get_blob(nvs_handle_t,const char *,void *,size_t *);
int nvs_commit(nvs_handle_t);
void nvs_close(nvs_handle_t);
int ble_gap_adv_stop(void);
int ble_gap_terminate(uint16_t,int);
int ble_gap_wl_set(const ble_addr_t *,int);
int ble_gap_conn_find(uint16_t,struct ble_gap_conn_desc *);
int ble_gap_adv_active(void);
int ble_hs_pvcy_set_resolve_enabled(int);
int ble_store_iterate(int,int (*)(int,union ble_store_value *,void *),void *);
void ble_store_key_from_value(int,union ble_store_key *,const union ble_store_value *);
int ble_store_util_count(int,int *);
int ble_store_read_peer_sec(const struct ble_store_key_sec *,struct ble_store_value_sec *);
struct os_mbuf *ble_hs_mbuf_from_flat(const void *,uint16_t);
int ble_gatts_notify_custom(uint16_t,uint16_t,struct os_mbuf *);
int64_t esp_timer_get_time(void);
struct ble_npl_eventq *nimble_port_get_dflt_eventq(void);
int ble_npl_callout_init(struct ble_npl_callout *,struct ble_npl_eventq *,void (*)(struct ble_npl_event *),void *);
int ble_npl_callout_reset(struct ble_npl_callout *,uint32_t);
void ble_npl_callout_stop(struct ble_npl_callout *);
static inline uint32_t ble_npl_time_ms_to_ticks32(uint32_t ms) { return ms; }
extern bool test_interrupted;
extern mp_obj_t test_dict_values[256];
static inline bool mp_hal_is_interrupted(void) { return test_interrupted; }
void test_vm_background(void);
void common_hal_time_delay_ms(uint32_t);
#define RUN_BACKGROUND_TASKS test_vm_background()
#define mp_const_none ((mp_obj_t)0)
#define MP_OBJ_NEW_SMALL_INT(v) ((mp_obj_t)(((uintptr_t)(v)<<2)|1))
#define MP_OBJ_NEW_QSTR(v) ((mp_obj_t)(v))
#define MP_ERROR_TEXT(v) (v)
static inline bool mp_obj_is_str(mp_obj_t v) { return v>65536 && (v&1)==0; }
static inline bool mp_obj_is_int(mp_obj_t v) { return (v&3)==1; }
static inline bool mp_obj_equal(mp_obj_t a,mp_obj_t b) { assert(!test_lock_depth);return a==b; }
static inline const char *mp_obj_str_get_str(mp_obj_t v) { return (const char *)v; }
static inline const char *mp_obj_str_get_data(mp_obj_t v,size_t *n) { *n=strlen((const char *)v); return (const char *)v; }
static inline mp_obj_t mp_obj_new_int(int v) { assert(!test_lock_depth); return MP_OBJ_NEW_SMALL_INT(v); }
static inline mp_obj_t mp_obj_new_int_from_uint(uint32_t v) { assert(!test_lock_depth); return MP_OBJ_NEW_SMALL_INT(v); }
static inline mp_obj_t mp_obj_new_bool(bool v) { assert(!test_lock_depth); return v ? 2 : 6; }
mp_obj_t mp_obj_new_str(const char *,size_t);
static inline mp_obj_t mp_obj_new_dict(int unused) { (void)unused; assert(!test_lock_depth); memset(test_dict_values,0,sizeof(mp_obj_t)*256); return 8; }
static inline void mp_obj_dict_store(mp_obj_t dict,mp_obj_t key,mp_obj_t value) { (void)dict; assert(!test_lock_depth && key<256); test_dict_values[key]=value; }
static inline mp_obj_t mp_obj_new_tuple(size_t n,const mp_obj_t *p) { (void)n;(void)p;assert(!test_lock_depth);return 12; }
static inline __attribute__((noreturn)) void mp_raise_RuntimeError(const char *s) { fprintf(stderr,"unexpected VM RuntimeError: %s\n",s);abort(); }
static inline __attribute__((noreturn)) void mp_raise_ValueError(const char *s) { fprintf(stderr,"unexpected VM ValueError: %s\n",s);abort(); }

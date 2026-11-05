// SPDX-License-Identifier: MIT
// Appended AFTER the production HostPolicy.c function bodies by the harness.
unsigned test_lock_depth;
bool test_interrupted;
mp_obj_t test_dict_values[256];
bleio_adapter_obj_t common_hal_bleio_adapter_obj;
typedef struct { bool used; union ble_store_value ram,nvs; } test_record_t;
static test_record_t records[7][24];
static ble_store_config_vars_t test_store;
ble_store_config_vars_t *ble_store_config_vars = &test_store;
static hp_blob_t stored_policy,pending_policy;
static bool policy_exists,nvs_stale,adv_on,mbuf_fail,policy_read_fail_once;
static unsigned reads,writes,deletes,policy_commits,timer_initializations,timer_deinitializations,terminations,actual_adv_starts,actual_notifications;
static unsigned test_nimble_lock_depth;
static uint16_t test_bond_count[7];
static unsigned hci_step,fail_hci_step;
static int timer_fail,write_fail,read_fail,notify_fail,stop_fail;
static uint64_t test_ms,next_service;
static struct ble_gap_conn_desc test_connection;
static void (*background_injection)(void);
static uint8_t notification_values[16][HP_INPUT_BYTES];
static uint16_t notification_lengths[16];
static struct os_mbuf mbuf;
static unsigned string_index;
static char string_pool[128][64];
static ble_addr_t test_address(unsigned n) { ble_addr_t a={.type=0,.val={1,2,3,4,5,0}};a.val[5]=(uint8_t)n;return a; }
static const ble_addr_t *record_address(int type,const union ble_store_value *v) { return type==BLE_STORE_OBJ_TYPE_CCCD ? &v->cccd.peer_addr : type==BLE_STORE_OBJ_TYPE_CSFC ? &v->csfc.peer_addr : type==BLE_STORE_OBJ_TYPE_LOCAL_IRK ? &v->local_irk.addr : type==BLE_STORE_OBJ_TYPE_PEER_ADDR ? &v->rpa_rec.peer_rpa_addr : &v->sec.peer_addr; }
static const ble_addr_t *key_address(int type,const union ble_store_key *k) { return type==BLE_STORE_OBJ_TYPE_CCCD ? &k->cccd.peer_addr : type==BLE_STORE_OBJ_TYPE_CSFC ? &k->csfc.peer_addr : type==BLE_STORE_OBJ_TYPE_LOCAL_IRK ? &k->local_irk.addr : type==BLE_STORE_OBJ_TYPE_PEER_ADDR ? &k->rpa_rec.peer_rpa_addr : &k->sec.peer_addr; }
static union ble_store_value record_ram(int type, unsigned index) {
    if (type == BLE_STORE_OBJ_TYPE_CCCD) {
        return (union ble_store_value){.cccd = test_store._ble_store_config_cccds[index]};
    }
    return records[type][index].ram;
}
int ble_store_config_read(int type,const union ble_store_key *key,union ble_store_value *out) {
    reads++;
    if(read_fail)return read_fail;
    if (type == BLE_STORE_OBJ_TYPE_CCCD) {
        assert(ble_store_config_vars && ble_store_config_num_cccds >= 0 &&
            ble_store_config_num_cccds <= CONFIG_BT_NIMBLE_MAX_CCCDS);
    }
    const ble_addr_t *a=key_address(type,key);
    for(unsigned i=0;i<24;i++)if(records[type][i].used) {
        union ble_store_value current = record_ram(type, i);
        if (memcmp(a, record_address(type, &current), sizeof(*a))) continue;
        if(type==BLE_STORE_OBJ_TYPE_CCCD && key->cccd.chr_val_handle && key->cccd.chr_val_handle!=current.cccd.chr_val_handle)continue;
        *out=current;return 0;
    }
    return BLE_HS_ENOENT;
}
int ble_store_config_write(int type,const union ble_store_value *value) {
    writes++;if(write_fail)return write_fail;
    const ble_addr_t *a=record_address(type,value);unsigned index=24;
    for(unsigned i=0;i<24;i++)if(records[type][i].used) {
        union ble_store_value current = record_ram(type, i);
        if (memcmp(a, record_address(type, &current), sizeof(*a))) continue;
        if (type == BLE_STORE_OBJ_TYPE_CCCD && value->cccd.chr_val_handle != current.cccd.chr_val_handle) continue;
        index = i;
        break;
    }
    if(index==24)for(unsigned i=0;i<24;i++)if(!records[type][i].used){index=i;break;}
    if(index==24)return BLE_HS_ESTORE_CAP;
    bool new_record = !records[type][index].used;
    records[type][index].used=true;memset(&records[type][index].ram,0,sizeof(union ble_store_value));memcpy(&records[type][index].ram,value,store_size(type));
    if(type==BLE_STORE_OBJ_TYPE_OUR_SEC || type==BLE_STORE_OBJ_TYPE_PEER_SEC)records[type][index].ram.sec.bond_count=++test_bond_count[type];
    if (type == BLE_STORE_OBJ_TYPE_CCCD) {
        if (new_record) test_store._ble_store_config_num_cccds++;
        test_store._ble_store_config_cccds[index] = value->cccd;
        // Pinned ESP NVS skips a CCCD persistence pass when the count is unchanged.
        if (!new_record) return 0;
    }
    if(!nvs_stale)records[type][index].nvs=records[type][index].ram;
    return 0;
}
int ble_store_config_delete(int type,const union ble_store_key *key) { (void)type;(void)key;deletes++;return 0; }
int ble_hs_locked_by_cur_task(void) { return test_nimble_lock_depth != 0; }
static void restore_vendor_callbacks(void) {
    // This is the subset of ble_store_config_init() that changes the dispatch.
    ble_hs_cfg.store_read_cb = ble_store_config_read;
    ble_hs_cfg.store_write_cb = ble_store_config_write;
    ble_hs_cfg.store_delete_cb = ble_store_config_delete;
}
static int nimble_write(int type, const union ble_store_value *value) {
    assert(!test_nimble_lock_depth && ble_hs_cfg.store_write_cb);
    test_nimble_lock_depth++;
    int rc = ble_hs_cfg.store_write_cb(type, value);
    test_nimble_lock_depth--;
    return rc;
}
int nvs_open(const char *name,int mode,nvs_handle_t *h) { assert(!test_lock_depth);*h=!strcmp(name,"nimble_bond")?1:2;return *h==2 && mode==NVS_READONLY && !policy_exists ? ESP_ERR_NVS_NOT_FOUND : 0; }
int nvs_set_blob(nvs_handle_t h,const char *key,const void *value,size_t size) { assert(h==2&&!strcmp(key,"policy_v1")&&size==sizeof(stored_policy));memcpy(&pending_policy,value,size);return 0; }
int nvs_commit(nvs_handle_t h) { assert(h==2);policy_commits++;stored_policy=pending_policy;policy_exists=true;return 0; }
void nvs_close(nvs_handle_t h) { (void)h; }
int nvs_get_blob(nvs_handle_t h,const char *key,void *value,size_t *size) {
    assert(!test_lock_depth);
    if(h==2){if(!policy_exists)return ESP_ERR_NVS_NOT_FOUND;if(policy_read_fail_once&&stored_policy.mode==HP_AUTO){policy_read_fail_once=false;return ESP_ERR_INVALID_STATE;}if(*size!=sizeof(stored_policy))return ESP_ERR_NVS_INVALID_LENGTH;memcpy(value,&stored_policy,*size);return 0;}
    const char *prefixes[]={"", "our_sec","peer_sec","cccd_sec","csfc_sec","local_irk","rpa_rec"};
    for(int type=1;type<=6;type++){size_t n=strlen(prefixes[type]);if(!strncmp(key,prefixes[type],n)&&key[n]=='_'){unsigned i=(unsigned)strtoul(key+n+1,NULL,10);if(!i||i>24||!records[type][i-1].used)return ESP_ERR_NVS_NOT_FOUND;if(*size!=store_size(type))return ESP_ERR_NVS_INVALID_LENGTH;memcpy(value,&records[type][i-1].nvs,*size);return 0;}}
    return ESP_ERR_NVS_NOT_FOUND;
}
int ble_gap_adv_stop(void){assert(!test_lock_depth);if(stop_fail)return stop_fail;adv_on=false;return 0;}
int ble_gap_adv_active(void){return adv_on;}
int ble_gap_terminate(uint16_t h,int r){assert(!test_lock_depth);(void)h;(void)r;terminations++;return 0;}
static int hci(void){assert(!test_lock_depth);return ++hci_step==fail_hci_step?99:0;}
int ble_hs_pvcy_set_resolve_enabled(int n){(void)n;return hci();}
int ble_hs_hci_cmd_tx(uint16_t op,const void *c,uint8_t n,void *out,uint8_t size){(void)op;(void)c;(void)n;(void)out;(void)size;return hci();}
int ble_hs_pvcy_add_entry(const uint8_t *a,uint8_t t,const uint8_t *irk){(void)a;(void)t;(void)irk;return hci();}
int ble_hs_pvcy_remove_entry(uint8_t t,const uint8_t *a){(void)t;(void)a;return 0;}
int ble_hs_pvcy_rpa_ah(const uint8_t irk[16],const uint8_t p[3],uint8_t out[3]){(void)p;out[0]=irk[0];out[1]=0x22;out[2]=0x33;return 0;}
int ble_gap_wl_set(const ble_addr_t *a,int n){assert(n==0||n==1);if(n)assert(a);return hci();}
int ble_gap_conn_find(uint16_t h,struct ble_gap_conn_desc *out){if(h!=test_connection.conn_handle)return BLE_HS_ENOTCONN;*out=test_connection;return 0;}
void ble_store_key_from_value(int t,union ble_store_key *k,const union ble_store_value *v){memset(k,0,sizeof(*k));if(t==BLE_STORE_OBJ_TYPE_CCCD){k->cccd.peer_addr=v->cccd.peer_addr;k->cccd.chr_val_handle=v->cccd.chr_val_handle;}else if(t==BLE_STORE_OBJ_TYPE_CSFC)k->csfc.peer_addr=v->csfc.peer_addr;else if(t==BLE_STORE_OBJ_TYPE_LOCAL_IRK)k->local_irk.addr=v->local_irk.addr;else if(t==BLE_STORE_OBJ_TYPE_PEER_ADDR)k->rpa_rec.peer_rpa_addr=v->rpa_rec.peer_rpa_addr;else k->sec.peer_addr=v->sec.peer_addr;}
int ble_store_iterate(int t,int (*callback)(int,union ble_store_value *,void *),void *cookie){for(unsigned i=0;i<24;i++)if(records[t][i].used){union ble_store_value v=record_ram(t,i);if(callback(t,&v,cookie))return 0;}return 0;}
int ble_store_util_count(int type,int *out){*out=0;for(unsigned i=0;i<24;i++)*out+=records[type][i].used;return 0;}
int ble_store_read_peer_sec(const struct ble_store_key_sec *k,struct ble_store_value_sec *out){union ble_store_key key={.sec=*k};union ble_store_value v;int rc=ble_store_config_read(BLE_STORE_OBJ_TYPE_PEER_SEC,&key,&v);if(!rc)*out=v.sec;return rc;}
struct os_mbuf *ble_hs_mbuf_from_flat(const void *p,uint16_t n){assert(!test_lock_depth&&n<=HP_INPUT_BYTES);if(mbuf_fail)return NULL;memcpy(mbuf.data,p,n);mbuf.length=n;return &mbuf;}
int ble_gatts_notify_custom(uint16_t h,uint16_t a,struct os_mbuf *b){assert(!test_lock_depth);(void)h;(void)a;if(notify_fail)return notify_fail;assert(actual_notifications<16);memcpy(notification_values[actual_notifications],b->data,b->length);notification_lengths[actual_notifications]=b->length;actual_notifications++;return 0;}
int64_t esp_timer_get_time(void){return (int64_t)test_ms*1000;}
struct ble_npl_eventq *nimble_port_get_dflt_eventq(void){return NULL;}
int ble_npl_callout_init(struct ble_npl_callout *co,struct ble_npl_eventq *q,void (*fn)(struct ble_npl_event *),void *arg){(void)q;(void)arg;timer_initializations++;co->fn=fn;return timer_fail;}
int ble_npl_callout_reset(struct ble_npl_callout *co,uint32_t ms){(void)co;if(timer_fail)return timer_fail;next_service=test_ms+ms;return 0;}
void ble_npl_callout_stop(struct ble_npl_callout *co){(void)co;}
void ble_npl_callout_deinit(struct ble_npl_callout *co) { assert(co->fn); co->fn = NULL; timer_deinitializations++; }
void common_hal_time_delay_ms(uint32_t ms){test_ms+=ms;}
void test_vm_background(void){if(background_injection){void(*f)(void)=background_injection;background_injection=NULL;f();}if(test_ms>=next_service){next_service=test_ms+100;service(NULL);}}
mp_obj_t mp_obj_new_str(const char *s,size_t n){assert(!test_lock_depth&&n<64&&string_index<128);char *p=string_pool[string_index++];memcpy(p,s,n);p[n]=0;return (mp_obj_t)p;}
static uint32_t raw_start(bleio_adapter_obj_t *s,bool c,bool a,uint32_t t,float i,const uint8_t *d,uint16_t n,const uint8_t *r,uint16_t z,mp_int_t p,const bleio_address_obj_t *to){(void)s;(void)c;(void)a;(void)t;(void)i;(void)r;(void)z;(void)p;(void)to;assert(!test_lock_depth);assert(n==3&&d[0]==1&&d[1]==2&&d[2]==3);assert(bleio_host_policy_advertising_guard()>=0);actual_adv_starts++;adv_on=true;return 0;}
static void reset(void){
    assert(!test_lock_depth);memset(records,0,sizeof(records));memset(&core,0,sizeof(core));memset(&observed,0,sizeof(observed));memset(&command_queue,0,sizeof(command_queue));memset(&input_queue,0,sizeof(input_queue));memset(&advertising_request,0,sizeof(advertising_request));
    assert(!test_nimble_lock_depth);
    memset(&test_store, 0, sizeof(test_store));
    ble_store_config_vars = &test_store;
    initialized=false;synced=true;timer_ready=true;processing=false;policy_busy=false;fault_pending=false;last_input_valid=false;input_origin_valid=false;policy_exists=false;nvs_stale=false;adv_on=false;mbuf_fail=false;policy_read_fail_once=false;memset(test_bond_count,0,sizeof(test_bond_count));
    timer_initialized = store_guard_failed = false;
    memset(&policy_timer, 0, sizeof(policy_timer));
    reads=writes=deletes=policy_commits=timer_initializations=timer_deinitializations=terminations=actual_adv_starts=actual_notifications=hci_step=fail_hci_step=string_index=0;timer_fail=write_fail=read_fail=notify_fail=stop_fail=0;test_ms=0;next_service=100;background_injection=NULL;store_generation=0;
    restore_vendor_callbacks();
    ble_hs_cfg.store_status_cb = bleio_host_policy_store_status;
    bleio_host_policy_install_store_guards();
    hp_backend_t backend={.persist=persist,.stop_advertising=stop_advertising,.terminate=terminate,.filter=filter,.peers=peers,.reserve_enrollment=reserve_enrollment};hp_init(&core,&backend,NULL,0);
    union ble_store_value sec;memset(&sec,0,sizeof(sec));sec.sec.peer_addr=test_address(6);sec.sec.ltk_present=true;sec.sec.key_size=16;memset(sec.sec.ltk,0x11,16);ble_store_config_write(BLE_STORE_OBJ_TYPE_OUR_SEC,&sec);
    sec.sec.irk_present=true;sec.sec.irk[0]=0x44;ble_store_config_write(BLE_STORE_OBJ_TYPE_PEER_SEC,&sec);
    union ble_store_value cccd;memset(&cccd,0,sizeof(cccd));cccd.cccd.peer_addr=test_address(6);cccd.cccd.chr_val_handle=123;cccd.cccd.flags=1;ble_store_config_write(BLE_STORE_OBJ_TYPE_CCCD,&cccd);
    reads=writes=0;assert(!hp_refresh(&core));publish();
}
static void arm_ready(void){assert(bleio_host_policy_arm_input(mp_obj_new_int_from_uint(core.status.operation_id),mp_obj_new_int_from_uint(core.status.policy_generation),mp_obj_new_int_from_uint(core.status.connection_generation),mp_obj_new_int_from_uint(core.status.subscription_generation))==2);}
static void ready(void){hp_request(&core,HP_AUTO,core.peers[0].id,1,60,test_ms);test_connection.conn_handle=42;test_connection.peer_id_addr=test_address(6);test_connection.peer_ota_addr=test_connection.peer_id_addr;test_connection.sec_state.encrypted=1;test_connection.sec_state.bonded=1;uint32_t g=hp_connect(&core,42,&core.peers[0].address);assert(g);hp_security(&core,42,g,true,true,0);hp_subscribe(&core,42,g,123,true);hp_tick(&core,test_ms);assert(core.status.hid_ready);publish();arm_ready();}
static void expire_enrollment(void){test_ms=core.deadline_ms;}
static void disconnect_reuse(void){uint32_t old=core.status.connection_generation;hp_disconnect(&core,42,old,0x213);hp_tick(&core,test_ms);uint32_t g=hp_connect(&core,42,&core.peers[0].address);assert(g!=old);hp_security(&core,42,g,true,true,0);hp_subscribe(&core,42,g,123,true);hp_tick(&core,test_ms);publish();}

static void test_privacy_sync_and_marker(void) {
    reset();
    // Adapter setup installs guards, then NimBLE privacy startup restores the
    // vendor dispatch. The host sync boundary must re-establish the guards.
    assert(ble_hs_cfg.store_write_cb == guarded_write);
    assert(ble_hs_cfg.store_delete_cb == guarded_delete);
    restore_vendor_callbacks();
    union ble_store_value cccd = record_ram(BLE_STORE_OBJ_TYPE_CCCD, 0);
    cccd.cccd.value_changed = 1;
    assert(!nimble_write(BLE_STORE_OBJ_TYPE_CCCD, &cccd));
    assert(ble_store_config_cccds[0].value_changed);
    assert(!records[BLE_STORE_OBJ_TYPE_CCCD][0].nvs.cccd.value_changed);

    synced = timer_ready = false;
    bleio_host_policy_sync();
    bleio_host_policy_sync();
    assert(synced && timer_ready && timer_initializations == 1);
    assert(ble_hs_cfg.store_read_cb == ble_store_config_read);
    assert(ble_hs_cfg.store_write_cb == guarded_write);
    assert(ble_hs_cfg.store_delete_cb == guarded_delete);
    assert(ble_hs_cfg.store_status_cb == bleio_host_policy_store_status);
    assert(core.status.state != HP_ERROR && core.peer_count == 1 && core.peers[0].durable);

    unsigned vendor_writes = writes;
    unsigned policy_writes = policy_commits;
    uint32_t generation = store_generation;
    // A queued command must not turn transient GATT bookkeeping into a fault.
    hp_command_t queued = {.mode = HP_ENROLL, .timeout_s = 5};
    assert(!hp_submit(&command_queue, &queued));
    cccd.cccd.value_changed = 0;
    assert(!nimble_write(BLE_STORE_OBJ_TYPE_CCCD, &cccd));
    assert(!ble_store_config_cccds[0].value_changed);
    cccd.cccd.value_changed = 1;
    assert(!nimble_write(BLE_STORE_OBJ_TYPE_CCCD, &cccd));
    assert(ble_store_config_cccds[0].value_changed);
    assert(!records[BLE_STORE_OBJ_TYPE_CCCD][0].nvs.cccd.value_changed);
    assert(writes == vendor_writes && policy_commits == policy_writes && store_generation == generation);
    assert(!fault_pending && !hp_refresh(&core) && core.peers[0].durable);

    // Follow the real request/service/advertisement path through expiry.
    service(NULL);
    assert(core.status.applied_mode == HP_ENROLL);
    uint8_t payload[] = {1, 2, 3};
    assert(!bleio_host_policy_start_advertising(&common_hal_bleio_adapter_obj, true, false,
        0, 0.1f, payload, sizeof(payload), NULL, 0, 0, NULL, raw_start));
    assert(adv_on && actual_adv_starts == 1);
    expire_enrollment();
    service(NULL);
    assert(!adv_on && core.status.applied_mode == HP_PAUSED);
    assert(writes == vendor_writes && !deletes && core.peer_count == 1 && core.peers[0].durable);

    // A deliberate adapter restart has a distinct timer lifecycle from resync.
    bleio_host_policy_disabled();
    bleio_host_policy_deinit();
    assert(timer_deinitializations == 1);
    restore_vendor_callbacks();
    bleio_host_policy_install_store_guards();
    restore_vendor_callbacks();
    bleio_host_policy_sync();
    assert(synced && timer_ready && timer_initializations == 2 && timer_deinitializations == 1);
    assert(ble_hs_cfg.store_write_cb == guarded_write && ble_hs_cfg.store_delete_cb == guarded_delete);
}

static void test_marker_store_boundaries(void) {
    reset();
    union ble_store_value cccd = record_ram(BLE_STORE_OBJ_TYPE_CCCD, 0);
    cccd.cccd.flags ^= 2;
    cccd.cccd.value_changed = 1;
    assert(nimble_write(BLE_STORE_OBJ_TYPE_CCCD, &cccd));
    assert(!writes && !ble_store_config_cccds[0].value_changed && ble_store_config_cccds[0].flags == 1);
    assert(records[BLE_STORE_OBJ_TYPE_CCCD][0].nvs.cccd.flags == 1);

    // A genuine mismatch in durable subscription flags still fails inventory.
    reset();
    ble_store_config_cccds[0].flags ^= 2;
    assert(hp_refresh(&core));

    reset();
    cccd = record_ram(BLE_STORE_OBJ_TYPE_CCCD, 0);
    cccd.cccd.peer_addr = test_address(7);
    cccd.cccd.value_changed = 1;
    assert(nimble_write(BLE_STORE_OBJ_TYPE_CCCD, &cccd));
    assert(!writes && !ble_store_config_cccds[0].value_changed);

    reset();
    cccd = record_ram(BLE_STORE_OBJ_TYPE_CCCD, 0);
    cccd.cccd.chr_val_handle++;
    cccd.cccd.value_changed = 1;
    assert(nimble_write(BLE_STORE_OBJ_TYPE_CCCD, &cccd));
    assert(!writes && !ble_store_config_cccds[0].value_changed);

    reset();
    ble_store_config_cccds[1] = ble_store_config_cccds[0];
    records[BLE_STORE_OBJ_TYPE_CCCD][1] = records[BLE_STORE_OBJ_TYPE_CCCD][0];
    ble_store_config_num_cccds++;
    cccd = record_ram(BLE_STORE_OBJ_TYPE_CCCD, 0);
    cccd.cccd.value_changed = 1;
    assert(nimble_write(BLE_STORE_OBJ_TYPE_CCCD, &cccd));
    assert(!writes && !ble_store_config_cccds[0].value_changed && !ble_store_config_cccds[1].value_changed);

    reset();
    cccd = record_ram(BLE_STORE_OBJ_TYPE_CCCD, 0);
    cccd.cccd.value_changed = 1;
    ble_store_config_num_cccds = CONFIG_BT_NIMBLE_MAX_CCCDS + 1;
    assert(nimble_write(BLE_STORE_OBJ_TYPE_CCCD, &cccd));
    assert(!writes && !ble_store_config_cccds[0].value_changed);

    reset();
    cccd = record_ram(BLE_STORE_OBJ_TYPE_CCCD, 0);
    cccd.cccd.value_changed = 1;
    ble_store_config_vars = NULL;
    assert(nimble_write(BLE_STORE_OBJ_TYPE_CCCD, &cccd));
    assert(!writes && !test_store._ble_store_config_cccds[0].value_changed);

    // A first subscription for the current enrollment still goes through the
    // durable vendor write. The RAM-only path cannot create a new record.
    reset();
    hp_request(&core, HP_ENROLL, 0, 20, 60, 0);
    ble_addr_t new_peer = test_address(7);
    hp_address_t new_address = address(&new_peer);
    assert(hp_connect(&core, 50, &new_address));
    cccd = record_ram(BLE_STORE_OBJ_TYPE_CCCD, 0);
    cccd.cccd.peer_addr = new_peer;
    assert(!nimble_write(BLE_STORE_OBJ_TYPE_CCCD, &cccd));
    assert(writes == 1 && ble_store_config_num_cccds == 2 && !fault_pending);
    assert(records[BLE_STORE_OBJ_TYPE_CCCD][1].nvs.cccd.peer_addr.val[5] == 7);
    assert(records[BLE_STORE_OBJ_TYPE_CCCD][1].nvs.cccd.flags == cccd.cccd.flags);
}

static void test_unexpected_callback_drift(void) {
    reset();
    ready();
    adv_on = true; // Even a stale underlying advertisement must be stopped.
    uint8_t press[] = {0xe9, 0};
    assert(!bleio_host_policy_queue_input(42, 123, press, sizeof(press)));
    hp_command_t queued = {.mode = HP_AUTO, .target = core.status.target_id, .timeout_s = 60};
    assert(!hp_submit(&command_queue, &queued));

    ble_hs_cfg.store_read_cb = NULL;
    union ble_store_value cccd = record_ram(BLE_STORE_OBJ_TYPE_CCCD, 0);
    cccd.cccd.value_changed = 1;
    unsigned vendor_reads = reads;
    assert(nimble_write(BLE_STORE_OBJ_TYPE_CCCD, &cccd));
    assert(reads == vendor_reads && !writes && !deletes && !ble_store_config_cccds[0].value_changed);
    assert(!bleio_host_policy_input_guard(42) && bleio_host_policy_advertising_guard() < 0);
    unsigned policy_writes = policy_commits;
    service(NULL);
    assert(core.status.state == HP_ERROR && core.status.applied_mode == HP_PAUSED);
    assert(terminations == 1 && !adv_on && !command_queue.pending && input_queue.count == 0);
    assert(!actual_notifications && policy_commits == policy_writes + 1);
    service(NULL);
    assert(policy_commits == policy_writes + 1 && terminations == 1 && !actual_notifications);
    assert(bleio_host_policy_queue_input(42, 123, press, sizeof(press)) == BLE_HS_EREJECT);
    assert(bleio_host_policy_advertising_guard() < 0);
}

int main(void){
    reset();ready();unsigned before=records[BLE_STORE_OBJ_TYPE_OUR_SEC][0].ram.sec.bond_count;union ble_store_value sec=records[BLE_STORE_OBJ_TYPE_OUR_SEC][0].ram;assert(!nimble_write(BLE_STORE_OBJ_TYPE_OUR_SEC,&sec));assert(!fault_pending&&records[BLE_STORE_OBJ_TYPE_OUR_SEC][0].nvs.sec.bond_count==before+1);
    // This is deliberately a SMALLER object than union ble_store_value; ASan
    // catches a whole-union copy from the real API's struct-to-union cast.
    struct ble_store_value_cccd small=ble_store_config_cccds[0];assert(!nimble_write(BLE_STORE_OBJ_TYPE_CCCD,(const union ble_store_value *)&small));assert(!fault_pending);
    nvs_stale=true;assert(nimble_write(BLE_STORE_OBJ_TYPE_OUR_SEC,&sec)!=0&&fault_pending);assert(!bleio_host_policy_input_guard(42));service(NULL);assert(core.status.state==HP_ERROR&&!adv_on);
    reset();ready();sec=records[BLE_STORE_OBJ_TYPE_OUR_SEC][0].ram;sec.sec.ltk[0]^=1;assert(nimble_write(BLE_STORE_OBJ_TYPE_OUR_SEC,&sec)!=0&&writes==0&&deletes==0);
    for(int type=BLE_STORE_OBJ_TYPE_OUR_SEC;type<=BLE_STORE_OBJ_TYPE_LOCAL_IRK;type++){union ble_store_key key={0};assert(guarded_delete(type,&key)!=0);}assert(!deletes);
    struct ble_store_status_event full={.event_code=1,.full={.obj_type=BLE_STORE_OBJ_TYPE_CCCD}};assert(bleio_host_policy_store_status(&full,NULL)==BLE_HS_ESTORE_CAP&&!deletes);
    reset();hp_request(&core,HP_ENROLL,0,2,5,0);publish();uint8_t payload[]={1,2,3};background_injection=expire_enrollment;assert(bleio_host_policy_start_advertising(&common_hal_bleio_adapter_obj,true,false,0,0.1f,payload,3,NULL,0,0,NULL,raw_start)!=0);assert(actual_adv_starts==0&&!adv_on&&core.status.applied_mode==HP_PAUSED);
    reset();ready();uint8_t press[]={0xe9,0},release[]={0,0};assert(!bleio_host_policy_queue_input(42,123,press,2));assert(!bleio_host_policy_queue_input(42,123,release,2));service(NULL);assert(actual_notifications==2&&notification_values[0][0]==0xe9&&notification_values[1][0]==0);
    assert(!bleio_host_policy_queue_input(42,123,press,2));disconnect_reuse();service(NULL);assert(actual_notifications==2);uint8_t value[2]={1,1};assert(bleio_host_policy_input_value(42,123,value,2)&&value[0]==0&&value[1]==0);
    // A report prepared by VM BEFORE reconnect cannot be relabelled as new-host
    // input merely because queue_input is entered AFTER numeric-handle reuse.
    assert(bleio_host_policy_queue_input(42,123,press,2)==BLE_HS_EREJECT&&!fault_pending&&core.status.state==HP_CONNECTED);
    arm_ready();for(unsigned i=0;i<HP_INPUT_QUEUE_CAPACITY;i++)assert(!bleio_host_policy_queue_input(42,123,press,2));assert(bleio_host_policy_queue_input(42,123,press,2)==BLE_HS_ENOMEM);service(NULL);assert(core.status.state==HP_ERROR&&terminations>0&&input_queue.count==0);
    reset();ready();assert(!bleio_host_policy_queue_input(42,123,press,2));mbuf_fail=true;service(NULL);assert(core.status.state==HP_ERROR&&actual_notifications==0&&terminations>0);
    reset();ready();timer_fail=73;service(NULL);assert(!timer_ready&&core.status.state==HP_ERROR&&!adv_on);
    reset();timer_fail=74;bleio_host_policy_sync();assert(!timer_ready&&core.status.state==HP_ERROR&&!adv_on);
    reset();ready();hp_command_t queued={.mode=HP_AUTO,.target=core.status.target_id,.timeout_s=60};assert(!hp_submit(&command_queue,&queued));fault(HP_DOMAIN_SECURITY,HP_REPEAT_PAIR);service(NULL);assert(core.status.state==HP_ERROR&&!hp_advertising_allowed(&core));
    reset();ready();processing=true;string_index=0;bleio_host_policy_status();assert(!strcmp((const char *)test_dict_values[MP_QSTR_state],"CONNECTED")&&test_dict_values[MP_QSTR_hid_ready]==2);processing=false;
    for(unsigned step=1;step<=5;step++){reset();fail_hci_step=step;hp_request(&core,HP_AUTO,core.peers[0].id,10,60,0);assert(core.status.state==HP_ERROR&&!adv_on&&!hp_advertising_allowed(&core));}
    reset();records[BLE_STORE_OBJ_TYPE_PEER_SEC][0].ram.sec.peer_addr.type=2;records[BLE_STORE_OBJ_TYPE_PEER_SEC][0].nvs=records[BLE_STORE_OBJ_TYPE_PEER_SEC][0].ram;assert(!hp_refresh(&core));hp_request(&core,HP_AUTO,core.peers[0].id,101,60,0);assert(core.status.state==HP_WAITING&&hci_step==5);
    reset();records[BLE_STORE_OBJ_TYPE_PEER_SEC][0].used=false;assert(!hp_refresh(&core));hp_request(&core,HP_AUTO,core.peers[0].id,11,60,0);assert(core.status.state==HP_WAITING);publish();string_index=0;bleio_host_policy_peers();assert(test_dict_values[MP_QSTR_resumable]==2&&test_dict_values[MP_QSTR_peer_sec]==6);
    reset();policy_read_fail_once=true;hp_request(&core,HP_AUTO,core.peers[0].id,12,60,0);assert(core.status.state==HP_ERROR&&stored_policy.mode==HP_PAUSED&&!adv_on);
    reset();ready();adv_on=true;stop_fail=75;hp_request(&core,HP_PAUSED,0,13,60,0);assert(core.status.state==HP_ERROR&&!hp_advertising_allowed(&core)&&adv_on);publish();string_index=0;bleio_host_policy_status();assert(test_dict_values[MP_QSTR_advertising]==2); // Never falsely report stopped hardware.
    reset();ready();assert(!bleio_host_policy_queue_input(42,123,press,2));service(NULL);assert(actual_notifications==1&&notification_values[0][0]);hp_command_t pause={.mode=HP_PAUSED,.timeout_s=60};assert(!hp_submit(&command_queue,&pause));service(NULL);assert(actual_notifications==2&&!notification_values[1][0]&&terminations>0);
    reset();ready();assert(!bleio_host_policy_queue_input(42,123,press,2));assert(!bleio_host_policy_queue_input(42,123,release,2));struct ble_gap_event same_security={.type=BLE_GAP_EVENT_ENC_CHANGE,.enc_change={.conn_handle=42,.status=0}};bleio_host_policy_event(&same_security,core.status.connection_generation);service(NULL);assert(actual_notifications==2&&notification_values[0][0]==0xe9&&notification_values[1][0]==0);
    reset();ready();uint32_t old_subscription=core.status.subscription_generation;bleio_host_policy_subscription(42,core.status.connection_generation,123,false);bleio_host_policy_subscription(42,core.status.connection_generation,123,true);hp_tick(&core,test_ms);publish();assert(core.status.subscription_generation!=old_subscription);assert(bleio_host_policy_queue_input(42,123,press,2)==BLE_HS_EREJECT&&!fault_pending);arm_ready();assert(!bleio_host_policy_queue_input(42,123,release,2));
    test_privacy_sync_and_marker();
    test_marker_store_boundaries();
    test_unexpected_callback_drift();
    puts("PASS production ESP32 bridge bodies: NVS, small CCCD, privacy rebind, marker, drift, expiry, FIFO, reuse, ENOMEM, timer and asymmetric snapshots");return 0;
}

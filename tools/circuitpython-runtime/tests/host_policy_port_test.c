// SPDX-License-Identifier: MIT
// Appended AFTER the production HostPolicy.c function bodies by the harness.
unsigned test_lock_depth;
bool test_interrupted;
mp_obj_t test_dict_values[256];
bleio_adapter_obj_t common_hal_bleio_adapter_obj;
typedef struct { bool used; union ble_store_value ram; } test_record_t;
typedef struct { bool used; union ble_store_value value; } test_nvs_record_t;
static test_record_t records[9][24];
static test_nvs_record_t nvs_records[9][24];
bool test_raise_armed;
jmp_buf test_raise_jump;
static unsigned erase_attempts, erased_rows, vendor_nvs_erases, nvs_commits;
static unsigned erase_fail_at, nvs_commit_fail_at;
static unsigned stops, erase_types[32];
static bool erase_readback_present;
static ble_store_config_vars_t test_store;
ble_store_config_vars_t *ble_store_config_vars = &test_store;
static hp_blob_t stored_policy,pending_policy;
static bool policy_exists,nvs_stale,adv_on,mbuf_fail,policy_read_fail_once;
static unsigned reads,writes,deletes,policy_commits,timer_initializations,timer_deinitializations,terminations,actual_adv_starts,actual_notifications;
static unsigned test_nimble_lock_depth;
static uint16_t test_bond_count[9];
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
static bool matches_vendor_address(int type, const ble_addr_t *wanted, const union ble_store_value *current) {
    if(type==BLE_STORE_OBJ_TYPE_CSFC) {
        hp_address_t a=address(wanted),b=address(&current->csfc.peer_addr);return hp_address_equal(&a,&b);
    }
    if (!memcmp(wanted, record_address(type, current), sizeof(*wanted))) return true;
    // The pinned RPA store uses either exact address. It does not implement
    // the BLE_ADDR_ANY wildcard used by ble_store_iterate().
    return type == BLE_STORE_OBJ_TYPE_PEER_ADDR && !memcmp(wanted, &current->rpa_rec.peer_addr, sizeof(*wanted));
}
int ble_store_config_read(int type,const union ble_store_key *key,union ble_store_value *out) {
    reads++;
    if(read_fail)return read_fail;
    if (type == BLE_STORE_OBJ_TYPE_CCCD) {
        assert(ble_store_config_vars && ble_store_config_num_cccds >= 0 &&
            ble_store_config_num_cccds <= CONFIG_BT_NIMBLE_MAX_CCCDS);
    }
    const ble_addr_t *a=key_address(type,key);
    if(type==BLE_STORE_OBJ_TYPE_CSFC && ble_addr_cmp(a,BLE_ADDR_ANY)) {
        bool found=false;
        for(unsigned i=0;i<24;i++)if(records[type][i].used && matches_vendor_address(type,a,&records[type][i].ram)) {
            if(found)return BLE_HS_ESTORE_FAIL;
            found=true;*out=records[type][i].ram;
        }
        return found ? 0 : BLE_HS_ENOENT;
    }
    unsigned wanted=type==BLE_STORE_OBJ_TYPE_CCCD ? key->cccd.idx : type==BLE_STORE_OBJ_TYPE_CSFC ? key->csfc.idx : key->sec.idx;
    unsigned found=0;
    for(unsigned i=0;i<24;i++)if(records[type][i].used) {
        union ble_store_value current = record_ram(type, i);
        bool wildcard=type!=BLE_STORE_OBJ_TYPE_PEER_ADDR && !ble_addr_cmp(a,BLE_ADDR_ANY);
        if (!wildcard && !matches_vendor_address(type, a, &current)) continue;
        if(type==BLE_STORE_OBJ_TYPE_CCCD && key->cccd.chr_val_handle && key->cccd.chr_val_handle!=current.cccd.chr_val_handle)continue;
        if(found++!=wanted)continue;
        *out=current;return 0;
    }
    return BLE_HS_ENOENT;
}
int ble_store_config_write(int type,const union ble_store_value *value) {
    writes++;if(write_fail)return write_fail;
    const ble_addr_t *a=record_address(type,value);unsigned index=24;
    for(unsigned i=0;i<24;i++)if(records[type][i].used) {
        union ble_store_value current = record_ram(type, i);
        if (!matches_vendor_address(type, a, &current)) continue;
        if (type == BLE_STORE_OBJ_TYPE_CCCD && value->cccd.chr_val_handle != current.cccd.chr_val_handle) continue;
        index = i;
        break;
    }
    if(index==24)for(unsigned i=0;i<24;i++)if(!records[type][i].used){index=i;break;}
    if(index==24)return BLE_HS_ESTORE_CAP;
    bool new_record = !records[type][index].used;
    if(new_record && type==BLE_STORE_OBJ_TYPE_OUR_SEC)ble_store_config_num_our_secs++;
    if(new_record && type==BLE_STORE_OBJ_TYPE_PEER_SEC)ble_store_config_num_peer_secs++;
    if(new_record && type==BLE_STORE_OBJ_TYPE_CSFC)ble_store_config_num_csfcs++;
    records[type][index].used=true;memset(&records[type][index].ram,0,sizeof(union ble_store_value));memcpy(&records[type][index].ram,value,store_size(type));
    if(type==BLE_STORE_OBJ_TYPE_OUR_SEC || type==BLE_STORE_OBJ_TYPE_PEER_SEC)records[type][index].ram.sec.bond_count=++test_bond_count[type];
    if (type == BLE_STORE_OBJ_TYPE_CCCD) {
        if (new_record) test_store._ble_store_config_num_cccds++;
        test_store._ble_store_config_cccds[index] = value->cccd;
        // Pinned ESP NVS skips a CCCD persistence pass when the count is unchanged.
        if (!new_record) return 0;
    }
    if (type == BLE_STORE_OBJ_TYPE_PEER_ADDR) {
        test_store._ble_store_config_rpa_recs[index] = value->rpa_rec;
        if (new_record) test_store._ble_store_config_num_rpa_recs++;
        // RPA persistence has the same equal-count behavior as CCCDs.
        else return 0;
    }
    if(!nvs_stale){nvs_records[type][index].used=true;nvs_records[type][index].value=records[type][index].ram;}
    return 0;
}

int ble_store_config_delete(int type,const union ble_store_key *key) {
    deletes++;
    const ble_addr_t *a=key_address(type,key);
    unsigned index=24;
    for(unsigned i=0;i<24;i++)if(records[type][i].used) {
        union ble_store_value row=record_ram(type,i);
        if(!matches_vendor_address(type,a,&row))continue;
        if(type==BLE_STORE_OBJ_TYPE_CCCD && key->cccd.chr_val_handle && key->cccd.chr_val_handle!=row.cccd.chr_val_handle)continue;
        index=i;break;
    }
    if(index==24)return BLE_HS_ENOENT;
    if(type==BLE_STORE_OBJ_TYPE_OUR_SEC)ble_store_config_num_our_secs--;
    if(type==BLE_STORE_OBJ_TYPE_PEER_SEC)ble_store_config_num_peer_secs--;
    if(type==BLE_STORE_OBJ_TYPE_CSFC)ble_store_config_num_csfcs--;
    memmove(&records[type][index],&records[type][index+1],(23-index)*sizeof(records[type][0]));
    memset(&records[type][23],0,sizeof(records[type][23]));
    if(type==BLE_STORE_OBJ_TYPE_CCCD) {
        memmove(&ble_store_config_cccds[index],&ble_store_config_cccds[index+1],(23-index)*sizeof(ble_store_config_cccds[0]));
        memset(&ble_store_config_cccds[23],0,sizeof(ble_store_config_cccds[23]));
        ble_store_config_num_cccds--;
    }
    if(type==BLE_STORE_OBJ_TYPE_PEER_ADDR) {
        memmove(&ble_store_config_rpa_recs[index],&ble_store_config_rpa_recs[index+1],(7-index)*sizeof(ble_store_config_rpa_recs[0]));
        memset(&ble_store_config_rpa_recs[7],0,sizeof(ble_store_config_rpa_recs[7]));
        ble_store_config_num_rpa_recs--;
    }
    unsigned ram_count=0,nvs_count=0;
    for(unsigned i=0;i<24;i++){ram_count+=records[type][i].used;nvs_count+=nvs_records[type][i].used;}
    // The pinned vendor layer erases the first NVS row matching no RAM bytes.
    // A changed CCCD marker can make another host's lower-index row win.
    if(nvs_count>ram_count) {
        for(unsigned slot=0;slot<24;slot++)if(nvs_records[type][slot].used) {
            bool matched=false;
            for(unsigned i=0;i<24;i++)if(records[type][i].used) {
                union ble_store_value row=record_ram(type,i);
                if(!memcmp(&row,&nvs_records[type][slot].value,store_size(type)))matched=true;
            }
            if(!matched){nvs_records[type][slot].used=false;vendor_nvs_erases++;return 0;}
        }
        return BLE_HS_ESTORE_FAIL;
    }
    return 0;
}
int ble_hs_locked_by_cur_task(void) { return test_nimble_lock_depth != 0; }
void ble_hs_lock(void) { assert(!test_nimble_lock_depth && !test_lock_depth); test_nimble_lock_depth++; }
void ble_hs_unlock(void) { assert(test_nimble_lock_depth == 1 && !test_lock_depth); test_nimble_lock_depth--; }
static void restore_vendor_callbacks(void) {
    // This is the subset of ble_store_config_init() that changes the dispatch.
    ble_hs_cfg.store_read_cb = ble_store_config_read;
    ble_hs_cfg.store_write_cb = ble_store_config_write;
    ble_hs_cfg.store_delete_cb = ble_store_config_delete;
}
static int nimble_write(int type, const union ble_store_value *value) {
    assert(ble_hs_cfg.store_write_cb);
    ble_hs_lock();
    int rc = ble_hs_cfg.store_write_cb(type, value);
    ble_hs_unlock();
    return rc;
}
int nvs_open(const char *name,int mode,nvs_handle_t *h) { assert(!test_lock_depth);*h=!strcmp(name,"nimble_bond")?1:2;return *h==2 && mode==NVS_READONLY && !policy_exists ? ESP_ERR_NVS_NOT_FOUND : 0; }
int nvs_set_blob(nvs_handle_t h,const char *key,const void *value,size_t size) { assert(h==2&&!strcmp(key,"policy_v1")&&size==sizeof(stored_policy));memcpy(&pending_policy,value,size);return 0; }

int nvs_commit(nvs_handle_t h) {
    assert(!test_lock_depth);
    if(h==1){assert(test_nimble_lock_depth==1);nvs_commits++;return nvs_commit_fail_at==nvs_commits ? 79 : 0;}
    assert(h==2);policy_commits++;stored_policy=pending_policy;policy_exists=true;return 0;
}
static bool nvs_key(const char *key,int *type,unsigned *index) {
    for(int t=1;t<=8;t++){
        const char *prefix=store_prefix(t);
        if(!prefix)continue;
        size_t n=strlen(prefix);
        if(!strncmp(key,prefix,n)&&key[n]=='_'){
            unsigned i=(unsigned)strtoul(key+n+1,NULL,10);
            if(!i||i>24)return false;
            *type=t;*index=i-1;return true;
        }
    }
    return false;
}
int nvs_erase_key(nvs_handle_t h,const char *key) {
    assert(h==1 && !test_lock_depth && test_nimble_lock_depth==1);
    erase_attempts++;
    if(erase_fail_at==erase_attempts)return 78;
    int type;unsigned index;
    if(!nvs_key(key,&type,&index)||!nvs_records[type][index].used)return ESP_ERR_NVS_NOT_FOUND;
    assert(erase_attempts<=32);erase_types[erase_attempts-1]=(unsigned)type;
    if(!erase_readback_present){nvs_records[type][index].used=false;erased_rows++;}
    return 0;
}
void nvs_close(nvs_handle_t h) { (void)h; }
int nvs_get_blob(nvs_handle_t h,const char *key,void *value,size_t *size) {
    assert(!test_lock_depth);
    if(h==2){if(!policy_exists)return ESP_ERR_NVS_NOT_FOUND;if(policy_read_fail_once&&stored_policy.mode==HP_AUTO){policy_read_fail_once=false;return ESP_ERR_INVALID_STATE;}if(*size!=sizeof(stored_policy))return ESP_ERR_NVS_INVALID_LENGTH;memcpy(value,&stored_policy,*size);return 0;}
    int type;unsigned index;
    if(nvs_key(key,&type,&index)&&nvs_records[type][index].used){
        if(*size!=store_size(type))return ESP_ERR_NVS_INVALID_LENGTH;
        memcpy(value,&nvs_records[type][index].value,*size);return 0;
    }
    return ESP_ERR_NVS_NOT_FOUND;
}
int ble_gap_adv_stop(void){assert(!test_lock_depth);stops++;if(stop_fail)return stop_fail;adv_on=false;return 0;}
int ble_gap_ext_adv_stop(uint8_t instance) { assert(instance == 0); return ble_gap_adv_stop(); }
int ble_gap_adv_active(void){return adv_on;}
int ble_gap_ext_adv_active(uint8_t instance) { assert(instance == 0); return ble_gap_adv_active(); }
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
static bool iterable_record(int type, unsigned index) {
    if (!records[type][index].used) return false;
    return type != BLE_STORE_OBJ_TYPE_PEER_ADDR ||
        matches_vendor_address(type, BLE_ADDR_ANY, &records[type][index].ram);
}
int ble_store_iterate(int t,int (*callback)(int,union ble_store_value *,void *),void *cookie){for(unsigned i=0;i<24;i++)if(iterable_record(t,i)){union ble_store_value v=record_ram(t,i);if(callback(t,&v,cookie))return 0;}return 0;}
int ble_store_util_count(int type,int *out){assert(!test_nimble_lock_depth);*out=0;for(unsigned i=0;i<24;i++)*out+=iterable_record(type,i);return 0;}
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
    assert(!test_lock_depth);memset(records,0,sizeof(records));memset(nvs_records,0,sizeof(nvs_records));memset(&core,0,sizeof(core));memset(&observed,0,sizeof(observed));memset(&command_queue,0,sizeof(command_queue));memset(&input_queue,0,sizeof(input_queue));memset(&advertising_request,0,sizeof(advertising_request));
    assert(!test_nimble_lock_depth);
    memset(&test_store, 0, sizeof(test_store));
    ble_store_config_vars = &test_store;
    initialized=false;synced=true;timer_ready=true;processing=false;policy_busy=false;fault_pending=false;last_input_valid=false;input_origin_valid=false;policy_exists=false;nvs_stale=false;adv_on=false;mbuf_fail=false;policy_read_fail_once=false;memset(test_bond_count,0,sizeof(test_bond_count));
    timer_initialized = store_guard_failed = false;
    memset(&policy_timer, 0, sizeof(policy_timer));
    reads=writes=deletes=policy_commits=timer_initializations=timer_deinitializations=terminations=actual_adv_starts=actual_notifications=hci_step=fail_hci_step=string_index=0;timer_fail=write_fail=read_fail=notify_fail=stop_fail=0;test_ms=0;next_service=100;background_injection=NULL;store_generation=0;
    restore_vendor_callbacks();
    ble_hs_cfg.store_status_cb = bleio_host_policy_store_status;
    test_raise_armed=false;stops=erase_attempts=erased_rows=vendor_nvs_erases=nvs_commits=erase_fail_at=nvs_commit_fail_at=0;erase_readback_present=false;memset(erase_types,0,sizeof(erase_types));
    bleio_host_policy_install_store_guards();
    bleio_host_policy_init(0);
    assert(core.backend.forget==forget_records);
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
    assert(!nvs_records[BLE_STORE_OBJ_TYPE_CCCD][0].value.cccd.value_changed);

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
    assert(!nvs_records[BLE_STORE_OBJ_TYPE_CCCD][0].value.cccd.value_changed);
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
    assert(nvs_records[BLE_STORE_OBJ_TYPE_CCCD][0].value.cccd.flags == 1);

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
    assert(nvs_records[BLE_STORE_OBJ_TYPE_CCCD][1].value.cccd.peer_addr.val[5] == 7);
    assert(nvs_records[BLE_STORE_OBJ_TYPE_CCCD][1].value.cccd.flags == cccd.cccd.flags);
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

static ble_addr_t test_rpa(uint8_t n) {
    return (ble_addr_t){.type = BLE_ADDR_RANDOM, .val = {0x55, 0x22, 0x33, n, 0x55, 0x66}};
}

static void test_rpa_mappings_preserve_existing_rows(void) {
    reset();
    union ble_store_value old = {.rpa_rec = {.peer_addr = test_address(6)}};
    assert(!ble_store_config_write(BLE_STORE_OBJ_TYPE_PEER_ADDR, &old));
    hp_request(&core, HP_ENROLL, 0, 21, 60, 0);
    ble_addr_t fresh_peer = test_address(7);
    hp_address_t fresh_identity = address(&fresh_peer);
    assert(hp_connect(&core, 50, &fresh_identity));
    union ble_store_value requested = old;
    requested.rpa_rec.peer_addr = fresh_peer;
    unsigned vendor_reads = reads, vendor_writes = writes;
    uint32_t generation = store_generation;
    assert(!nimble_write(BLE_STORE_OBJ_TYPE_PEER_ADDR, &requested));
    assert(reads == vendor_reads && writes == vendor_writes && store_generation == generation);
    assert(ble_store_config_num_rpa_recs == 1);
    assert(!ble_addr_cmp(&records[BLE_STORE_OBJ_TYPE_PEER_ADDR][0].ram.rpa_rec.peer_addr, &old.rpa_rec.peer_addr));
    assert(!ble_addr_cmp(&nvs_records[BLE_STORE_OBJ_TYPE_PEER_ADDR][0].value.rpa_rec.peer_addr, &old.rpa_rec.peer_addr));

    reset();
    old.rpa_rec.peer_rpa_addr = test_rpa(8);
    assert(!ble_store_config_write(BLE_STORE_OBJ_TYPE_PEER_ADDR, &old));
    ready();
    vendor_writes = writes;
    generation = store_generation;
    assert(!nimble_write(BLE_STORE_OBJ_TYPE_PEER_ADDR, &old));
    assert(writes == vendor_writes && store_generation == generation);
    nvs_records[BLE_STORE_OBJ_TYPE_PEER_ADDR][0].value.rpa_rec.peer_addr = fresh_peer;
    assert(nimble_write(BLE_STORE_OBJ_TYPE_PEER_ADDR, &old));
    assert(writes == vendor_writes && store_generation == generation);

    reset();
    assert(!ble_store_config_write(BLE_STORE_OBJ_TYPE_PEER_ADDR, &old));
    hp_request(&core, HP_ENROLL, 0, 22, 60, 0);
    assert(hp_connect(&core, 50, &fresh_identity));
    vendor_writes = writes;
    requested = old;
    requested.rpa_rec.peer_addr = fresh_peer;
    assert(nimble_write(BLE_STORE_OBJ_TYPE_PEER_ADDR, &requested));
    assert(writes == vendor_writes && ble_store_config_num_rpa_recs == 1);
    assert(!ble_addr_cmp(&records[BLE_STORE_OBJ_TYPE_PEER_ADDR][0].ram.rpa_rec.peer_addr, &old.rpa_rec.peer_addr));
    assert(!ble_addr_cmp(&nvs_records[BLE_STORE_OBJ_TYPE_PEER_ADDR][0].value.rpa_rec.peer_addr, &old.rpa_rec.peer_addr));

    reset();
    for (unsigned i = 0; i < CONFIG_BT_NIMBLE_MAX_BONDS; i++) {
        old.rpa_rec.peer_rpa_addr = test_rpa(i);
        assert(!ble_store_config_write(BLE_STORE_OBJ_TYPE_PEER_ADDR, &old));
    }
    int vendor_count = -1;
    assert(!ble_store_util_count(BLE_STORE_OBJ_TYPE_PEER_ADDR, &vendor_count) && vendor_count == 0);
    assert(ble_store_config_num_rpa_recs == CONFIG_BT_NIMBLE_MAX_BONDS);
    hp_request(&core, HP_ENROLL, 0, 23, 60, 0);
    assert(core.status.state == HP_ERROR && core.status.error_code == BLE_HS_ESTORE_CAP && !adv_on);
}

static void test_fresh_private_enrollment(void) {
    reset();
    hp_request(&core, HP_ENROLL, 0, 24, 60, 0);
    ble_addr_t private_addr = test_rpa(9), identity = test_address(7);
    test_connection = (struct ble_gap_conn_desc){
        .conn_handle = 50, .peer_ota_addr = private_addr, .peer_id_addr = private_addr,
    };
    uint32_t connection = bleio_host_policy_connect(50);
    assert(connection && !core.candidate_valid && !core.status.connected_id);

    // Pinned SMP publishes the resolved identity before OUR/PEER keys and
    // the RPA mapping. It publishes ENC_CHANGE before saving early CCCDs.
    bleio_host_policy_subscription(50, connection, 123, true);
    test_connection.peer_id_addr = identity;
    struct ble_gap_event resolved = {
        .type = BLE_GAP_EVENT_IDENTITY_RESOLVED, .identity_resolved = {.conn_handle = 50},
    };
    bleio_host_policy_event(&resolved, connection);
    assert(core.candidate_valid && core.status.connected_id);
    union ble_store_value sec = record_ram(BLE_STORE_OBJ_TYPE_OUR_SEC, 0);
    sec.sec.peer_addr = identity;
    sec.sec.ltk[0] ^= 1;
    assert(!nimble_write(BLE_STORE_OBJ_TYPE_OUR_SEC, &sec));
    sec.sec.irk_present = true;
    sec.sec.irk[0] = 0x55;
    assert(!nimble_write(BLE_STORE_OBJ_TYPE_PEER_SEC, &sec));
    union ble_store_value rpa = {.rpa_rec = {.peer_addr = identity, .peer_rpa_addr = private_addr}};
    assert(!nimble_write(BLE_STORE_OBJ_TYPE_PEER_ADDR, &rpa));
    assert(ble_store_config_num_rpa_recs == 1);
    assert(!ble_addr_cmp(&nvs_records[BLE_STORE_OBJ_TYPE_PEER_ADDR][0].value.rpa_rec.peer_addr, &identity));
    assert(!ble_addr_cmp(&nvs_records[BLE_STORE_OBJ_TYPE_PEER_ADDR][0].value.rpa_rec.peer_rpa_addr, &private_addr));

    test_connection.sec_state.encrypted = test_connection.sec_state.bonded = 1;
    struct ble_gap_event encrypted = {.type = BLE_GAP_EVENT_ENC_CHANGE, .enc_change = {.conn_handle = 50}};
    bleio_host_policy_event(&encrypted, connection);
    service(NULL);
    assert(core.status.applied_mode == HP_ENROLL && !core.status.hid_ready);
    union ble_store_value cccd = record_ram(BLE_STORE_OBJ_TYPE_CCCD, 0);
    cccd.cccd.peer_addr = identity;
    assert(!nimble_write(BLE_STORE_OBJ_TYPE_CCCD, &cccd));
    service(NULL);
    assert(core.status.applied_mode == HP_AUTO && core.status.hid_ready && core.status.state == HP_CONNECTED);
    assert(core.status.target_id == core.status.connected_id && stored_policy.mode == HP_AUTO);
    assert(terminations == 0);
}

static void test_rejected_enrollment_cannot_write_existing_records(void) {
    reset();
    hp_request(&core, HP_ENROLL, 0, 25, 60, 0);
    const uint16_t handle = 50;
    ble_addr_t private_address = test_rpa(9);
    test_connection = (struct ble_gap_conn_desc){
        .conn_handle = handle, .peer_id_addr = private_address, .peer_ota_addr = private_address,
    };
    uint32_t generation = bleio_host_policy_connect(handle);
    assert(generation && !core.candidate_valid);
    test_connection.peer_id_addr = test_address(6);
    struct ble_gap_event resolved = {
        .type = BLE_GAP_EVENT_IDENTITY_RESOLVED, .identity_resolved = {.conn_handle = handle},
    };
    bleio_host_policy_event(&resolved, generation);
    assert(core.enrollment_rejected && terminations == 1 && !fault_pending);

    union ble_store_value original = record_ram(BLE_STORE_OBJ_TYPE_OUR_SEC, 0);
    union ble_store_value changed = original;
    changed.sec.ltk[0] ^= 1;
    assert(nimble_write(BLE_STORE_OBJ_TYPE_OUR_SEC, &changed) == BLE_HS_ESTORE_FAIL);
    union ble_store_key key;
    ble_store_key_from_value(BLE_STORE_OBJ_TYPE_OUR_SEC, &key, &original);
    assert(guarded_delete(BLE_STORE_OBJ_TYPE_OUR_SEC, &key) == BLE_HS_ESTORE_FAIL);
    assert(!fault_pending && same_store_record(BLE_STORE_OBJ_TYPE_OUR_SEC, &original,
        &nvs_records[BLE_STORE_OBJ_TYPE_OUR_SEC][0].value));
    hp_disconnect(&core, handle, generation, 0x216);
    service(NULL);
    assert(core.status.state == HP_ENROLLING && core.status.operation_id == 25 && !fault_pending);
}

static void test_failed_peripheral_establishment(void) {
    reset();
    hp_request(&core, HP_ENROLL, 0, 25, 60, 0);
    test_connection = (struct ble_gap_conn_desc){
        .conn_handle = 50, .peer_id_addr = test_address(6),
    };
    // A retained host can answer an open advertisement before the user
    // selects the new one. Reject it without admitting a policy connection.
    assert(!bleio_host_policy_connect(50));
    assert(!core.status.connected && !core.status.connection_generation && terminations == 1);
    assert(bleio_host_policy_advertising_guard() == HP_ENROLL);

    test_connection.peer_id_addr = test_address(7);
    uint32_t generation = bleio_host_policy_connect(50);
    assert(generation && core.status.connected);
    struct ble_gap_event event = {
        .type = BLE_GAP_EVENT_CONNECT, .connect = {.conn_handle = 50, .status = 0},
    };
    bleio_host_policy_event(&event, generation);
    assert(core.status.connected);
    event.connect.status = BLE_HS_EAGAIN;
    event.connect.conn_handle = 51;
    bleio_host_policy_event(&event, generation);
    assert(core.status.connected);
    event.connect.conn_handle = 50;
    bleio_host_policy_event(&event, generation - 1);
    assert(core.status.connected);

    // Pinned NimBLE reports CONNECT failure, rather than DISCONNECT, if its
    // remote-version/feature handshake ends before application establishment.
    bleio_host_policy_event(&event, generation);
    assert(!core.status.connected && core.status.last_disconnect_generation == generation);
    assert(!core.status.last_disconnect_local && core.status.last_disconnect_reason == BLE_HS_EAGAIN);
    service(NULL);
    assert(bleio_host_policy_advertising_guard() == HP_ENROLL && core.status.state == HP_ENROLLING);

    uint32_t replacement = bleio_host_policy_connect(50);
    assert(replacement && replacement != generation);
    bleio_host_policy_event(&event, generation);
    assert(core.status.connected && core.status.connection_generation == replacement);

    hp_request(&core, HP_PAUSED, 0, 26, 60, 0);
    assert(terminations == 2 && stored_policy.mode == HP_PAUSED);
    bleio_host_policy_event(&event, replacement);
    service(NULL);
    assert(core.status.state == HP_STATE_PAUSED && !core.status.connected);
    assert(core.status.last_disconnect_generation == replacement && core.status.last_disconnect_local);
    assert(bleio_host_policy_advertising_guard() < 0);
}

static void test_failed_connection_callback_registration(void) {
    reset();
    hp_request(&core, HP_ENROLL, 0, 27, 60, 0);
    test_connection = (struct ble_gap_conn_desc){
        .conn_handle = 50, .peer_id_addr = test_address(7),
    };
    uint32_t generation = bleio_host_policy_connect(50);
    assert(generation && core.status.connected);

    bleio_host_policy_connection_attach_failed(50, generation - 1, BLE_HS_ENOTCONN);
    bleio_host_policy_connection_attach_failed(51, generation, BLE_HS_ENOTCONN);
    assert(core.status.connected && !core.status.last_disconnect_generation);
    bleio_host_policy_connection_attach_failed(50, generation, BLE_HS_ENOTCONN);
    assert(!core.status.connected && !terminations && core.status.last_disconnect_generation == generation);
    assert(core.status.last_disconnect_reason == BLE_HS_ENOTCONN);
    service(NULL);
    assert(bleio_host_policy_advertising_guard() == HP_ENROLL);

    generation = bleio_host_policy_connect(50);
    assert(generation && core.status.connected);
    bleio_host_policy_connection_attach_failed(50, generation, BLE_HS_EINVAL);
    assert(core.status.state == HP_ERROR && core.status.error_code == BLE_HS_EINVAL);
    assert(stored_policy.mode == HP_PAUSED && terminations == 1 && bleio_host_policy_advertising_guard() < 0);
}


static uint64_t test_host_id(unsigned number) {
    ble_addr_t native=test_address(number);hp_address_t value=address(&native);return hp_identity_id(&value);
}
static void clean_pause(void) {
    hp_request(&core,HP_PAUSED,0,900,60,test_ms);hp_tick(&core,test_ms);publish();
    assert(hp_forget_allowed(&observed,observed_handle) && !adv_on);
}
static void forget_fixture(bool select_target) {
    reset();
    union ble_store_value sec=record_ram(BLE_STORE_OBJ_TYPE_OUR_SEC,0);
    sec.sec.peer_addr=test_address(7);memset(sec.sec.ltk,0x77,sizeof(sec.sec.ltk));
    assert(!ble_store_config_write(BLE_STORE_OBJ_TYPE_OUR_SEC,&sec));
    sec.sec.irk_present=true;memset(sec.sec.irk,0x66,sizeof(sec.sec.irk));
    assert(!ble_store_config_write(BLE_STORE_OBJ_TYPE_PEER_SEC,&sec));
    // A PUBLIC_ID row resolves to the same policy identity as PUBLIC.
    records[BLE_STORE_OBJ_TYPE_PEER_SEC][0].ram.sec.peer_addr.type=2;
    nvs_records[BLE_STORE_OBJ_TYPE_PEER_SEC][0].value=records[BLE_STORE_OBJ_TYPE_PEER_SEC][0].ram;
    // Put the unrelated, RAM-divergent CCCD before both target NVS keys.
    nvs_records[BLE_STORE_OBJ_TYPE_CCCD][3]=nvs_records[BLE_STORE_OBJ_TYPE_CCCD][0];
    nvs_records[BLE_STORE_OBJ_TYPE_CCCD][0].used=false;
    union ble_store_value cccd={.cccd={.peer_addr=test_address(7),.chr_val_handle=123,.flags=1}};
    assert(!ble_store_config_write(BLE_STORE_OBJ_TYPE_CCCD,&cccd));
    nvs_records[BLE_STORE_OBJ_TYPE_CCCD][0]=nvs_records[BLE_STORE_OBJ_TYPE_CCCD][1];
    nvs_records[BLE_STORE_OBJ_TYPE_CCCD][1].used=false;
    ble_store_config_cccds[1].value_changed=1;
    cccd.cccd.peer_addr=test_address(6);cccd.cccd.chr_val_handle=124;
    assert(!ble_store_config_write(BLE_STORE_OBJ_TYPE_CCCD,&cccd));
    for(unsigned host=6;host<=7;host++) {
        union ble_store_value csfc={.csfc={.peer_addr=test_address(host),.csfc={(uint8_t)host}}};
        assert(!ble_store_config_write(BLE_STORE_OBJ_TYPE_CSFC,&csfc));
        union ble_store_value rpa={.rpa_rec={.peer_addr=test_address(host),.peer_rpa_addr=test_rpa(host)}};
        if(host==6)rpa.rpa_rec.peer_addr.type=2;
        assert(!ble_store_config_write(BLE_STORE_OBJ_TYPE_PEER_ADDR,&rpa));
    }
    // NVS keys are independent of compacted RAM indices. Keep the other
    // host first so subsequent new writes fit the pre-existing write model.
    const int swap_types[]={BLE_STORE_OBJ_TYPE_OUR_SEC,BLE_STORE_OBJ_TYPE_PEER_SEC,BLE_STORE_OBJ_TYPE_CSFC,BLE_STORE_OBJ_TYPE_PEER_ADDR};
    for(unsigned i=0;i<sizeof(swap_types)/sizeof(swap_types[0]);i++) {
        int type=swap_types[i];test_nvs_record_t temporary=nvs_records[type][0];
        nvs_records[type][0]=nvs_records[type][1];nvs_records[type][1]=temporary;
    }
    union ble_store_value local={.local_irk={.addr=test_address(9)}};
    memset(local.local_irk.irk,0x99,sizeof(local.local_irk.irk));
    assert(!ble_store_config_write(BLE_STORE_OBJ_TYPE_LOCAL_IRK,&local));
    assert(!hp_refresh(&core) && core.peer_count==2);
    hp_request(&core,HP_AUTO,test_host_id(select_target ? 6 : 7),901,60,test_ms);
    clean_pause();
    assert(!hp_set_alias(&core,test_host_id(6),"target",6));
    assert(!hp_set_alias(&core,test_host_id(7),"other",5));
    publish();
}
static test_record_t before_ram[9][24];
static test_nvs_record_t before_nvs[9][24];
static union ble_store_value before_values[9][24];
static void save_forget_records(void) {
    memcpy(before_ram,records,sizeof(records));memcpy(before_nvs,nvs_records,sizeof(nvs_records));
    memset(before_values,0,sizeof(before_values));
    for(int type=1;type<=8;type++)for(unsigned i=0;i<24;i++)if(records[type][i].used)before_values[type][i]=record_ram(type,i);
}
static bool fixture_target(int type,const union ble_store_value *value) {
    if(type==BLE_STORE_OBJ_TYPE_LOCAL_IRK)return false;
    hp_address_t target=address(&(ble_addr_t){.type=0,.val={1,2,3,4,5,6}});
    return forget_target(type,value,&target);
}
static void assert_other_records_preserved(void) {
    for(int type=1;type<=8;type++)for(unsigned slot=0;slot<24;slot++) {
        if(before_nvs[type][slot].used && fixture_target(type,&before_nvs[type][slot].value)) {
            assert(!nvs_records[type][slot].used);
        } else {
            assert(!memcmp(&before_nvs[type][slot],&nvs_records[type][slot],sizeof(before_nvs[type][slot])));
        }
        if(!before_ram[type][slot].used || fixture_target(type,&before_values[type][slot]))continue;
        unsigned matches=0;
        for(unsigned i=0;i<24;i++)if(records[type][i].used) {
            union ble_store_value value=record_ram(type,i);
            if(!memcmp(&value,&before_values[type][slot],store_size(type)))matches++;
        }
        assert(matches==1);
    }
    assert(!memcmp(before_ram[BLE_STORE_OBJ_TYPE_LOCAL_IRK],records[BLE_STORE_OBJ_TYPE_LOCAL_IRK],sizeof(records[0])));
}
static void test_forget_storage_and_service(void) {
    for(unsigned selected=0;selected<2;selected++) {
        forget_fixture(selected!=0);
        hp_address_t target=core.peers[0].address;
        for(size_t i=0;i<core.peer_count;i++)if(core.peers[i].id==test_host_id(6))target=core.peers[i].address;
        uint32_t generation=core.status.bond_generation, stores=store_generation;
        hp_blob_t before=core.blob;
        save_forget_records();
        unsigned old_stops=stops,old_hci=hci_step;
        mp_obj_t operation=bleio_host_policy_forget(id_object(test_host_id(6)),mp_obj_new_int_from_uint(generation));
        assert(operation && command_queue.pending && command_queue.command.forget);
        assert(command_queue.command.generation==generation && !erased_rows);
        uint32_t queued=command_queue.command.operation;
        service(NULL);
        assert(core.status.operation_id==queued && hp_forget_allowed(&core.status,core.handle));
        assert(core.status.bond_generation!=generation && core.peer_count==1 && core.peers[0].id==test_host_id(7));
        assert(stops==old_stops+1 && hci_step==old_hci+4);
        assert(erase_attempts==6 && erased_rows==6 && deletes==6 && vendor_nvs_erases==0);
        const unsigned order[]={6,8,1,3,3,2};assert(!memcmp(order,erase_types,sizeof(order)));
        assert(store_generation==stores+6);
        assert_other_records_preserved();
        for(unsigned i=0;i<HP_MAX_PEERS;i++) {
            if(hp_address_equal(&before.aliases[i].address,&target)) {
                hp_alias_t empty={0};assert(!memcmp(&empty,&core.blob.aliases[i],sizeof(empty)));
            } else assert(!memcmp(&before.aliases[i],&core.blob.aliases[i],sizeof(before.aliases[i])));
        }
        assert(core.status.target_id==(selected ? 0 : test_host_id(7)));
        string_index=0;bleio_host_policy_status();
        assert(test_dict_values[MP_QSTR_target_id]==(selected ? mp_const_none : id_object(test_host_id(7))) ||
            (!selected && !strcmp((const char *)test_dict_values[MP_QSTR_target_id],(const char *)id_object(test_host_id(7)))));
        hp_request(&core,HP_ENROLL,0,902,60,test_ms);
        for(size_t i=0;i<core.enrollment_existing_count;i++)assert(core.enrollment_existing[i]!=test_host_id(6));
    }
}
// Legacy NVS restoration appends every valid slot, including equal CCCDs.
// These invented identities/key bytes never come from a device backup.
static void legacy_duplicate_cccd_fixture(bool select_target) {
    reset();
    for(unsigned host=7;host<=9;host++) {
        union ble_store_value sec={0};sec.sec.peer_addr=test_address(host);
        sec.sec.ltk_present=true;sec.sec.key_size=16;memset(sec.sec.ltk,(int)host,16);
        assert(!ble_store_config_write(BLE_STORE_OBJ_TYPE_OUR_SEC,&sec));
        sec.sec.irk_present=true;memset(sec.sec.irk,(int)(host+1),16);
        assert(!ble_store_config_write(BLE_STORE_OBJ_TYPE_PEER_SEC,&sec));
    }
    const unsigned owners[]={6,6,8,7,8,9,7,9};
    const unsigned handles[]={123,124,123,123,124,123,123,124};
    memset(records[BLE_STORE_OBJ_TYPE_CCCD],0,sizeof(records[0]));
    memset(nvs_records[BLE_STORE_OBJ_TYPE_CCCD],0,sizeof(nvs_records[0]));
    memset(ble_store_config_cccds,0,CONFIG_BT_NIMBLE_MAX_CCCDS*sizeof(ble_store_config_cccds[0]));
    ble_store_config_num_cccds=0;
    for(unsigned slot=0;slot<8;slot++) {
        union ble_store_value row={.cccd={.peer_addr=test_address(owners[slot]),
                                        .chr_val_handle=(uint16_t)handles[slot],.flags=1}};
        nvs_records[BLE_STORE_OBJ_TYPE_CCCD][slot]=(test_nvs_record_t){.used=true,.value=row};
    }
    // Match pinned populate_db_from_nvs: copy each persistent slot to the next
    // RAM occurrence, rather than calling a key-based writer that deduplicates.
    for(unsigned slot=0;slot<24;slot++)if(nvs_records[BLE_STORE_OBJ_TYPE_CCCD][slot].used) {
        unsigned index=(unsigned)ble_store_config_num_cccds;
        union ble_store_value row=nvs_records[BLE_STORE_OBJ_TYPE_CCCD][slot].value;
        records[BLE_STORE_OBJ_TYPE_CCCD][index]=(test_record_t){.used=true,.ram=row};
        ble_store_config_cccds[index]=row.cccd;
        ble_store_config_num_cccds++;
    }
    for(unsigned host=6;host<=9;host++) {
        union ble_store_value csfc={.csfc={.peer_addr=test_address(host),.csfc={1}}};
        assert(!ble_store_config_write(BLE_STORE_OBJ_TYPE_CSFC,&csfc));
        if(host!=9) {
            union ble_store_value rpa={.rpa_rec={.peer_addr=test_address(host),.peer_rpa_addr=test_rpa(host)}};
            assert(!ble_store_config_write(BLE_STORE_OBJ_TYPE_PEER_ADDR,&rpa));
        }
    }
    union ble_store_value local={.local_irk={.addr=test_address(10)}};
    memset(local.local_irk.irk,0x99,sizeof(local.local_irk.irk));
    assert(!ble_store_config_write(BLE_STORE_OBJ_TYPE_LOCAL_IRK,&local));
    assert(ble_store_config_num_cccds==8);
    assert(!hp_refresh(&core) && core.peer_count==4);
    for(size_t i=0;i<core.peer_count;i++)assert(core.peers[i].durable);
    hp_request(&core,HP_AUTO,test_host_id(select_target ? 6 : 7),901,60,test_ms);
    clean_pause();
    const char *aliases[]={"target","otherA","otherB","otherC"};
    for(unsigned host=6;host<=9;host++)assert(!hp_set_alias(&core,test_host_id(host),aliases[host-6],6));
    publish();
    assert(!erase_attempts && !erased_rows && !deletes && !vendor_nvs_erases);
}
static void assert_legacy_unrelated_occurrences_preserved(void) {
    for(int type=1;type<=8;type++)for(unsigned slot=0;slot<24;slot++) {
        if(before_nvs[type][slot].used && fixture_target(type,&before_nvs[type][slot].value)) {
            assert(!nvs_records[type][slot].used);
        } else {
            // Physical NVS slot positions and complete blobs stay identical.
            assert(!memcmp(&before_nvs[type][slot],&nvs_records[type][slot],sizeof(before_nvs[type][slot])));
        }
        if(!before_ram[type][slot].used || fixture_target(type,&before_values[type][slot]))continue;
        unsigned expected=0,actual=0;
        for(unsigned i=0;i<24;i++) {
            if(before_ram[type][i].used &&
                !memcmp(&before_values[type][slot],&before_values[type][i],store_size(type)))expected++;
            if(records[type][i].used) {
                union ble_store_value row=record_ram(type,i);
                if(!memcmp(&row,&before_values[type][slot],store_size(type)))actual++;
            }
        }
        assert(expected && actual==expected);
    }
    assert(!memcmp(before_ram[BLE_STORE_OBJ_TYPE_LOCAL_IRK],records[BLE_STORE_OBJ_TYPE_LOCAL_IRK],sizeof(records[0])));
}
static void test_forget_preserves_legacy_unrelated_cccd_occurrences(void) {
    for(unsigned selected=0;selected<2;selected++) {
        legacy_duplicate_cccd_fixture(selected!=0);
        save_forget_records();
        hp_blob_t old=core.blob;
        uint32_t generation=core.status.bond_generation;
        hp_address_t target=address(&(ble_addr_t){.type=0,.val={1,2,3,4,5,6}});
        assert(!forget_records(NULL,&target,false));
        mp_obj_t operation=bleio_host_policy_forget(id_object(test_host_id(6)),mp_obj_new_int_from_uint(generation));
        assert(operation && command_queue.pending && !erased_rows);
        service(NULL);
        assert(core.status.state==HP_STATE_PAUSED && !core.status.error_domain && !core.status.error_code);
        assert(core.peer_count==3 && core.cccd_count==6 && core.status.bond_generation!=generation);
        assert(erase_attempts==6 && erased_rows==6 && deletes==6 && !vendor_nvs_erases);
        const unsigned order[]={6,8,1,3,3,2};assert(!memcmp(order,erase_types,sizeof(order)));
        assert_legacy_unrelated_occurrences_preserved();
        // Equal unrelated CCCDs remain at their original two NVS slots.
        assert(nvs_records[BLE_STORE_OBJ_TYPE_CCCD][3].used && nvs_records[BLE_STORE_OBJ_TYPE_CCCD][6].used);
        for(unsigned i=0;i<HP_MAX_PEERS;i++) {
            if(hp_address_equal(&old.aliases[i].address,&target)) {
                hp_alias_t empty={0};assert(!memcmp(&empty,&core.blob.aliases[i],sizeof(empty)));
            } else assert(!memcmp(&old.aliases[i],&core.blob.aliases[i],sizeof(old.aliases[i])));
        }
        assert(core.status.target_id==(selected ? 0 : test_host_id(7)));
    }
}
static void test_forget_legacy_cccd_multiplicity_and_owner_refusals(void) {
    for(unsigned failure=0;failure<12;failure++) {
        legacy_duplicate_cccd_fixture(true);
        if(failure==0)nvs_records[BLE_STORE_OBJ_TYPE_CCCD][8]=nvs_records[BLE_STORE_OBJ_TYPE_CCCD][3];
        if(failure==1) {
            records[BLE_STORE_OBJ_TYPE_CCCD][8]=records[BLE_STORE_OBJ_TYPE_CCCD][3];
            ble_store_config_cccds[8]=ble_store_config_cccds[3];ble_store_config_num_cccds++;
        }
        if(failure==2)nvs_records[BLE_STORE_OBJ_TYPE_CCCD][6].value.cccd.flags^=2;
        if(failure==3)ble_store_config_cccds[6].flags^=2;
        if(failure==4 || failure==5) {
            union ble_store_value row=record_ram(BLE_STORE_OBJ_TYPE_CCCD,0);
            if(failure==5)row.cccd.flags^=2; // Same target key, conflicting flags.
            nvs_records[BLE_STORE_OBJ_TYPE_CCCD][8]=(test_nvs_record_t){.used=true,.value=row};
            records[BLE_STORE_OBJ_TYPE_CCCD][8]=(test_record_t){.used=true,.ram=row};
            ble_store_config_cccds[8]=row.cccd;ble_store_config_num_cccds++;
        }
        if(failure>=6 && failure<=9) {
            const int types[]={BLE_STORE_OBJ_TYPE_OUR_SEC,BLE_STORE_OBJ_TYPE_PEER_SEC,
                               BLE_STORE_OBJ_TYPE_CSFC,BLE_STORE_OBJ_TYPE_PEER_ADDR};
            int type=types[failure-6];unsigned index=type==BLE_STORE_OBJ_TYPE_PEER_ADDR ? 3 : 4;
            records[type][index]=records[type][0];nvs_records[type][index]=nvs_records[type][0];
            if(type==BLE_STORE_OBJ_TYPE_OUR_SEC)ble_store_config_num_our_secs++;
            if(type==BLE_STORE_OBJ_TYPE_PEER_SEC)ble_store_config_num_peer_secs++;
            if(type==BLE_STORE_OBJ_TYPE_CSFC)ble_store_config_num_csfcs++;
            if(type==BLE_STORE_OBJ_TYPE_PEER_ADDR){ble_store_config_rpa_recs[index]=ble_store_config_rpa_recs[0];ble_store_config_num_rpa_recs++;}
        }
        if(failure==10) {
            // Invalid/wildcard owners must not gain the non-target exception.
            for(unsigned i=3;i<=6;i+=3) {
                memset(&ble_store_config_cccds[i].peer_addr,0,sizeof(ble_addr_t));
                records[BLE_STORE_OBJ_TYPE_CCCD][i].ram.cccd=ble_store_config_cccds[i];
                nvs_records[BLE_STORE_OBJ_TYPE_CCCD][i].value.cccd=ble_store_config_cccds[i];
            }
        }
        if(failure==11) {
            // PUBLIC_ID still denotes the target, never an unrelated owner.
            for(unsigned i=3;i<=6;i+=3) {
                ble_store_config_cccds[i].peer_addr=test_address(6);
                ble_store_config_cccds[i].peer_addr.type=2;
                records[BLE_STORE_OBJ_TYPE_CCCD][i].ram.cccd=ble_store_config_cccds[i];
                nvs_records[BLE_STORE_OBJ_TYPE_CCCD][i].value.cccd=ble_store_config_cccds[i];
            }
        }
        save_forget_records();
        struct ble_store_value_cccd prior_cccds[CONFIG_BT_NIMBLE_MAX_CCCDS];
        memcpy(prior_cccds,ble_store_config_cccds,sizeof(prior_cccds));
        hp_address_t target=address(&(ble_addr_t){.type=0,.val={1,2,3,4,5,6}});
        assert(forget_records(NULL,&target,false)==HP_STORAGE);
        assert(!erase_attempts && !erased_rows && !deletes && !vendor_nvs_erases);
        assert(!memcmp(before_ram,records,sizeof(records)) && !memcmp(before_nvs,nvs_records,sizeof(nvs_records)));
        assert(!memcmp(prior_cccds,ble_store_config_cccds,sizeof(prior_cccds)));
    }
}

static void test_vendor_delete_mutation_control(void) {
    forget_fixture(true);
    union ble_store_value target=record_ram(BLE_STORE_OBJ_TYPE_CCCD,0);union ble_store_key key;
    ble_store_key_from_value(BLE_STORE_OBJ_TYPE_CCCD,&key,&target);
    assert(!ble_store_config_delete(BLE_STORE_OBJ_TYPE_CCCD,&key));
    assert(vendor_nvs_erases==1 && !nvs_records[BLE_STORE_OBJ_TYPE_CCCD][0].used);
    assert(nvs_records[BLE_STORE_OBJ_TYPE_CCCD][3].used);
}
static void test_forget_storage_refusals(void) {
    for(unsigned failure=0;failure<7;failure++) {
        forget_fixture(true);
        if(failure==0)nvs_records[BLE_STORE_OBJ_TYPE_OUR_SEC][1].used=false;
        if(failure==1)nvs_records[BLE_STORE_OBJ_TYPE_OUR_SEC][4]=nvs_records[BLE_STORE_OBJ_TYPE_OUR_SEC][1];
        if(failure==2){records[BLE_STORE_OBJ_TYPE_OUR_SEC][2]=records[BLE_STORE_OBJ_TYPE_OUR_SEC][0];ble_store_config_num_our_secs++;}
        if(failure==3){
            records[BLE_STORE_OBJ_TYPE_PEER_ADDR][1].ram.rpa_rec.peer_addr=records[BLE_STORE_OBJ_TYPE_PEER_ADDR][0].ram.rpa_rec.peer_rpa_addr;
            ble_store_config_rpa_recs[1]=records[BLE_STORE_OBJ_TYPE_PEER_ADDR][1].ram.rpa_rec;
            nvs_records[BLE_STORE_OBJ_TYPE_PEER_ADDR][0].value=records[BLE_STORE_OBJ_TYPE_PEER_ADDR][1].ram;
        }
        if(failure==4){
            records[BLE_STORE_OBJ_TYPE_CSFC][2]=records[BLE_STORE_OBJ_TYPE_CSFC][0];
            records[BLE_STORE_OBJ_TYPE_CSFC][2].ram.csfc.peer_addr.type=2;
            nvs_records[BLE_STORE_OBJ_TYPE_CSFC][4]=(test_nvs_record_t){.used=true,.value=records[BLE_STORE_OBJ_TYPE_CSFC][2].ram};
            ble_store_config_num_csfcs++;
        }
        if(failure==5){
            records[BLE_STORE_OBJ_TYPE_CCCD][0].ram.cccd.chr_val_handle=0;
            ble_store_config_cccds[0].chr_val_handle=0;
            nvs_records[BLE_STORE_OBJ_TYPE_CCCD][3].value.cccd.chr_val_handle=0;
        }
        if(failure==6){
            ble_addr_t key=test_address(10);
            records[BLE_STORE_OBJ_TYPE_PEER_ADDR][0].ram.rpa_rec.peer_rpa_addr=key;
            ble_store_config_rpa_recs[0]=records[BLE_STORE_OBJ_TYPE_PEER_ADDR][0].ram.rpa_rec;
            nvs_records[BLE_STORE_OBJ_TYPE_PEER_ADDR][1].value=records[BLE_STORE_OBJ_TYPE_PEER_ADDR][0].ram;
            key.type=2;
            records[BLE_STORE_OBJ_TYPE_PEER_ADDR][1].ram.rpa_rec.peer_addr=key;
            ble_store_config_rpa_recs[1]=records[BLE_STORE_OBJ_TYPE_PEER_ADDR][1].ram.rpa_rec;
            nvs_records[BLE_STORE_OBJ_TYPE_PEER_ADDR][0].value=records[BLE_STORE_OBJ_TYPE_PEER_ADDR][1].ram;
        }
        save_forget_records();
        hp_address_t target=address(&(ble_addr_t){.type=0,.val={1,2,3,4,5,6}});
        assert(forget_records(NULL,&target,false)==HP_STORAGE);
        assert(!erased_rows && !deletes && !memcmp(before_ram,records,sizeof(records)) && !memcmp(before_nvs,nvs_records,sizeof(nvs_records)));
    }
    forget_fixture(true);
    hp_address_t target=address(&(ble_addr_t){.type=0,.val={1,2,3,4,5,6}});
    erase_readback_present=true;
    assert(forget_records(NULL,&target,true)==HP_STORAGE);
    assert(erase_attempts==1 && !deletes && !erased_rows);
    forget_fixture(true);nvs_commit_fail_at=1;
    assert(forget_records(NULL,&target,true)==79);
    assert(erase_attempts==1 && nvs_commits==1 && !deletes);
}
static void test_forget_partial_failure_retry(void) {
    forget_fixture(true);erase_fail_at=3;
    uint32_t generation=core.status.bond_generation;
    bleio_host_policy_forget(id_object(test_host_id(6)),mp_obj_new_int_from_uint(generation));
    service(NULL);
    assert(core.status.state==HP_ERROR && core.status.error_domain==HP_DOMAIN_NVS && core.status.error_code==78);
    assert(core.peer_count==2 && erased_rows==2 && !vendor_nvs_erases);
    clean_pause();erase_fail_at=0;
    bleio_host_policy_forget(id_object(test_host_id(6)),mp_obj_new_int_from_uint(core.status.bond_generation));
    service(NULL);
    assert(core.status.state==HP_STATE_PAUSED && core.peer_count==1 && core.peers[0].id==test_host_id(7));
    assert(!vendor_nvs_erases);
}
static void expect_forget_value_error(mp_obj_t target,mp_obj_t generation) {
    hp_queue_t queue=command_queue;unsigned before=terminations,erases=erase_attempts;
    test_raise_armed=true;
    int raised=setjmp(test_raise_jump);
    if(!raised) { (void)bleio_host_policy_forget(target,generation);assert(!"Forget unexpectedly queued"); }
    test_raise_armed=false;
    assert(raised==2 && !test_lock_depth && !memcmp(&queue,&command_queue,sizeof(queue)));
    assert(terminations==before && erase_attempts==erases);
}
static void test_forget_vm_preconditions(void) {
    for(unsigned condition=0;condition<19;condition++) {
        forget_fixture(true);
        switch(condition) {
            case 0:core.status.state=HP_SWITCHING;break;
            case 1:core.status.requested_mode=HP_AUTO;break;
            case 2:core.status.applied_mode=HP_AUTO;break;
            case 3:core.status.persisted=false;break;
            case 4:core.status.connected=true;break;
            case 5:core.handle=42;break;
            case 6:core.status.error_domain=HP_DOMAIN_NVS;break;
            case 7:core.status.error_code=19;break;
            case 8:command_queue.pending=true;break;
            case 9:processing=true;break;
            case 10:policy_busy=true;break;
            case 11:fault_pending=true;break;
            case 12:store_guard_failed=true;break;
            case 13:adv_on=true;break;
            case 14:advertising_request.active=true;break;
            case 15:initialized=false;break;
            case 16:synced=false;break;
            case 17:timer_ready=false;break;
            case 18:core.status.state=HP_ERROR;break;
        }
        publish();
        expect_forget_value_error(id_object(test_host_id(6)),mp_obj_new_int_from_uint(core.status.bond_generation));
    }
    forget_fixture(true);
    mp_obj_t generation=mp_obj_new_int_from_uint(core.status.bond_generation);
    expect_forget_value_error(mp_obj_new_str("invalid",7),generation);
    expect_forget_value_error(mp_obj_new_str("0000000000000000",16),generation);
    expect_forget_value_error(id_object(test_host_id(6)),mp_obj_new_str("1",1));
    expect_forget_value_error(id_object(test_host_id(6)),2);
    expect_forget_value_error(id_object(test_host_id(6)),mp_obj_new_int_from_uint(core.status.bond_generation+1));
    // A fault consumes the operation but never interprets its zero/default mode.
    forget_fixture(true);core.status.requested_mode=HP_AUTO;publish();
    hp_command_t command={.forget=true,.mode=HP_ENROLL,.target=test_host_id(6),.generation=core.status.bond_generation};
    assert(!hp_submit(&command_queue,&command));fault(HP_DOMAIN_NVS,88);service(NULL);
    assert(core.status.operation_id==command.operation && core.status.requested_mode!=HP_ENROLL && !erased_rows);
}
static void test_forget_then_reenroll_saved_identity(void) {
    forget_fixture(true);
    hp_request(&core,HP_ENROLL,0,903,60,test_ms);
    ble_addr_t private_address=test_rpa(10),identity=test_address(6);
    test_connection=(struct ble_gap_conn_desc){.conn_handle=50,.peer_id_addr=private_address,.peer_ota_addr=private_address};
    uint32_t connection=bleio_host_policy_connect(50);assert(connection);
    test_connection.peer_id_addr=identity;
    struct ble_gap_event resolved={.type=BLE_GAP_EVENT_IDENTITY_RESOLVED,.identity_resolved={.conn_handle=50}};
    bleio_host_policy_event(&resolved,connection);
    assert(core.enrollment_rejected && terminations==1);
    hp_disconnect(&core,50,connection,0x13);clean_pause();
    bleio_host_policy_forget(id_object(test_host_id(6)),mp_obj_new_int_from_uint(core.status.bond_generation));service(NULL);
    assert(core.peer_count==1);
    hp_request(&core,HP_ENROLL,0,904,60,test_ms);
    test_connection=(struct ble_gap_conn_desc){.conn_handle=51,.peer_id_addr=private_address,.peer_ota_addr=private_address};
    connection=bleio_host_policy_connect(51);assert(connection);
    bleio_host_policy_subscription(51,connection,123,true);
    test_connection.peer_id_addr=identity;resolved.identity_resolved.conn_handle=51;
    bleio_host_policy_event(&resolved,connection);
    assert(core.candidate_valid && !core.enrollment_rejected);
    union ble_store_value sec={.sec={.peer_addr=identity,.key_size=16,.ltk_present=true,.irk_present=true}};
    memset(sec.sec.ltk,0x33,sizeof(sec.sec.ltk));memset(sec.sec.irk,0x22,sizeof(sec.sec.irk));
    assert(!nimble_write(BLE_STORE_OBJ_TYPE_OUR_SEC,&sec));
    assert(!nimble_write(BLE_STORE_OBJ_TYPE_PEER_SEC,&sec));
    test_connection.sec_state.encrypted=test_connection.sec_state.bonded=1;
    struct ble_gap_event encrypted={.type=BLE_GAP_EVENT_ENC_CHANGE,.enc_change={.conn_handle=51}};
    bleio_host_policy_event(&encrypted,connection);service(NULL);
    union ble_store_value cccd={.cccd={.peer_addr=identity,.chr_val_handle=123,.flags=1}};
    assert(!nimble_write(BLE_STORE_OBJ_TYPE_CCCD,&cccd));service(NULL);
    assert(core.status.applied_mode==HP_AUTO && core.status.state==HP_CONNECTED && core.status.hid_ready && core.status.connected_id==test_host_id(6));
}

int main(void){
    reset();ready();unsigned before=records[BLE_STORE_OBJ_TYPE_OUR_SEC][0].ram.sec.bond_count;union ble_store_value sec=records[BLE_STORE_OBJ_TYPE_OUR_SEC][0].ram;assert(!nimble_write(BLE_STORE_OBJ_TYPE_OUR_SEC,&sec));assert(!fault_pending&&nvs_records[BLE_STORE_OBJ_TYPE_OUR_SEC][0].value.sec.bond_count==before+1);
    // This is deliberately a SMALLER object than union ble_store_value; ASan
    // catches a whole-union copy from the real API's struct-to-union cast.
    struct ble_store_value_cccd small=ble_store_config_cccds[0];assert(!nimble_write(BLE_STORE_OBJ_TYPE_CCCD,(const union ble_store_value *)&small));assert(!fault_pending);
    nvs_stale=true;assert(nimble_write(BLE_STORE_OBJ_TYPE_OUR_SEC,&sec)!=0&&fault_pending);assert(!bleio_host_policy_input_guard(42));service(NULL);assert(core.status.state==HP_ERROR&&!adv_on);
    reset();ready();sec=records[BLE_STORE_OBJ_TYPE_OUR_SEC][0].ram;sec.sec.ltk[0]^=1;assert(nimble_write(BLE_STORE_OBJ_TYPE_OUR_SEC,&sec)!=0&&writes==0&&deletes==0);
    const int guarded_types[]={BLE_STORE_OBJ_TYPE_OUR_SEC,BLE_STORE_OBJ_TYPE_PEER_SEC,BLE_STORE_OBJ_TYPE_CCCD,BLE_STORE_OBJ_TYPE_CSFC,BLE_STORE_OBJ_TYPE_LOCAL_IRK};
    for(unsigned i=0;i<sizeof(guarded_types)/sizeof(guarded_types[0]);i++){union ble_store_key key={0};assert(guarded_delete(guarded_types[i],&key)!=0);}assert(!deletes);
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
    reset();records[BLE_STORE_OBJ_TYPE_PEER_SEC][0].ram.sec.peer_addr.type=2;nvs_records[BLE_STORE_OBJ_TYPE_PEER_SEC][0].value=records[BLE_STORE_OBJ_TYPE_PEER_SEC][0].ram;assert(!hp_refresh(&core));hp_request(&core,HP_AUTO,core.peers[0].id,101,60,0);assert(core.status.state==HP_WAITING&&hci_step==5);
    reset();records[BLE_STORE_OBJ_TYPE_PEER_SEC][0].used=false;assert(!hp_refresh(&core));hp_request(&core,HP_AUTO,core.peers[0].id,11,60,0);assert(core.status.state==HP_WAITING);publish();string_index=0;bleio_host_policy_peers();assert(test_dict_values[MP_QSTR_resumable]==2&&test_dict_values[MP_QSTR_peer_sec]==6);
    reset();policy_read_fail_once=true;hp_request(&core,HP_AUTO,core.peers[0].id,12,60,0);assert(core.status.state==HP_ERROR&&stored_policy.mode==HP_PAUSED&&!adv_on);
    reset();ready();adv_on=true;stop_fail=75;hp_request(&core,HP_PAUSED,0,13,60,0);assert(core.status.state==HP_ERROR&&!hp_advertising_allowed(&core)&&adv_on);publish();string_index=0;bleio_host_policy_status();assert(test_dict_values[MP_QSTR_advertising]==2); // Never falsely report stopped hardware.
    reset();ready();assert(!bleio_host_policy_queue_input(42,123,press,2));service(NULL);assert(actual_notifications==1&&notification_values[0][0]);hp_command_t pause={.mode=HP_PAUSED,.timeout_s=60};assert(!hp_submit(&command_queue,&pause));service(NULL);assert(actual_notifications==2&&!notification_values[1][0]&&terminations>0);
    reset();ready();assert(!bleio_host_policy_queue_input(42,123,press,2));assert(!bleio_host_policy_queue_input(42,123,release,2));struct ble_gap_event same_security={.type=BLE_GAP_EVENT_ENC_CHANGE,.enc_change={.conn_handle=42,.status=0}};bleio_host_policy_event(&same_security,core.status.connection_generation);service(NULL);assert(actual_notifications==2&&notification_values[0][0]==0xe9&&notification_values[1][0]==0);
    reset();ready();uint32_t old_subscription=core.status.subscription_generation;bleio_host_policy_subscription(42,core.status.connection_generation,123,false);bleio_host_policy_subscription(42,core.status.connection_generation,123,true);hp_tick(&core,test_ms);publish();assert(core.status.subscription_generation!=old_subscription);assert(bleio_host_policy_queue_input(42,123,press,2)==BLE_HS_EREJECT&&!fault_pending);arm_ready();assert(!bleio_host_policy_queue_input(42,123,release,2));
    test_forget_storage_and_service();
    test_forget_preserves_legacy_unrelated_cccd_occurrences();
    test_forget_legacy_cccd_multiplicity_and_owner_refusals();
    test_vendor_delete_mutation_control();
    test_forget_storage_refusals();
    test_forget_partial_failure_retry();
    test_forget_vm_preconditions();
    test_forget_then_reenroll_saved_identity();
    test_privacy_sync_and_marker();
    test_marker_store_boundaries();
    test_rpa_mappings_preserve_existing_rows();
    test_fresh_private_enrollment();
    test_rejected_enrollment_cannot_write_existing_records();
    test_failed_peripheral_establishment();
    test_failed_connection_callback_registration();
    test_unexpected_callback_drift();
    puts("PASS production ESP32 bridge bodies: NVS, small CCCD, privacy rebind, marker, drift, expiry, FIFO, reuse, ENOMEM, timer and asymmetric snapshots");return 0;
}

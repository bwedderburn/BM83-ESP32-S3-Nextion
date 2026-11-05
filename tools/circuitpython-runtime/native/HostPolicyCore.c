// SPDX-License-Identifier: MIT
#include "HostPolicyCore.h"
#include <string.h>
#define HP_MAGIC 0x31485042u
int hp_submit(hp_queue_t *queue, hp_command_t *command) {
    if (queue->pending && (command->alias || command->mode!=HP_PAUSED)) { return HP_QUEUE_FULL; }
    command->operation=++queue->next_operation;
    if (!command->operation) { command->operation=++queue->next_operation; }
    queue->command=*command; queue->pending=true; return 0;
}
bool hp_pop(hp_queue_t *queue, hp_command_t *command) {
    if (!queue->pending) { return false; }
    *command=queue->command; queue->pending=false; return true;
}
void hp_clear_input(hp_input_queue_t *queue) { queue->head=0; queue->count=0; }
int hp_queue_input(hp_input_queue_t *queue, const hp_status_t *s, uint16_t active_handle,
    uint16_t actual_input, uint16_t handle, uint16_t attribute, const uint8_t *data, size_t length) {
    if (length>HP_INPUT_BYTES || !length || s->state!=HP_CONNECTED || s->applied_mode!=HP_AUTO || !s->connected || !s->encrypted || !s->bonded || !s->hid_ready || s->connected_id!=s->target_id || handle!=active_handle || attribute!=actual_input) { return HP_UNAUTHORIZED; }
    if (queue->count==HP_INPUT_QUEUE_CAPACITY) { return HP_QUEUE_FULL; }
    unsigned index=(queue->head+queue->count)%HP_INPUT_QUEUE_CAPACITY;
    hp_input_report_t *report=&queue->reports[index];
    report->handle=handle; report->attribute=attribute; report->operation=s->operation_id;
    report->policy_generation=s->policy_generation; report->connection_generation=s->connection_generation;
    report->subscription_generation=s->subscription_generation;
    report->identity=s->target_id; report->length=(uint8_t)length; memcpy(report->data,data,length);
    queue->count++; return 0;
}
bool hp_pop_input(hp_input_queue_t *queue, hp_input_report_t *report) {
    if (!queue->count) { return false; }
    *report=queue->reports[queue->head]; queue->head=(queue->head+1)%HP_INPUT_QUEUE_CAPACITY; queue->count--; return true;
}
bool hp_input_current(const hp_core_t *p, const hp_input_report_t *report) {
    return hp_input_allowed(p,report->handle) && report->attribute==p->hid_input_handle && report->operation==p->status.operation_id && report->policy_generation==p->status.policy_generation && report->connection_generation==p->status.connection_generation && report->subscription_generation==p->status.subscription_generation && report->identity==p->status.target_id;
}
bool hp_normalize(hp_address_t *out, const hp_address_t *in) {
    *out = *in;
    if (out->type == 2 || out->type == 3) { out->type -= 2; }
    if (out->type > 1) { return false; }
    // Random identity must be static: never publish/use an RPA or NRPA as a host ID.
    if (out->type == 1 && (out->val[5] & 0xc0) != 0xc0) { return false; }
    uint8_t any=0, all=0xff;
    for (unsigned i=0;i<6;i++) { any |= out->val[i]; all &= out->val[i]; }
    return any != 0 && all != 0xff;
}
bool hp_address_equal(const hp_address_t *a, const hp_address_t *b) {
    hp_address_t x,y;
    return hp_normalize(&x,a) && hp_normalize(&y,b) && x.type==y.type && memcmp(x.val,y.val,6)==0;
}
uint64_t hp_identity_id(const hp_address_t *address) {
    hp_address_t a;
    if (!hp_normalize(&a,address)) { return 0; }
    // An opaque label, NOT authentication. Admission always compares the full identity.
    uint64_t id=UINT64_C(14695981039346656037);
    const uint8_t domain[]={ 'B','M','8','3','H','P',1,a.type };
    for (unsigned i=0;i<sizeof domain;i++) { id=(id^domain[i])*UINT64_C(1099511628211); }
    for (unsigned i=0;i<6;i++) { id=(id^a.val[i])*UINT64_C(1099511628211); }
    return id == 0 ? 1 : id;
}
uint32_t hp_blob_checksum(const hp_blob_t *blob) {
    uint32_t crc=0xffffffffu;
    const uint8_t *bytes=(const uint8_t *)blob;
    for (size_t i=0;i<offsetof(hp_blob_t,checksum);i++) {
        crc ^= bytes[i];
        for (unsigned bit=0;bit<8;bit++) { crc=(crc>>1)^((0u-(crc&1u))&0xedb88320u); }
    }
    return ~crc;
}
bool hp_alias_valid(const char *text, size_t length) {
    if (length>HP_ALIAS_BYTES) { return false; }
    for (size_t i=0;i<length;) {
        uint8_t first=(uint8_t)text[i++]; uint32_t cp; unsigned continuation;
        if (first<0x80) { cp=first; continuation=0; }
        else if (first>=0xc2 && first<=0xdf) { cp=first&0x1f; continuation=1; }
        else if (first>=0xe0 && first<=0xef) { cp=first&0x0f; continuation=2; }
        else if (first>=0xf0 && first<=0xf4) { cp=first&7; continuation=3; }
        else { return false; }
        if (i+continuation>length) { return false; }
        for (unsigned j=0;j<continuation;j++) { uint8_t next=(uint8_t)text[i++]; if ((next&0xc0)!=0x80) { return false; } cp=(cp<<6)|(next&0x3f); }
        if ((continuation==1 && cp<0x80) || (continuation==2 && cp<0x800) || (continuation==3 && cp<0x10000) || cp>0x10ffff || (cp>=0xd800 && cp<=0xdfff) || cp<0x20 || (cp>=0x7f && cp<=0x9f)) { return false; }
    }
    return true;
}
bool hp_blob_valid(const hp_blob_t *b) {
    if (b->magic!=HP_MAGIC || b->version!=1 || b->size!=sizeof(*b) || b->mode>HP_AUTO || b->checksum!=hp_blob_checksum(b)) { return false; }
    hp_address_t a;
    if (b->mode==HP_AUTO && !hp_normalize(&a,&b->selected)) { return false; }
    for (unsigned i=0;i<HP_MAX_PEERS;i++) {
        if (b->aliases[i].alias[HP_ALIAS_BYTES] != 0 || !hp_alias_valid(b->aliases[i].alias,strlen(b->aliases[i].alias))) { return false; }
        if (b->aliases[i].alias[0] && !hp_normalize(&a,&b->aliases[i].address)) { return false; }
    }
    return true;
}
static int commit(hp_core_t *p, hp_mode_t mode, const hp_address_t *selected) {
    hp_blob_t next=p->blob;
    next.magic=HP_MAGIC; next.version=1; next.size=sizeof(next); next.serial++;
    next.mode=mode;
    if (selected) { next.selected=*selected; }
    next.checksum=hp_blob_checksum(&next);
    int rc=p->backend.persist(p->backend.context,&next);
    if (rc) { p->status.persisted=false; return rc; }
    p->blob=next; p->status.persisted=true; p->status.policy_generation=next.serial;
    return 0;
}
static void terminate_once(hp_core_t *p) {
    if (p->handle==HP_INVALID_HANDLE || p->terminate_sent) { return; }
    p->terminate_sent=true;
    int rc=p->backend.terminate(p->backend.context,p->handle);
    if (rc==HP_TERMINATE_ABSENT) {
        // Native lookup confirms absence, but supplied no disconnect EVENT or
        // reason. Clear live facts without fabricating a terminal reason.
        p->handle=HP_INVALID_HANDLE; p->status.connected=false; p->status.connected_id=0;
        p->status.encrypted=false; p->status.bonded=false; p->status.hid_ready=false;
        p->terminate_sent=false; p->terminate_failed=false;
    } else if (rc) { p->terminate_failed=true; p->status.error_domain=HP_DOMAIN_NIMBLE; p->status.error_code=rc; p->status.state=HP_ERROR; }
}
void hp_fail(hp_core_t *p, hp_domain_t domain, int error) {
    p->status.filter_ready=false; p->status.hid_ready=false; p->input_subscribed=false;
    p->status.applied_mode=HP_PAUSED; p->status.state=HP_ERROR;
    p->status.error_domain=domain; p->status.error_code=error;
    p->deadline_ms=0; p->status.enroll_remaining_s=0;
    // An earlier write may have committed even if its readback failed before
    // updating this RAM blob. Always attempt an explicit durable PAUSED record.
    if (commit(p,HP_PAUSED,NULL)) { p->status.persisted=false; }
    int stopped=p->backend.stop_advertising(p->backend.context);
    if (stopped && !error) { p->status.error_domain=HP_DOMAIN_NIMBLE; p->status.error_code=stopped; }
    terminate_once(p);
}
void hp_init(hp_core_t *p, const hp_backend_t *backend, const hp_blob_t *blob, int load_error) {
    memset(p,0,sizeof(*p)); p->backend=*backend; p->handle=HP_INVALID_HANDLE;
    p->status.requested_mode=HP_PAUSED; p->status.applied_mode=HP_PAUSED; p->status.state=HP_STATE_PAUSED;
    if (blob && hp_blob_valid(blob) && !load_error) {
        p->blob=*blob; p->status.persisted=true; p->status.policy_generation=blob->serial;
        p->status.target_id=hp_identity_id(&blob->selected); p->status.requested_mode=(hp_mode_t)blob->mode;
        if (blob->mode==HP_AUTO) { p->status.state=HP_SWITCHING; }
    } else if (load_error || blob) {
        p->status.state=HP_ERROR; p->status.error_domain=HP_DOMAIN_NVS; p->status.error_code=load_error ? load_error : HP_STORAGE;
    }
}
int hp_refresh(hp_core_t *p) {
    hp_peer_t peers[HP_MAX_PEERS]; size_t count=HP_MAX_PEERS; unsigned cccds=0;
    memset(peers,0,sizeof(peers));
    int rc=p->backend.peers(p->backend.context,peers,&count,&cccds);
    if (rc || count>HP_MAX_PEERS || cccds>24) { return rc ? rc : HP_CAPACITY; }
    for (size_t i=0;i<count;i++) {
        hp_address_t normalized;
        if (!hp_normalize(&normalized,&peers[i].address)) { return HP_INVALID; }
        peers[i].address=normalized; peers[i].id=hp_identity_id(&normalized);
        for (size_t j=0;j<i;j++) { if (peers[j].id==peers[i].id) { return HP_INVALID; } }
        for (unsigned j=0;j<HP_MAX_PEERS;j++) {
            if (hp_address_equal(&p->blob.aliases[j].address,&normalized)) { memcpy(peers[i].alias,p->blob.aliases[j].alias,HP_ALIAS_BYTES+1); }
        }
    }
    bool changed=count!=p->peer_count;
    for (size_t i=0;i<count && !changed;i++) {
        changed=peers[i].id!=p->peers[i].id || peers[i].our_sec!=p->peers[i].our_sec || peers[i].peer_sec!=p->peers[i].peer_sec || peers[i].cccd!=p->peers[i].cccd || peers[i].durable!=p->peers[i].durable || strcmp(peers[i].alias,p->peers[i].alias)!=0;
    }
    if (changed) { p->status.bond_generation++; }
    memcpy(p->peers,peers,sizeof(peers)); p->peer_count=count; p->cccd_count=cccds;
    return 0;
}
static hp_peer_t *find(hp_core_t *p, uint64_t id) {
    for (size_t i=0;i<p->peer_count;i++) { if (p->peers[i].id==id) { return &p->peers[i]; } }
    return NULL;
}
static bool enrollment_existing(const hp_core_t *p, uint64_t id) {
    for (size_t i=0;i<p->enrollment_existing_count;i++) { if (p->enrollment_existing[i]==id) { return true; } }
    return false;
}
void hp_request(hp_core_t *p, hp_mode_t mode, uint64_t target, uint32_t operation, uint32_t timeout_s, uint64_t now_ms) {
    p->status.operation_id=operation; p->status.requested_mode=mode;
    // A failed submission may be attempted again only for a NEW explicit
    // intent. Never loop/retry a failed terminate from background ticks.
    if (p->terminate_failed) { p->terminate_sent=false; p->terminate_failed=false; }
    p->status.filter_ready=false; p->status.hid_ready=false; p->input_subscribed=false;
    p->status.error_domain=HP_DOMAIN_NONE; p->status.error_code=0;
    p->candidate_valid=false; p->candidate_store_started=false;
    p->deadline_ms=0; p->status.enroll_remaining_s=0;
    int rc=hp_refresh(p);
    if (rc) { hp_fail(p,HP_DOMAIN_NVS,rc); return; }
    hp_peer_t *peer=NULL;
    if (mode==HP_AUTO) {
        if (!target) { target=hp_identity_id(&p->blob.selected); }
        peer=find(p,target);
        if (!peer || !peer->our_sec || !peer->durable) { hp_fail(p,HP_DOMAIN_POLICY,HP_NO_TARGET); return; }
    } else if (mode==HP_ENROLL) {
        if (target || timeout_s<5 || timeout_s>120 || p->peer_count>=HP_MAX_PEERS || p->cccd_count>21) { hp_fail(p,HP_DOMAIN_POLICY,HP_CAPACITY); return; }
        if (p->backend.reserve_enrollment) {
            rc=p->backend.reserve_enrollment(p->backend.context);
            if (rc) { hp_fail(p,HP_DOMAIN_NVS,rc); return; }
        }
        p->deadline_ms=now_ms+(uint64_t)timeout_s*1000;
        p->enrollment_existing_count=p->peer_count;
        for (size_t i=0;i<p->peer_count;i++) { p->enrollment_existing[i]=p->peers[i].id; }
    } else if (mode!=HP_PAUSED || target) { hp_fail(p,HP_DOMAIN_POLICY,HP_INVALID); return; }
    // ENROLL never survives boot. Preserve old selected identity while durably pausing first.
    rc=commit(p,mode==HP_AUTO ? HP_AUTO : HP_PAUSED,peer ? &peer->address : NULL);
    if (rc) { hp_fail(p,HP_DOMAIN_NVS,rc); return; }
    p->status.target_id=hp_identity_id(&p->blob.selected);
    rc=p->backend.stop_advertising(p->backend.context);
    if (rc) { hp_fail(p,HP_DOMAIN_NIMBLE,rc); return; }
    p->status.state=HP_SWITCHING; p->status.applied_mode=HP_PAUSED;
    terminate_once(p);
    hp_tick(p,now_ms);
}
void hp_tick(hp_core_t *p, uint64_t now_ms) {
    if (p->status.state==HP_ERROR) { return; }
    if (p->status.requested_mode==HP_ENROLL && p->deadline_ms) {
        if (now_ms>=p->deadline_ms) {
            p->status.requested_mode=HP_PAUSED; p->deadline_ms=0; p->status.enroll_remaining_s=0;
            int stopped=p->backend.stop_advertising(p->backend.context);
            if (stopped) { hp_fail(p,HP_DOMAIN_NIMBLE,stopped); return; }
            p->status.filter_ready=false; p->status.hid_ready=false;
            p->status.applied_mode=HP_PAUSED; p->status.state=HP_STATE_PAUSED;
            p->status.error_domain=HP_DOMAIN_POLICY; p->status.error_code=HP_TIMEOUT;
            terminate_once(p); return;
        }
        p->status.enroll_remaining_s=(uint32_t)((p->deadline_ms-now_ms+999)/1000);
    }
    if (p->status.state==HP_SWITCHING && p->handle==HP_INVALID_HANDLE) {
        if (p->status.requested_mode==HP_PAUSED) { p->status.state=HP_STATE_PAUSED; return; }
        int rc=hp_refresh(p);
        if (rc) { hp_fail(p,HP_DOMAIN_NVS,rc); return; }
        hp_peer_t *peer=find(p,p->status.target_id);
        if (p->status.requested_mode==HP_AUTO && (!peer || !peer->our_sec || !peer->durable)) { hp_fail(p,HP_DOMAIN_POLICY,HP_NO_TARGET); return; }
        rc=p->backend.filter(p->backend.context,p->status.requested_mode==HP_AUTO ? &peer->address : NULL);
        if (rc) { hp_fail(p,HP_DOMAIN_NIMBLE,rc); return; }
        p->status.applied_mode=p->status.requested_mode; p->status.filter_ready=true;
        p->status.state=p->status.applied_mode==HP_AUTO ? HP_WAITING : HP_ENROLLING;
    }
    if (p->handle!=HP_INVALID_HANDLE && !p->status.hid_ready && p->status.encrypted && p->status.bonded && p->input_subscribed) {
        int rc=hp_refresh(p);
        if (rc) { hp_fail(p,HP_DOMAIN_NVS,rc); return; }
        hp_peer_t *peer=find(p,hp_identity_id(&p->connected_address));
        if (!peer || !peer->our_sec || !peer->cccd || !peer->durable) { return; }
        if (p->status.applied_mode==HP_ENROLL) {
            rc=commit(p,HP_AUTO,&peer->address);
            if (rc) { hp_fail(p,HP_DOMAIN_NVS,rc); return; }
            rc=p->backend.filter(p->backend.context,&peer->address);
            if (rc) { hp_fail(p,HP_DOMAIN_NIMBLE,rc); return; }
            p->status.requested_mode=HP_AUTO; p->status.applied_mode=HP_AUTO;
            p->status.target_id=peer->id; p->deadline_ms=0; p->status.enroll_remaining_s=0;
        }
        p->status.hid_ready=true; p->status.state=HP_CONNECTED;
    }
}
uint32_t hp_connect(hp_core_t *p, uint16_t handle, const hp_address_t *address) {
    if (!hp_advertising_allowed(p) || p->handle!=HP_INVALID_HANDLE) { p->backend.terminate(p->backend.context,handle); return 0; }
    hp_address_t normalized;
    bool valid=hp_normalize(&normalized,address);
    if (p->status.applied_mode==HP_AUTO && (!valid || hp_identity_id(&normalized)!=p->status.target_id || !hp_address_equal(&normalized,&p->blob.selected))) { p->backend.terminate(p->backend.context,handle); return 0; }
    if (p->status.applied_mode==HP_ENROLL && valid && (enrollment_existing(p,hp_identity_id(&normalized)) || (p->candidate_valid && !hp_address_equal(&normalized,&p->candidate)))) { p->backend.terminate(p->backend.context,handle); return 0; }
    p->handle=handle; p->terminate_sent=false; p->terminate_failed=false; p->input_subscribed=false;
    p->enrollment_rejected=false;
    p->status.connection_generation++; if (!p->status.connection_generation) { p->status.connection_generation++; }
    p->connected_address=*address; p->status.connected=true;
    p->status.connected_id=valid ? hp_identity_id(&normalized) : 0;
    p->status.encrypted=false; p->status.bonded=false; p->status.hid_ready=false;
    if (p->status.applied_mode==HP_ENROLL && valid) { p->candidate=normalized; p->candidate_valid=true; }
    return p->status.connection_generation;
}
bool hp_reject_enrollment_link(hp_core_t *p, uint16_t handle, uint32_t generation) {
    if (p->status.applied_mode!=HP_ENROLL || p->status.requested_mode!=HP_ENROLL ||
        p->status.state==HP_ERROR || handle==HP_INVALID_HANDLE || handle!=p->handle ||
        generation!=p->status.connection_generation) { return false; }
    if (p->enrollment_rejected) { return true; }
    // SMP can still call the bond store after identity resolution returned.
    // Keep the reject latched through those callbacks and until the next admission.
    p->enrollment_rejected=true;
    if (!p->candidate_store_started) { p->candidate_valid=false; }
    p->status.connected_id=0; p->status.encrypted=false; p->status.bonded=false;
    p->status.filter_ready=false; p->status.hid_ready=false; p->input_subscribed=false;
    p->status.state=HP_SWITCHING;
    terminate_once(p);
    return true;
}
void hp_identity(hp_core_t *p, uint16_t handle, uint32_t generation, const hp_address_t *address) {
    if (handle!=p->handle || generation!=p->status.connection_generation ||
        p->status.state==HP_ERROR || p->enrollment_rejected) { return; }
    hp_address_t normalized;
    if (!hp_normalize(&normalized,address) || (p->status.applied_mode==HP_AUTO && !hp_address_equal(&normalized,&p->blob.selected))) { hp_fail(p,HP_DOMAIN_SECURITY,HP_UNAUTHORIZED); return; }
    if (p->status.applied_mode==HP_ENROLL) {
        if (enrollment_existing(p,hp_identity_id(&normalized)) || (p->candidate_valid && !hp_address_equal(&normalized,&p->candidate))) {
            if (!hp_reject_enrollment_link(p,handle,generation)) { hp_fail(p,HP_DOMAIN_SECURITY,HP_REPEAT_PAIR); }
            return;
        }
        p->candidate=normalized; p->candidate_valid=true;
    }
    p->connected_address=normalized; p->status.connected_id=hp_identity_id(&normalized);
}
void hp_security(hp_core_t *p, uint16_t handle, uint32_t generation, bool encrypted, bool bonded, int error) {
    if (handle!=p->handle || generation!=p->status.connection_generation || p->enrollment_rejected) { return; }
    p->status.encrypted=encrypted; p->status.bonded=bonded;
    if (!encrypted || !bonded) { p->status.hid_ready=false; }
    if (error || !encrypted) { hp_fail(p,HP_DOMAIN_SECURITY,error ? error : HP_UNAUTHORIZED); }
}
void hp_subscribe(hp_core_t *p, uint16_t handle, uint32_t generation, uint16_t input_handle, bool enabled) {
    if (handle!=p->handle || generation!=p->status.connection_generation || p->enrollment_rejected) { return; }
    if (p->hid_input_handle!=input_handle || p->input_subscribed!=enabled) { p->status.subscription_generation++; p->status.hid_ready=false; }
    p->hid_input_handle=input_handle; p->input_subscribed=enabled;
}
void hp_disconnect(hp_core_t *p, uint16_t handle, uint32_t generation, int reason) {
    if (handle!=p->handle || generation!=p->status.connection_generation) { return; }
    p->status.last_disconnect_reason=reason; p->status.last_disconnect_generation=generation;
    p->status.last_disconnect_local=p->terminate_sent;
    p->handle=HP_INVALID_HANDLE; p->status.connected=false; p->status.connected_id=0;
    p->status.encrypted=false; p->status.bonded=false; p->status.hid_ready=false; p->input_subscribed=false;
    p->terminate_sent=false; p->terminate_failed=false;
    if (p->status.state!=HP_ERROR) { p->status.state=HP_SWITCHING; }
}
bool hp_advertising_allowed(const hp_core_t *p) {
    return p->status.filter_ready && p->status.state!=HP_ERROR && p->status.applied_mode!=HP_PAUSED && p->handle==HP_INVALID_HANDLE;
}
bool hp_input_allowed(const hp_core_t *p, uint16_t handle) {
    return p->handle==handle && p->status.applied_mode==HP_AUTO && p->status.state==HP_CONNECTED && p->status.hid_ready && p->status.encrypted && p->status.bonded && p->status.connected_id==p->status.target_id;
}
bool hp_store_allowed(hp_core_t *p, const hp_address_t *address, bool security, bool exists, bool same_keys) {
    hp_address_t normalized;
    if (!hp_normalize(&normalized,address) || p->status.state==HP_ERROR || p->enrollment_rejected) { return false; }
    if (exists && security) { return same_keys; } // Never replace a saved peer's keys.
    if (p->status.applied_mode==HP_AUTO) { return hp_address_equal(&normalized,&p->blob.selected) && (!security || exists); }
    if (p->status.applied_mode!=HP_ENROLL || p->handle==HP_INVALID_HANDLE || enrollment_existing(p,hp_identity_id(&normalized))) { return false; }
    if (p->candidate_valid && !hp_address_equal(&normalized,&p->candidate)) { return false; }
    p->candidate=normalized; p->candidate_valid=true; p->candidate_store_started=true;
    return true;
}
int hp_set_alias(hp_core_t *p, uint64_t id, const char *alias, size_t length) {
    if (!hp_alias_valid(alias,length)) { return HP_INVALID; }
    hp_peer_t *peer=find(p,id);
    if (!peer) { return HP_NO_TARGET; }
    unsigned slot=HP_MAX_PEERS;
    for (unsigned i=0;i<HP_MAX_PEERS;i++) {
        if (hp_address_equal(&p->blob.aliases[i].address,&peer->address)) { slot=i; break; }
        if (slot==HP_MAX_PEERS && !p->blob.aliases[i].alias[0]) { slot=i; }
    }
    if (slot==HP_MAX_PEERS) { return HP_CAPACITY; }
    hp_blob_t old=p->blob;
    p->blob.aliases[slot].address=peer->address; memset(p->blob.aliases[slot].alias,0,HP_ALIAS_BYTES+1);
    memcpy(p->blob.aliases[slot].alias,alias,length);
    int rc=commit(p,(hp_mode_t)p->blob.mode,NULL);
    if (rc) { p->blob=old; hp_fail(p,HP_DOMAIN_NVS,rc); return rc; }
    return hp_refresh(p);
}

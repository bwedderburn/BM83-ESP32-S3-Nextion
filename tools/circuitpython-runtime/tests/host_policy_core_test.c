// SPDX-License-Identifier: MIT
#include "HostPolicyCore.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef struct {
    hp_peer_t peers[9]; size_t count; unsigned cccds;
    hp_blob_t saved; unsigned commits, stops, filters, terms;
    int persist_error, filter_error, terminate_error, peers_error, reserve_error, stop_error;
    int forget_preflight_error, forget_apply_error, peers_after_forget_error;
    unsigned forget_preflights, forget_applies, event_count;
    bool keep_forgotten_peer, filter_was_null;
    char events[128];
    hp_address_t filtered;
} fixture_t;
static hp_address_t addr(unsigned n) { hp_address_t a={.type=0,.val={1,2,3,4,5,0}};a.val[5]=(uint8_t)n;return a; }
static hp_peer_t peer(unsigned n) { hp_peer_t p={.address=addr(n),.our_sec=true,.peer_sec=true,.cccd=true,.durable=true};p.id=hp_identity_id(&p.address);return p; }
static void event(fixture_t *f, char value) {
    assert(f->event_count+1 < sizeof(f->events));
    f->events[f->event_count++]=value; f->events[f->event_count]=0;
}
static int persist(void *c,const hp_blob_t *b) { fixture_t *f=c;event(f,'C');f->commits++;if(f->persist_error)return f->persist_error;f->saved=*b;return 0; }
static int stop(void *c) { fixture_t *f=c;event(f,'S');f->stops++;return f->stop_error; }
static int terminate(void *c,uint16_t h) { fixture_t *f=c;event(f,'T');(void)h;f->terms++;return f->terminate_error; }
static int filter(void *c,const hp_address_t *a) { fixture_t *f=c;event(f,'F');f->filters++;f->filter_was_null=a==NULL;if(a)f->filtered=*a;return f->filter_error; }
static int peers(void *c,hp_peer_t *p,size_t *count,unsigned *cccds) { fixture_t *f=c;event(f,'R');if(f->peers_error)return f->peers_error;*count=f->count;*cccds=f->cccds;if(f->count<=8)memcpy(p,f->peers,f->count*sizeof(*p));return 0; }
static int reserve(void *c) { return ((fixture_t *)c)->reserve_error; }
static int forget(void *c, const hp_address_t *address, bool apply) {
    fixture_t *f=c;
    if (!apply) {
        event(f,'V'); f->forget_preflights++;
        return f->forget_preflight_error;
    }
    event(f,'D'); f->forget_applies++;
    assert(f->saved.mode==HP_PAUSED);
    for (unsigned i=0; i<HP_MAX_PEERS; i++) {
        assert(!hp_address_equal(&f->saved.aliases[i].address,address));
    }
    assert(!hp_address_equal(&f->saved.selected,address));
    if (f->forget_apply_error) { return f->forget_apply_error; }
    if (!f->keep_forgotten_peer) {
        for (size_t i=0; i<f->count; i++) {
            if (hp_address_equal(&f->peers[i].address,address)) {
                memmove(&f->peers[i],&f->peers[i+1],(f->count-i-1)*sizeof(f->peers[0]));
                f->count--;
                if (f->cccds) { f->cccds--; }
                break;
            }
        }
    }
    f->peers_error=f->peers_after_forget_error;
    return 0;
}
static void setup(fixture_t *f,hp_core_t *p) { memset(f,0,sizeof(*f));f->count=2;f->peers[0]=peer(6);f->peers[1]=peer(7);f->cccds=6;hp_backend_t b={f,persist,stop,terminate,filter,peers,reserve,forget};hp_init(p,&b,NULL,0); }
static uint32_t connect_ready(fixture_t *f,hp_core_t *p,unsigned index,uint16_t handle) { uint32_t g=hp_connect(p,handle,&f->peers[index].address);assert(g);hp_security(p,handle,g,true,true,0);hp_subscribe(p,handle,g,123,true);hp_tick(p,200);assert(hp_input_allowed(p,handle));return g; }
static void test_late_saved_identity_keeps_the_pairing_window(void) {
    fixture_t fixture;
    hp_core_t policy;
    setup(&fixture, &policy);
    hp_request(&policy, HP_ENROLL, 0, 100, 60, 0);
    hp_address_t private_address = {.type=1, .val={1,2,3,4,5,0x40}};
    const uint16_t handle = 42;
    uint32_t rejected = hp_connect(&policy, handle, &private_address);
    assert(rejected && policy.status.connected && !policy.status.connected_id);

    hp_identity(&policy, handle, rejected, &fixture.peers[0].address);
    assert(policy.enrollment_rejected && fixture.terms == 1 && policy.status.state == HP_SWITCHING);
    assert(policy.deadline_ms == 60000 && policy.status.operation_id == 100 && fixture.saved.mode == HP_PAUSED);
    assert(!hp_store_allowed(&policy, &fixture.peers[0].address, true, true, true));
    hp_security(&policy, handle, rejected, true, true, 0);
    hp_subscribe(&policy, handle, rejected, 123, true);
    assert(!policy.status.encrypted && !policy.input_subscribed && !hp_advertising_allowed(&policy));

    hp_disconnect(&policy, handle, rejected, 0x216);
    hp_tick(&policy, 1000);
    assert(policy.status.state == HP_ENROLLING && hp_advertising_allowed(&policy));
    assert(policy.status.error_domain == HP_DOMAIN_NONE && policy.status.enroll_remaining_s == 59);
    assert(!hp_store_allowed(&policy, &fixture.peers[0].address, true, true, true));

    hp_address_t new_address = addr(8);
    uint32_t admitted = hp_connect(&policy, handle, &new_address);
    assert(admitted && admitted != rejected && !policy.enrollment_rejected);
    assert(!hp_reject_enrollment_link(&policy, handle, rejected));
    hp_identity(&policy, handle, rejected, &fixture.peers[0].address);
    assert(hp_store_allowed(&policy, &new_address, true, false, false));
    hp_security(&policy, handle, admitted, true, true, 0);
    hp_subscribe(&policy, handle, admitted, 123, true);
    fixture.peers[2] = peer(8);
    fixture.count = 3;
    hp_tick(&policy, 1200);
    assert(policy.status.state == HP_CONNECTED && policy.status.target_id == fixture.peers[2].id);
    assert(hp_input_allowed(&policy, handle) && policy.peer_count == 3 && fixture.terms == 1);
}

static void test_enrollment_reject_drains_late_callbacks_after_handle_loss(void) {
    fixture_t fixture;
    hp_core_t policy;
    setup(&fixture, &policy);
    hp_request(&policy, HP_ENROLL, 0, 101, 5, 0);
    hp_address_t private_address = {.type=1, .val={1,2,3,4,5,0x40}};
    const uint16_t handle = 41;
    uint32_t generation = hp_connect(&policy, handle, &private_address);
    assert(generation);
    fixture.terminate_error = HP_TERMINATE_ABSENT;
    assert(hp_reject_enrollment_link(&policy, handle, generation));
    assert(policy.enrollment_rejected && policy.handle == HP_INVALID_HANDLE);
    assert(!hp_store_allowed(&policy, &fixture.peers[0].address, true, true, true));
    hp_tick(&policy, 1000);
    assert(policy.status.state == HP_ENROLLING && policy.status.operation_id == 101);
    hp_tick(&policy, 5000);
    assert(policy.status.state == HP_STATE_PAUSED && policy.status.error_code == HP_TIMEOUT);
    assert(fixture.terms == 1 && !hp_advertising_allowed(&policy));
}

static void test_enrollment_termination_failure_survives_expiry(void) {
    fixture_t fixture;
    hp_core_t policy;
    setup(&fixture, &policy);
    hp_request(&policy, HP_ENROLL, 0, 102, 5, 0);
    hp_address_t private_address = {.type=1, .val={1,2,3,4,5,0x40}};
    uint32_t generation = hp_connect(&policy, 41, &private_address);
    assert(generation);
    fixture.terminate_error = 88;
    assert(hp_reject_enrollment_link(&policy, 41, generation));
    assert(policy.status.state == HP_ERROR && policy.status.error_domain == HP_DOMAIN_NIMBLE);
    hp_tick(&policy, 5000);
    assert(policy.status.error_code == 88 && policy.status.state == HP_ERROR);
    assert(fixture.terms == 1 && fixture.saved.mode == HP_PAUSED && !hp_advertising_allowed(&policy));
}
static void forget_ready(fixture_t *f, hp_core_t *p, bool select_target) {
    setup(f,p);
    uint64_t selected=f->peers[select_target ? 0 : 1].id;
    hp_request(p,HP_AUTO,selected,201,60,0);
    assert(!hp_set_alias(p,f->peers[0].id,"Target",6));
    assert(!hp_set_alias(p,f->peers[1].id,"Other",5));
    p->blob.aliases[3]=p->blob.aliases[0];
    hp_request(p,HP_PAUSED,0,202,60,1);
    assert(hp_forget_allowed(&p->status,p->handle));
    f->event_count=0; f->events[0]=0;
    f->commits=0; f->stops=0; f->filters=0; f->terms=0;
}

static void assert_aliases_and_selection_kept(const hp_blob_t *before, const hp_blob_t *after) {
    assert(memcmp(&before->selected,&after->selected,sizeof(before->selected))==0);
    assert(memcmp(before->aliases,after->aliases,sizeof(before->aliases))==0);
}

static void test_forget_success_preserves_other_policy_and_clears_target(void) {
    for (unsigned selected=0; selected<2; selected++) {
        fixture_t f;
        hp_core_t p;
        forget_ready(&f,&p,selected==0);
        hp_blob_t before=p.blob;
        hp_peer_t other=f.peers[1];
        uint64_t target=f.peers[0].id;
        uint32_t generation=p.status.bond_generation;
        p.status.operation_id=203;
        hp_forget(&p,target,generation);
        assert(strcmp(f.events,"RVSFCDR")==0);
        assert(f.stops==1 && f.filters==1 && f.filter_was_null);
        assert(f.commits==1 && f.forget_preflights==1 && f.forget_applies==1 && !f.terms);
        assert(p.status.operation_id==203 && hp_forget_allowed(&p.status,p.handle));
        assert(p.status.bond_generation!=generation && p.peer_count==1 && p.peers[0].id==other.id);
        assert(f.count==1 && memcmp(&other,&f.peers[0],sizeof(other))==0);
        assert(memcmp(&before.aliases[1],&p.blob.aliases[1],sizeof(hp_alias_t))==0);
        assert(p.blob.aliases[0].alias[0]==0 && p.blob.aliases[3].alias[0]==0);
        assert(!hp_identity_id(&p.blob.aliases[0].address) && !hp_identity_id(&p.blob.aliases[3].address));
        assert(hp_blob_valid(&f.saved) && p.blob.mode==HP_PAUSED);
        if (!selected) {
            hp_address_t empty={0};
            assert(memcmp(&p.blob.selected,&empty,sizeof(empty))==0 && p.status.target_id==0);
        } else {
            assert(memcmp(&before.selected,&p.blob.selected,sizeof(before.selected))==0);
            assert(p.status.target_id==other.id);
        }
        assert(memcmp(&f.saved,&p.blob,sizeof(p.blob))==0);
    }
}

static void test_forget_refusal_order_and_errors(void) {
    for (unsigned failure=0; failure<10; failure++) {
        fixture_t f;
        hp_core_t p;
        forget_ready(&f,&p,true);
        hp_blob_t before=p.blob;
        uint64_t target=f.peers[0].id;
        uint32_t generation=p.status.bond_generation;
        hp_domain_t domain=HP_DOMAIN_NVS;
        int code=0;
        switch (failure) {
            case 0: f.peers_error=101; code=101; generation--; target=0; break;
            case 1: generation--; target=0; domain=HP_DOMAIN_POLICY; code=HP_STALE; break;
            case 2: target=0; domain=HP_DOMAIN_POLICY; code=HP_NO_TARGET; break;
            case 3: f.forget_preflight_error=102; code=102; break;
            case 4: f.stop_error=103; domain=HP_DOMAIN_NIMBLE; code=103; break;
            case 5: f.filter_error=104; domain=HP_DOMAIN_NIMBLE; code=104; break;
            case 6: f.persist_error=105; code=105; break;
            case 7: p.backend.forget=NULL; code=HP_STORAGE; break;
            case 8: f.forget_apply_error=106; code=106; break;
            case 9: f.peers_after_forget_error=107; code=107; break;
        }
        hp_forget(&p,target,generation);
        assert(p.status.state==HP_ERROR && p.status.applied_mode==HP_PAUSED);
        assert(p.status.error_domain==domain && p.status.error_code==code);
        assert(!hp_advertising_allowed(&p) && !p.status.hid_ready);
        if (failure<8) {
            assert(!f.forget_applies);
            assert_aliases_and_selection_kept(&before,&p.blob);
            if (failure!=6) { assert_aliases_and_selection_kept(&before,&f.saved); }
        } else {
            assert(f.forget_applies==1 && !p.status.target_id);
            assert(!p.blob.aliases[0].alias[0] && !p.blob.aliases[3].alias[0]);
        }
        if (failure<3 || failure==7) { assert(!f.forget_preflights); }
        else { assert(f.forget_preflights==1); }
        unsigned calls=f.forget_preflights+f.forget_applies;
        hp_tick(&p,50);
        hp_tick(&p,100);
        assert(f.forget_preflights+f.forget_applies==calls);
    }
    fixture_t f;
    hp_core_t p;
    forget_ready(&f,&p,true);
    f.keep_forgotten_peer=true;
    hp_forget(&p,f.peers[0].id,p.status.bond_generation);
    assert(p.status.state==HP_ERROR && p.status.error_domain==HP_DOMAIN_NVS);
    assert(p.status.error_code==HP_STORAGE && f.forget_applies==1);
}

static void test_forget_clean_paused_predicate_and_live_link_failure(void) {
    for (unsigned condition=0; condition<8; condition++) {
        fixture_t f;
        hp_core_t p;
        forget_ready(&f,&p,true);
        hp_blob_t before=p.blob;
        switch (condition) {
            case 0: p.status.state=HP_WAITING; break;
            case 1: p.status.requested_mode=HP_AUTO; break;
            case 2: p.status.applied_mode=HP_ENROLL; break;
            case 3: p.status.persisted=false; break;
            case 4: p.handle=9; break;
            case 5: p.status.connected=true; break;
            case 6: p.status.error_domain=HP_DOMAIN_NVS; break;
            case 7: p.status.error_code=HP_STORAGE; break;
        }
        assert(!hp_forget_allowed(&p.status,p.handle));
        hp_forget(&p,0,p.status.bond_generation-1);
        assert(p.status.state==HP_ERROR && p.status.error_domain==HP_DOMAIN_POLICY);
        assert(p.status.error_code==HP_INVALID && !f.forget_applies && !f.forget_preflights);
        assert(f.events[0]=='C');
        assert_aliases_and_selection_kept(&before,&p.blob);
        assert(f.terms==(condition==4));
    }
    fixture_t f;
    hp_core_t p;
    forget_ready(&f,&p,true);
    // The observed modes/state and actual link own admission. Cached peer
    // and readiness fields cannot add requirements to the PAUSED contract.
    p.status.connected_id=f.peers[0].id;
    p.status.filter_ready=true;
    p.status.encrypted=true;
    p.status.bonded=true;
    p.status.hid_ready=true;
    p.status.enroll_remaining_s=1;
    assert(hp_forget_allowed(&p.status,p.handle));
    hp_forget(&p,f.peers[0].id,p.status.bond_generation);
    assert(p.status.state==HP_STATE_PAUSED && p.status.requested_mode==HP_PAUSED);
    assert(p.status.applied_mode==HP_PAUSED && f.forget_applies==1);
}

static void test_forget_failure_then_explicit_pause_and_retry(void) {
    fixture_t f;
    hp_core_t p;
    forget_ready(&f,&p,true);
    uint64_t target=f.peers[0].id;
    f.forget_apply_error=222;
    hp_forget(&p,target,p.status.bond_generation);
    assert(p.status.state==HP_ERROR && f.count==2 && f.forget_applies==1);
    f.forget_apply_error=0;
    hp_request(&p,HP_PAUSED,0,204,60,5);
    assert(hp_forget_allowed(&p.status,p.handle));
    hp_forget(&p,target,p.status.bond_generation);
    assert(hp_forget_allowed(&p.status,p.handle) && f.count==1 && f.forget_applies==2);
}

static void test_forgotten_identity_can_reenroll(void) {
    fixture_t f;
    hp_core_t p;
    forget_ready(&f,&p,true);
    hp_address_t address=f.peers[0].address;
    uint64_t id=f.peers[0].id;
    hp_forget(&p,id,p.status.bond_generation);
    assert(p.peer_count==1 && p.peers[0].id!=id);
    hp_request(&p,HP_ENROLL,0,205,60,10);
    assert(p.status.state==HP_ENROLLING && p.enrollment_existing_count==1);
    assert(p.enrollment_existing[0]!=id);
    uint32_t generation=hp_connect(&p,42,&address);
    assert(generation);
    hp_identity(&p,42,generation,&address);
    assert(!p.enrollment_rejected && hp_store_allowed(&p,&address,true,false,false));
    hp_security(&p,42,generation,true,true,0);
    hp_subscribe(&p,42,generation,123,true);
    f.peers[f.count++]=peer(6);
    hp_tick(&p,20);
    assert(p.status.state==HP_CONNECTED && p.status.requested_mode==HP_AUTO);
    assert(p.status.applied_mode==HP_AUTO && p.status.target_id==id && p.status.hid_ready);
}

static void test_forget_queue_rules(void) {
    hp_queue_t queue={0};
    hp_command_t forget_command={.forget=true,.target=99,.generation=7};
    hp_command_t pause={.mode=HP_PAUSED};
    hp_command_t alias={.alias=true};
    hp_command_t automatic={.mode=HP_AUTO};
    hp_command_t popped;
    assert(!hp_submit(&queue,&automatic));
    uint32_t operation=queue.next_operation;
    assert(hp_submit(&queue,&forget_command)==HP_QUEUE_FULL && queue.next_operation==operation);
    assert(queue.command.mode==HP_AUTO && !queue.command.forget);
    assert(hp_pop(&queue,&popped));
    assert(!hp_submit(&queue,&forget_command));
    operation=forget_command.operation;
    assert(operation && hp_submit(&queue,&forget_command)==HP_QUEUE_FULL);
    assert(hp_submit(&queue,&alias)==HP_QUEUE_FULL && hp_submit(&queue,&automatic)==HP_QUEUE_FULL);
    assert(queue.next_operation==operation && queue.command.forget);
    assert(!hp_submit(&queue,&pause) && pause.operation!=operation);
    assert(hp_pop(&queue,&popped) && !popped.forget && popped.mode==HP_PAUSED);
    assert(!hp_pop(&queue,&popped));
    assert(!hp_submit(&queue,&alias));
    assert(hp_submit(&queue,&forget_command)==HP_QUEUE_FULL);
    assert(hp_pop(&queue,&popped) && popped.alias);
    queue.next_operation=UINT32_MAX;
    assert(!hp_submit(&queue,&forget_command) && forget_command.operation==1);
    assert(hp_pop(&queue,&popped) && popped.forget && popped.generation==7 && popped.target==99);
}

int main(void) {
    test_forget_success_preserves_other_policy_and_clears_target();
    test_forget_refusal_order_and_errors();
    test_forget_clean_paused_predicate_and_live_link_failure();
    test_forget_failure_then_explicit_pause_and_retry();
    test_forgotten_identity_can_reenroll();
    test_forget_queue_rules();
    test_late_saved_identity_keeps_the_pairing_window();
    test_enrollment_reject_drains_late_callbacks_after_handle_loss();
    test_enrollment_termination_failure_survives_expiry();
    fixture_t f;hp_core_t p;setup(&f,&p);
    assert(p.status.state==HP_STATE_PAUSED&&!hp_advertising_allowed(&p));
    hp_request(&p,HP_AUTO,0,1,60,0);assert(p.status.state==HP_ERROR&&!hp_advertising_allowed(&p));
    setup(&f,&p);hp_request(&p,HP_AUTO,f.peers[0].id,2,60,0);assert(p.status.state==HP_WAITING&&hp_advertising_allowed(&p));
    uint32_t generation=connect_ready(&f,&p,0,42);
    hp_disconnect(&p,42,generation,0x213);assert(p.status.last_disconnect_reason==0x213&&!p.status.last_disconnect_local);
    hp_tick(&p,500);assert(p.status.requested_mode==HP_AUTO&&p.status.state==HP_WAITING&&hp_address_equal(&f.filtered,&f.peers[0].address));
    generation=connect_ready(&f,&p,0,42);hp_request(&p,HP_PAUSED,0,3,60,1000);assert(f.terms==1&&!hp_input_allowed(&p,42)&&f.saved.mode==HP_PAUSED);
    hp_tick(&p,1100);assert(f.terms==1);hp_disconnect(&p,42,generation,0x216);hp_tick(&p,1200);assert(p.status.state==HP_STATE_PAUSED&&!hp_advertising_allowed(&p));
    hp_core_t reboot;hp_init(&reboot,&p.backend,&f.saved,0);assert(reboot.status.state==HP_STATE_PAUSED);
    hp_request(&p,HP_AUTO,f.peers[0].id,4,60,1300);generation=connect_ready(&f,&p,0,55);
    hp_request(&p,HP_AUTO,f.peers[1].id,5,60,1400);assert(p.status.state==HP_SWITCHING&&!p.status.filter_ready);
    hp_disconnect(&p,55,generation,0x216);hp_tick(&p,1500);uint32_t next=connect_ready(&f,&p,1,55);assert(next!=generation);
    hp_disconnect(&p,55,generation,0x213);assert(p.status.connected&&hp_input_allowed(&p,55));
    assert(!hp_store_allowed(&p,&f.peers[1].address,true,true,false));
    hp_fail(&p,HP_DOMAIN_SECURITY,HP_REPEAT_PAIR);assert(!hp_input_allowed(&p,55)&&p.status.state==HP_ERROR&&f.saved.mode==HP_PAUSED);
    setup(&f,&p);f.filter_error=99;hp_request(&p,HP_AUTO,f.peers[0].id,6,60,0);assert(p.status.state==HP_ERROR&&!hp_advertising_allowed(&p)&&f.saved.mode==HP_PAUSED);
    setup(&f,&p);f.persist_error=77;hp_request(&p,HP_PAUSED,0,7,60,0);assert(!p.status.persisted&&p.status.state==HP_ERROR);
    setup(&f,&p);hp_request(&p,HP_AUTO,f.peers[0].id,70,60,0);generation=connect_ready(&f,&p,0,70);
    f.terminate_error=88;hp_request(&p,HP_PAUSED,0,71,60,0);assert(p.status.state==HP_ERROR&&f.terms==1);
    hp_tick(&p,10);hp_tick(&p,20);assert(f.terms==1);
    f.terminate_error=0;hp_request(&p,HP_PAUSED,0,72,60,30);assert(f.terms==2&&p.status.state==HP_SWITCHING);
    hp_disconnect(&p,70,generation,0x216);hp_tick(&p,40);assert(p.status.state==HP_STATE_PAUSED);
    hp_request(&p,HP_AUTO,f.peers[0].id,73,60,50);generation=connect_ready(&f,&p,0,71);(void)generation;
    int old_reason=p.status.last_disconnect_reason;f.terminate_error=HP_TERMINATE_ABSENT;
    hp_request(&p,HP_PAUSED,0,74,60,60);assert(p.status.state==HP_STATE_PAUSED&&!p.status.connected&&p.status.last_disconnect_reason==old_reason);
    setup(&f,&p);f.count=8;for(unsigned i=0;i<8;i++)f.peers[i]=peer(i+10);hp_request(&p,HP_ENROLL,0,8,60,0);assert(p.status.state==HP_ERROR&&!hp_advertising_allowed(&p));
    setup(&f,&p);f.cccds=22;hp_request(&p,HP_ENROLL,0,9,60,0);assert(p.status.state==HP_ERROR);
    setup(&f,&p);f.reserve_error=HP_CAPACITY;hp_request(&p,HP_ENROLL,0,90,60,0);assert(p.status.state==HP_ERROR&&!hp_advertising_allowed(&p));
    setup(&f,&p);f.peers[0].peer_sec=false;hp_request(&p,HP_AUTO,f.peers[0].id,91,60,0);assert(p.status.state==HP_WAITING);connect_ready(&f,&p,0,91);
    setup(&f,&p);f.peers[0].our_sec=false;hp_request(&p,HP_AUTO,f.peers[0].id,92,60,0);assert(p.status.state==HP_ERROR);
    setup(&f,&p);hp_request(&p,HP_ENROLL,0,10,5,0);assert(p.status.state==HP_ENROLLING);hp_tick(&p,5000);assert(p.status.applied_mode==HP_PAUSED&&!hp_advertising_allowed(&p));
    // A start queued while ENROLL was allowed must re-check on the serialized
    // host task after autonomous expiry, never re-use the old VM guard result.
    setup(&f,&p);hp_request(&p,HP_ENROLL,0,100,5,0);bool queued_allowed=hp_advertising_allowed(&p);assert(queued_allowed);
    hp_tick(&p,5000);unsigned actual_starts=0;if(hp_advertising_allowed(&p))actual_starts++;assert(actual_starts==0&&p.status.state==HP_STATE_PAUSED);
    setup(&f,&p);hp_request(&p,HP_ENROLL,0,11,60,0);assert(!hp_connect(&p,66,&f.peers[0].address));
    hp_address_t fresh=addr(8);generation=hp_connect(&p,67,&fresh);assert(generation);
    assert(hp_store_allowed(&p,&fresh,true,false,false));assert(!hp_store_allowed(&p,&f.peers[0].address,true,true,false));
    hp_security(&p,67,generation,true,true,0);hp_subscribe(&p,67,generation,123,true);
    f.peers[2]=peer(8);f.peers[2].durable=false;f.count=3;hp_tick(&p,200);assert(!p.status.hid_ready&&p.status.applied_mode==HP_ENROLL);
    f.peers[2].durable=true;hp_tick(&p,300);assert(p.status.operation_id==11&&p.status.applied_mode==HP_AUTO&&p.status.target_id==f.peers[2].id&&hp_input_allowed(&p,67));
    assert(hp_set_alias(&p,f.peers[2].id,"B-Intel",7)==0);assert(hp_blob_valid(&f.saved));uint32_t bond_generation=p.status.bond_generation;assert(bond_generation>0);
    assert(hp_alias_valid("Mac \xe2\x99\xab",7));assert(!hp_alias_valid("\xc0\x80",2));assert(!hp_alias_valid("\xc2\x85",2));assert(!hp_alias_valid("bad\x7f",4));assert(!hp_alias_valid("\xed\xa0\x80",3));
    hp_blob_t corrupt=f.saved;corrupt.aliases[0].alias[0]^=1;hp_init(&reboot,&p.backend,&corrupt,0);assert(reboot.status.state==HP_ERROR&&!hp_advertising_allowed(&reboot));
    hp_address_t rpa={.type=1,.val={1,2,3,4,5,0x40}},normalized;assert(!hp_normalize(&normalized,&rpa)&&!hp_identity_id(&rpa));
    hp_address_t identity=addr(6);identity.type=2;assert(hp_identity_id(&identity)==f.peers[0].id);
    setup(&f,&p);f.peers_error=HP_STALE;hp_request(&p,HP_AUTO,f.peers[0].id,12,60,0);assert(p.status.state==HP_ERROR);
    hp_queue_t queue={0};hp_command_t a={.mode=HP_AUTO},b={.mode=HP_ENROLL},pause={.mode=HP_PAUSED},taken;
    assert(!hp_submit(&queue,&a)&&a.operation==1);assert(hp_submit(&queue,&b)==HP_QUEUE_FULL);assert(!hp_submit(&queue,&pause)&&pause.operation==2);assert(hp_pop(&queue,&taken)&&taken.mode==HP_PAUSED&&taken.operation==2);assert(!hp_pop(&queue,&taken));
    puts("PASS production host-policy core: persistence/admission/enrollment/generation/capacity/store/queue fault cases");
    return 0;
}

// Appended after the actual production bridge and its external-stub harness.
// No alternate decision implementation is used to exercise new counters.
static bool legacy_admission_accepts(const hp_core_t *p, const hp_address_t *a) {
    if (!hp_advertising_allowed(p) || p->handle!=HP_INVALID_HANDLE) { return false; }
    hp_address_t normalized;
    bool valid=hp_normalize(&normalized,a);
    if (p->status.applied_mode==HP_AUTO && (!valid || hp_identity_id(&normalized)!=p->status.target_id ||
        !hp_address_equal(&normalized,&p->blob.selected))) { return false; }
    bool saved=false;
    if (valid) {
        for (size_t i=0;i<p->enrollment_existing_count;i++) {
            if (p->enrollment_existing[i]==hp_identity_id(&normalized)) { saved=true; }
        }
    }
    return !(p->status.applied_mode==HP_ENROLL && valid &&
        (saved || (p->candidate_valid && !hp_address_equal(&normalized,&p->candidate))));
}
static void test_admission_classification_is_observational(void) {
    unsigned cases=0;
    for (unsigned mode=0;mode<3;mode++) for (unsigned filter_ready=0;filter_ready<2;filter_ready++)
    for (unsigned failed=0;failed<2;failed++) for (unsigned busy=0;busy<2;busy++)
    for (unsigned identity=0;identity<8;identity++) for (unsigned candidate=0;candidate<2;candidate++) {
        reset();
        core.status.applied_mode=(hp_mode_t)mode;core.status.filter_ready=filter_ready;
        core.status.state=failed ? HP_ERROR : mode==HP_ENROLL ? HP_ENROLLING : HP_WAITING;
        core.handle=busy ? 42 : HP_INVALID_HANDLE;
        core.blob.selected=core.peers[0].address;core.status.target_id=core.peers[0].id;
        core.enrollment_existing_count=1;core.enrollment_existing[0]=core.peers[0].id;
        core.candidate=address(&(ble_addr_t){.type=0,.val={1,2,3,4,5,8}});core.candidate_valid=candidate;
        hp_address_t inputs[]={core.peers[0].address, address(&(ble_addr_t){.type=0,.val={1,2,3,4,5,7}}),
            core.candidate, address(&(ble_addr_t){.type=1,.val={1,2,3,4,5,0x40}}),
            address(&(ble_addr_t){.type=2,.val={1,2,3,4,5,6}}), address(&(ble_addr_t){.type=2,.val={1,2,3,4,5,7}}),
            address(&(ble_addr_t){.type=3,.val={1,2,3,4,5,0xc8}}), address(&(ble_addr_t){0})};
        hp_address_t input=inputs[identity];
        bool accepted=legacy_admission_accepts(&core,&input);
        hp_core_t before=core;unsigned prior_terminations=terminations;
        assert((hp_connect_reason(&core,&input)==HP_CONNECT_ACCEPT)==accepted);
        assert(!memcmp(&before,&core,sizeof(core)) && terminations==prior_terminations);
        uint32_t result=hp_connect(&core,55,&input);
        assert((result!=0)==accepted && terminations==prior_terminations+!accepted);
        if (!accepted) { assert(!memcmp(&before,&core,sizeof(core))); }
        cases++;
    }
    assert(cases==384);
}
static void test_pre_admission_bridge_counters(void) {
    reset();memset(&diagnostics,0,sizeof(diagnostics));
    synced=false;assert(!bleio_host_policy_connect(50));
    assert(diagnostics.admission_attempts==1 && diagnostics.refused_unsynced==1 &&
        diagnostics.last_refusal_reason==HP_REFUSE_UNSYNCED && core.status.connection_generation==0 && terminations==1);

    reset();memset(&diagnostics,0,sizeof(diagnostics));
    restore_vendor_callbacks();assert(!bleio_host_policy_connect(50));
    assert(diagnostics.refused_store_guard==1 && core.status.connection_generation==0 && terminations==1);

    reset();memset(&diagnostics,0,sizeof(diagnostics));
    test_connection.conn_handle=49;assert(!bleio_host_policy_connect(50));
    assert(diagnostics.refused_conn_missing==1 && !core.status.connection_generation);

    reset();memset(&diagnostics,0,sizeof(diagnostics));
    hp_request(&core,HP_ENROLL,0,701,60,0);
    ble_addr_t rpa={.type=BLE_ADDR_RANDOM,.val={0x44,0x22,0x33,1,2,0x40}};
    test_connection=(struct ble_gap_conn_desc){.conn_handle=50,.peer_id_addr=rpa,.peer_ota_addr=rpa};
    unsigned before_writes=writes,before_deletes=deletes,before_commits=nvs_commits;
    assert(!bleio_host_policy_connect(50));
    assert(diagnostics.saved_irk_matches==1 && diagnostics.refused_saved_identity==1 &&
        !diagnostics.admissions && !core.status.connection_generation && !core.candidate_valid);
    assert(writes==before_writes && deletes==before_deletes && nvs_commits==before_commits &&
        core.status.state==HP_ENROLLING && !fault_pending);

    reset();memset(&diagnostics,0,sizeof(diagnostics));
    hp_request(&core,HP_ENROLL,0,704,60,0);
    test_connection=(struct ble_gap_conn_desc){.conn_handle=50,.peer_id_addr=rpa,.peer_ota_addr=rpa};
    records[BLE_STORE_OBJ_TYPE_PEER_SEC][1]=records[BLE_STORE_OBJ_TYPE_PEER_SEC][0];
    records[BLE_STORE_OBJ_TYPE_PEER_SEC][1].ram.sec.peer_addr=test_address(7);
    assert(!bleio_host_policy_connect(50));
    assert(diagnostics.refused_resolver==1 && diagnostics.saved_irk_matches==0 && fault_pending &&
        !core.status.connection_generation && pending_fault==HP_INVALID);

    reset();memset(&diagnostics,0,sizeof(diagnostics));
    hp_request(&core,HP_ENROLL,0,702,60,0);
    core.candidate=address(&(ble_addr_t){.type=0,.val={1,2,3,4,5,8}});core.candidate_valid=true;
    test_connection=(struct ble_gap_conn_desc){.conn_handle=50,.peer_id_addr=test_address(7),.peer_ota_addr=test_address(7)};
    assert(!bleio_host_policy_connect(50) && diagnostics.refused_candidate==1 && !core.status.connection_generation);

    reset();memset(&diagnostics,0,sizeof(diagnostics));
    test_connection=(struct ble_gap_conn_desc){.conn_handle=50,.peer_id_addr=test_address(7),.peer_ota_addr=test_address(7)};
    assert(!bleio_host_policy_connect(50) && diagnostics.refused_policy==1);
    hp_request(&core,HP_AUTO,core.peers[0].id,703,60,0);
    assert(!bleio_host_policy_connect(50) && diagnostics.refused_auto_identity==1);
    test_connection.peer_id_addr=test_address(6);test_connection.peer_ota_addr=test_address(6);
    assert(bleio_host_policy_connect(50) && diagnostics.admissions==1);
    assert(!bleio_host_policy_connect(50) && diagnostics.refused_slot==1 && core.status.connection_generation==1);
    bleio_host_policy_observe_adapter_no_slot();assert(diagnostics.refused_adapter_slot==1);
    assert(!diagnostics.adapter_publications);
    bleio_host_policy_observe_adapter_publication();assert(diagnostics.adapter_publications==1);
    bleio_host_policy_connection_attach_failed(50,core.status.connection_generation,BLE_HS_ENOTCONN);
    assert(diagnostics.attach_failures==1);
}
static void test_raw_callback_and_stop_observations(void) {
    reset();memset(&diagnostics,0,sizeof(diagnostics));
    struct ble_gap_event raw={.type=BLE_GAP_EVENT_CONNECT,.connect={.status=0x213,.conn_handle=50}};
    hp_core_t before=core;
    bleio_host_policy_observe_gap_event(&raw,HP_GAP_SOURCE_ADVERTISING);
    assert(diagnostics.connect_events==1 && diagnostics.connect_failures==1 && !diagnostics.connect_successes &&
        diagnostics.last_connect_status==0x213 && diagnostics.last_connect_source==HP_GAP_SOURCE_ADVERTISING);
    assert(!memcmp(&before,&core,sizeof(core)) && !terminations);
    raw.connect.status=0;bleio_host_policy_observe_gap_event(&raw,HP_GAP_SOURCE_CONNECTION);
    assert(diagnostics.connect_events==2 && diagnostics.connect_successes==1 && !core.status.connection_generation);
    raw=(struct ble_gap_event){.type=BLE_GAP_EVENT_ADV_COMPLETE,.adv_complete={.reason=0}};
    bleio_host_policy_observe_gap_event(&raw,HP_GAP_SOURCE_ADVERTISING);
    raw.adv_complete.reason=BLE_HS_ETIMEOUT;bleio_host_policy_observe_gap_event(&raw,HP_GAP_SOURCE_ADVERTISING);
    assert(diagnostics.adv_complete_events==2 && diagnostics.adv_complete_zero_reason==1 &&
        diagnostics.adv_complete_nonzero_reason==1 && diagnostics.last_adv_complete_reason==BLE_HS_ETIMEOUT);
    bleio_host_policy_observe_vm_adv_stop(false,0);bleio_host_policy_observe_vm_adv_stop(true,77);
    assert(diagnostics.vm_stop_requests==2 && diagnostics.vm_stop_active==1 && diagnostics.vm_stop_errors==1 &&
        diagnostics.last_stop_result==77);
    stop_fail=78;assert(stop_advertising(NULL)==78);
    assert(diagnostics.policy_stop_calls==1 && diagnostics.policy_stop_errors==1 &&
        diagnostics.last_adv_cause==HP_ADV_CAUSE_POLICY_STOP && diagnostics.last_stop_result==78);
    assert(!memcmp(&before,&core,sizeof(core)) && !test_lock_depth);
    diagnostics.connect_events=diagnostics.event_sequence=UINT32_MAX;
    raw=(struct ble_gap_event){.type=BLE_GAP_EVENT_CONNECT,.connect={.status=0x216}};
    bleio_host_policy_observe_gap_event(&raw,HP_GAP_SOURCE_CENTRAL);
    assert(diagnostics.connect_events==UINT32_MAX && diagnostics.event_sequence==UINT32_MAX &&
        diagnostics.connect_failures==2 && diagnostics.last_connect_status==0x216);
    string_index=0;publish();bleio_host_policy_status();
    assert(test_dict_values[MP_QSTR_diag_version]==MP_OBJ_NEW_SMALL_INT(1));
    assert(test_dict_values[MP_QSTR_diag_connect_events]==mp_obj_new_int_from_uint(UINT32_MAX));
    assert(test_dict_values[MP_QSTR_diag_last_connect_status]==mp_obj_new_int(0x216));
}
static void test_saved_refusal_identity_is_public_atomic_and_operation_scoped(void) {
    reset();memset(&diagnostics,0,sizeof(diagnostics));memset(&saved_refusal,0,sizeof(saved_refusal));
    string_index=0;bleio_host_policy_status();
    assert(test_dict_values[MP_QSTR_saved_refusal_version]==MP_OBJ_NEW_SMALL_INT(1));
    assert(test_dict_values[MP_QSTR_last_saved_refusal_id]==mp_const_none &&
        test_dict_values[MP_QSTR_last_saved_refusal_source]==mp_const_none &&
        test_dict_values[MP_QSTR_saved_refusal_window_count]==mp_obj_new_int_from_uint(0));
    hp_request(&core,HP_ENROLL,0,801,60,0);
    test_connection=(struct ble_gap_conn_desc){.conn_handle=50,.peer_id_addr=test_address(6),.peer_ota_addr=test_address(6)};
    unsigned before_writes=writes,before_deletes=deletes,before_commits=nvs_commits,before_policy_commits=policy_commits;
    assert(!bleio_host_policy_connect(50));
    assert(saved_refusal.id==core.peers[0].id && saved_refusal.source==HP_SAVED_FROM_DESCRIPTOR &&
        saved_refusal.operation_id==801 && saved_refusal.window_count==1 && terminations==1);
    assert(!bleio_host_policy_connect(50) && saved_refusal.window_count==2 && terminations==2);
    hp_saved_refusal_t previous=saved_refusal;
    test_connection.conn_handle=49;
    assert(!bleio_host_policy_connect(50));
    assert(!memcmp(&previous,&saved_refusal,sizeof(previous)));
    // A new window without an actual saved refusal retains the prior record.
    hp_request(&core,HP_ENROLL,0,802,60,0);
    assert(!memcmp(&previous,&saved_refusal,sizeof(previous)));
    test_connection=(struct ble_gap_conn_desc){.conn_handle=50,.peer_id_addr=test_address(6),.peer_ota_addr=test_address(6)};
    assert(!bleio_host_policy_connect(50));
    assert(saved_refusal.id==core.peers[0].id && saved_refusal.source==HP_SAVED_FROM_DESCRIPTOR &&
        saved_refusal.operation_id==802 && saved_refusal.window_count==1);
    saved_refusal.window_count=UINT32_MAX;
    assert(!bleio_host_policy_connect(50) && saved_refusal.window_count==UINT32_MAX);
    hp_saved_refusal_t before_getter=saved_refusal;
    string_index=0;bleio_host_policy_status();
    char expected_id[17];snprintf(expected_id,sizeof(expected_id),"%016" PRIx64,saved_refusal.id);
    assert(!strcmp(mp_obj_str_get_str(test_dict_values[MP_QSTR_last_saved_refusal_id]),expected_id));
    assert(!strcmp(mp_obj_str_get_str(test_dict_values[MP_QSTR_last_saved_refusal_source]),"descriptor"));
    assert(test_dict_values[MP_QSTR_last_saved_refusal_operation_id]==mp_obj_new_int_from_uint(802) &&
        test_dict_values[MP_QSTR_saved_refusal_window_count]==mp_obj_new_int_from_uint(UINT32_MAX));
    assert(!memcmp(&before_getter,&saved_refusal,sizeof(saved_refusal)) && !test_lock_depth);
    // Only the two explicit new-window policy requests may persist here.
    assert(writes==before_writes && deletes==before_deletes && nvs_commits==before_commits && policy_commits==before_policy_commits+1 &&
        core.status.connection_generation==0 && !diagnostics.admissions);
}
int main(void) {
    baseline_main();
    test_admission_classification_is_observational();
    test_pre_admission_bridge_counters();
    test_raw_callback_and_stop_observations();
    test_saved_refusal_identity_is_public_atomic_and_operation_scoped();
    puts("PASS pre-admission diagnostics: 384 unchanged admission outcomes, raw failures/refusals/stops/saturation");
    return 0;
}

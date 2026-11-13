// SPDX-License-Identifier: MIT
#pragma once
#include "py/obj.h"
#include "shared-bindings/_bleio/Adapter.h"
#include "host/ble_gap.h"
#include "host/ble_store.h"
#include "common-hal/_bleio/HostPolicyCore.h"
void bleio_host_policy_init(int nvs_error);
void bleio_host_policy_sync(void);
void bleio_host_policy_install_store_guards(void);
void bleio_host_policy_disabled(void);
void bleio_host_policy_deinit(void);
int bleio_host_policy_advertising_guard(void);
typedef uint32_t (*hp_raw_advertise_fn)(bleio_adapter_obj_t *, bool, bool, uint32_t, float,
    const uint8_t *, uint16_t, const uint8_t *, uint16_t, mp_int_t, const bleio_address_obj_t *);
uint32_t bleio_host_policy_start_advertising(bleio_adapter_obj_t *, bool, bool, uint32_t, float,
    const uint8_t *, uint16_t, const uint8_t *, uint16_t, mp_int_t, const bleio_address_obj_t *, hp_raw_advertise_fn);
uint32_t bleio_host_policy_advertising_timeout_ms(uint32_t);
bool bleio_host_policy_input_guard(uint16_t handle);
int bleio_host_policy_queue_input(uint16_t, uint16_t, const uint8_t *, size_t);
bool bleio_host_policy_input_value(uint16_t, uint16_t, uint8_t *, size_t);
uint32_t bleio_host_policy_connect(uint16_t handle);
void bleio_host_policy_connection_attach_failed(uint16_t handle, uint32_t generation, int error);
// Scalar-only observations, including events refused before CP publication.
enum { HP_GAP_SOURCE_CENTRAL=1, HP_GAP_SOURCE_ADVERTISING, HP_GAP_SOURCE_CONNECTION };
void bleio_host_policy_observe_gap_event(const struct ble_gap_event *, unsigned source);
void bleio_host_policy_observe_vm_adv_stop(bool active, int result);
void bleio_host_policy_observe_adapter_no_slot(void);
void bleio_host_policy_observe_adapter_publication(void);
void bleio_host_policy_event(struct ble_gap_event *, uint32_t generation);
void bleio_host_policy_subscription(uint16_t handle, uint32_t generation, uint16_t input_handle, bool enabled);
int bleio_host_policy_store_status(struct ble_store_status_event *, void *);
mp_obj_t bleio_host_policy_peers(void);
mp_obj_t bleio_host_policy_status(void);
mp_obj_t bleio_host_policy_request(mp_obj_t mode, mp_obj_t target, mp_int_t timeout_s);
mp_obj_t bleio_host_policy_alias(mp_obj_t target, mp_obj_t alias);
mp_obj_t bleio_host_policy_forget(mp_obj_t target, mp_obj_t generation);
mp_obj_t bleio_host_policy_clear_saved_hosts(mp_obj_t generation);
mp_obj_t bleio_host_policy_arm_input(mp_obj_t, mp_obj_t, mp_obj_t, mp_obj_t);

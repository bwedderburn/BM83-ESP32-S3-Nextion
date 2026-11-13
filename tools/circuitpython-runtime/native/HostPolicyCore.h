// SPDX-License-Identifier: MIT
// Production policy core; compiled unchanged by the ESP32 port and host harness.
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define HP_MAX_PEERS 8
#define HP_ALIAS_BYTES 24
#define HP_INPUT_BYTES 32
#define HP_INPUT_QUEUE_CAPACITY 8
#define HP_INVALID_HANDLE 0xffff
#define HP_TERMINATE_ABSENT (-1)
typedef struct { uint8_t type; uint8_t val[6]; } hp_address_t;
typedef enum { HP_PAUSED, HP_AUTO, HP_ENROLL } hp_mode_t;
typedef enum { HP_STATE_PAUSED, HP_SWITCHING, HP_WAITING, HP_ENROLLING, HP_CONNECTED, HP_ERROR } hp_state_t;
typedef enum { HP_DOMAIN_NONE, HP_DOMAIN_POLICY, HP_DOMAIN_NVS, HP_DOMAIN_NIMBLE, HP_DOMAIN_SECURITY } hp_domain_t;

// Observational reason for the same admission predicates used by hp_connect.
// No identity/address is exported and no rejection changes policy state.
typedef enum {
    HP_CONNECT_ACCEPT, HP_CONNECT_POLICY_CLOSED, HP_CONNECT_SLOT_BUSY,
    HP_CONNECT_AUTO_IDENTITY, HP_CONNECT_SAVED_IDENTITY, HP_CONNECT_CANDIDATE_IDENTITY
} hp_connect_reason_t;
enum { HP_INVALID=1, HP_NO_TARGET, HP_CAPACITY, HP_STALE, HP_REPEAT_PAIR, HP_TIMEOUT, HP_STORAGE, HP_UNAUTHORIZED, HP_QUEUE_FULL,
    HP_DUPLICATE_IRK, HP_IRK_RPA_MISMATCH, HP_KEY_SEQUENCE };
typedef struct {
    hp_address_t address;
    uint64_t id;
    bool our_sec, peer_sec, cccd, durable;
    char alias[HP_ALIAS_BYTES+1];
} hp_peer_t;
typedef struct { hp_address_t address; char alias[HP_ALIAS_BYTES+1]; } hp_alias_t;
typedef struct {
    uint32_t magic, version, size, serial;
    uint8_t mode;
    hp_address_t selected;
    hp_alias_t aliases[HP_MAX_PEERS];
    uint32_t checksum;
} hp_blob_t;
typedef struct {
    hp_mode_t requested_mode, applied_mode;
    hp_state_t state;
    uint64_t target_id, connected_id;
    uint32_t operation_id, policy_generation, connection_generation, bond_generation, subscription_generation;
    bool filter_ready, connected, encrypted, bonded, hid_ready, persisted;
    hp_domain_t error_domain;
    int error_code, last_disconnect_reason;
    uint32_t last_disconnect_generation;
    bool last_disconnect_local;
    uint32_t enroll_remaining_s;
} hp_status_t;
typedef struct {
    void *context;
    int (*persist)(void *, const hp_blob_t *);
    int (*stop_advertising)(void *);
    int (*terminate)(void *, uint16_t);
    int (*filter)(void *, const hp_address_t *); // NULL clears admission lists, never starts advertising.
    int (*peers)(void *, hp_peer_t *, size_t *, unsigned *);
    int (*reserve_enrollment)(void *); // Other persistent store classes; no eviction.
    int (*forget)(void *, const hp_address_t *, bool apply);
    int (*clear_peers)(void *, bool apply); // Explicit owner maintenance; excludes local IRK.
} hp_backend_t;
typedef struct {
    hp_backend_t backend;
    hp_blob_t blob;
    hp_status_t status;
    hp_address_t connected_address, candidate;
    bool candidate_valid, candidate_store_started, terminate_sent, terminate_failed, enrollment_rejected;
    uint16_t handle, hid_input_handle;
    bool input_subscribed;
    uint64_t deadline_ms;
    hp_peer_t peers[HP_MAX_PEERS];
    size_t peer_count;
    unsigned cccd_count;
    uint64_t enrollment_existing[HP_MAX_PEERS];
    size_t enrollment_existing_count;
} hp_core_t;
typedef struct {
    bool alias, forget, clear_peers;
    uint32_t generation;
    hp_mode_t mode;
    uint64_t target;
    uint32_t operation, timeout_s;
    char text[HP_ALIAS_BYTES+1];
    size_t length;
} hp_command_t;
typedef struct { bool pending; uint32_t next_operation; hp_command_t command; } hp_queue_t;
int hp_submit(hp_queue_t *, hp_command_t *); // Caller holds only its short snapshot lock.
bool hp_pop(hp_queue_t *, hp_command_t *);
typedef struct {
    uint16_t handle, attribute;
    uint32_t operation, policy_generation, connection_generation, subscription_generation;
    uint64_t identity;
    uint8_t length, data[HP_INPUT_BYTES];
} hp_input_report_t;
typedef struct { hp_input_report_t reports[HP_INPUT_QUEUE_CAPACITY]; unsigned head,count; } hp_input_queue_t;
int hp_queue_input(hp_input_queue_t *, const hp_status_t *, uint16_t active_handle,
    uint16_t actual_input, uint16_t handle, uint16_t attribute, const uint8_t *, size_t);
bool hp_pop_input(hp_input_queue_t *, hp_input_report_t *);
void hp_clear_input(hp_input_queue_t *);
bool hp_input_current(const hp_core_t *, const hp_input_report_t *);
bool hp_normalize(hp_address_t *out, const hp_address_t *in);
bool hp_address_equal(const hp_address_t *, const hp_address_t *);
uint64_t hp_identity_id(const hp_address_t *);
uint32_t hp_blob_checksum(const hp_blob_t *);
bool hp_blob_valid(const hp_blob_t *);
bool hp_alias_valid(const char *, size_t);
void hp_init(hp_core_t *, const hp_backend_t *, const hp_blob_t *, int load_error);
int hp_refresh(hp_core_t *);
bool hp_forget_allowed(const hp_status_t *, uint16_t handle);
void hp_forget(hp_core_t *, uint64_t id, uint32_t generation);
void hp_clear_saved_hosts(hp_core_t *, uint32_t generation);
void hp_request(hp_core_t *, hp_mode_t, uint64_t target, uint32_t operation, uint32_t timeout_s, uint64_t now_ms);
void hp_tick(hp_core_t *, uint64_t now_ms);
void hp_fail(hp_core_t *, hp_domain_t, int);
uint32_t hp_connect(hp_core_t *, uint16_t handle, const hp_address_t *);
hp_connect_reason_t hp_connect_reason(const hp_core_t *, const hp_address_t *);
void hp_identity(hp_core_t *, uint16_t, uint32_t, const hp_address_t *);
bool hp_reject_enrollment_link(hp_core_t *, uint16_t, uint32_t);
bool hp_latch_enrollment_rejection(hp_core_t *, uint16_t, uint32_t); // No backend/GAP/store calls.
void hp_security(hp_core_t *, uint16_t, uint32_t, bool encrypted, bool bonded, int error);
void hp_subscribe(hp_core_t *, uint16_t, uint32_t, uint16_t input_handle, bool enabled);
void hp_disconnect(hp_core_t *, uint16_t, uint32_t, int full_reason);
bool hp_advertising_allowed(const hp_core_t *);
bool hp_input_allowed(const hp_core_t *, uint16_t handle);
// No backend calls/deletion: safe inside the stack's store lock.
bool hp_store_allowed(hp_core_t *, const hp_address_t *, bool security, bool exists, bool same_keys);
int hp_set_alias(hp_core_t *, uint64_t, const char *, size_t);

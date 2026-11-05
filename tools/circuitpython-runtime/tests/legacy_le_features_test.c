#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#define MYNEWT_VAL(name) name
#define NIMBLE_BLE_CONNECT 1
#define BLE_PERIODIC_ADV_WITH_RESPONSES 0
#define BLE_HCI_SUGG_DEF_DATALEN_TX_OCTETS_MAX 251
#define BLE_HCI_SUGG_DEF_DATALEN_TX_TIME_MAX 2120
#define BLE_HS_CONN_F_MASTER 0x01
#define BLE_HS_HCI_LE_FEAT_CONN_PARAM_REQUEST 0x02
#define BLE_ERR_UNSUPP_REM_FEATURE 0x1a
#define BLE_ERR_CONN_ESTABLISHMENT 0x3e
#define BLE_ERR_AUTH_FAIL 0x05
#define BLE_GAP_EVENT_CONNECT 0
#define BLE_GAP_EVENT_LINK_ESTAB 38

struct ble_hci_ev_le_subev_rd_rem_used_feat {
    uint8_t status;
    uint16_t conn_handle;
    uint8_t features[8];
};

struct ble_hs_conn {
    unsigned bhc_flags;
    uint32_t supported_feat;
    bool slave_conn;
};

struct ble_gap_event {
    unsigned type;
    union {
        struct { int status; uint16_t conn_handle; } connect;
        struct { int status; uint16_t conn_handle; } link_estab;
    };
};

static struct ble_hs_conn connection;
static bool live;
static unsigned listener_events;
static unsigned connection_events;
static unsigned data_length_requests;
static unsigned version_requests;
static int posted_status;

static uint16_t le16toh(uint16_t value) { return value; }
static uint32_t get_le32(const uint8_t *value) {
    return (uint32_t)value[0] | ((uint32_t)value[1] << 8)
        | ((uint32_t)value[2] << 16) | ((uint32_t)value[3] << 24);
}

static void ble_hs_lock(void) {}
static void ble_hs_unlock(void) {}
static struct ble_hs_conn *ble_hs_conn_find(uint16_t handle) {
    assert(handle == 7);
    return live ? &connection : NULL;
}

static void check_event(const struct ble_gap_event *event, unsigned count) {
    if (count == 0) {
        assert(event->type == BLE_GAP_EVENT_CONNECT);
        assert(event->connect.conn_handle == 7);
        posted_status = event->connect.status;
    } else {
        assert(count == 1);
        assert(event->type == BLE_GAP_EVENT_LINK_ESTAB);
        assert(event->link_estab.conn_handle == 7);
        assert(event->link_estab.status == posted_status);
    }
}

static void ble_gap_event_listener_call(const struct ble_gap_event *event) {
    check_event(event, listener_events++);
}

static void ble_gap_call_conn_event_cb(const struct ble_gap_event *event, uint16_t handle) {
    assert(handle == 7);
    check_event(event, connection_events++);
}

static void ble_hs_hci_util_set_data_len(uint16_t handle, unsigned octets, unsigned time) {
    assert(handle == 7);
    assert(octets == BLE_HCI_SUGG_DEF_DATALEN_TX_OCTETS_MAX);
    assert(time == BLE_HCI_SUGG_DEF_DATALEN_TX_TIME_MAX);
    data_length_requests++;
}

static void ble_gap_rd_rem_ver_tx(uint16_t handle) {
    assert(handle == 7);
    version_requests++;
}

/* Built from the pinned upstream function bodies, before or after git apply. */
#include "legacy_le_features_under_test.h"

static void complete_features(bool has_connection, bool central, uint8_t status) {
    connection = (struct ble_hs_conn) { .bhc_flags = central ? BLE_HS_CONN_F_MASTER : 0 };
    live = has_connection;
    listener_events = 0;
    connection_events = 0;
    data_length_requests = 0;
    version_requests = 0;
    posted_status = -1;
    const struct ble_hci_ev_le_subev_rd_rem_used_feat event = {
        .status = status, .conn_handle = 7, .features = { 0xff, 0xff, 0xff, 0xff },
    };
    ble_gap_rx_rd_rem_sup_feat_complete(&event);
}

static void expect_events(unsigned count, int status, unsigned data_length, unsigned version) {
    assert(listener_events == count);
    assert(connection_events == count);
    assert(posted_status == status);
    assert(data_length_requests == data_length);
    assert(version_requests == version);
}

int main(void) {
    complete_features(true, false, BLE_ERR_UNSUPP_REM_FEATURE);
    expect_events(2, EXPECT_COMPAT_FIX ? 0 : BLE_ERR_UNSUPP_REM_FEATURE, 0, 0);
    assert(connection.slave_conn && connection.supported_feat == 0);

    complete_features(true, false, 0);
    expect_events(2, 0, 1, 0);
    assert(connection.slave_conn && connection.supported_feat != 0);

    complete_features(true, false, BLE_ERR_AUTH_FAIL);
    expect_events(2, BLE_ERR_AUTH_FAIL, 0, 0);
    assert(connection.slave_conn && connection.supported_feat == 0);

    complete_features(true, false, BLE_ERR_CONN_ESTABLISHMENT);
    expect_events(0, -1, 0, 0);
    assert(!connection.slave_conn);

    complete_features(true, true, BLE_ERR_UNSUPP_REM_FEATURE);
    expect_events(0, -1, 0, 1);
    assert(!connection.slave_conn && connection.supported_feat == 0);

    complete_features(true, true, 0);
    expect_events(0, -1, 0, 1);
    assert(!connection.slave_conn && connection.supported_feat != 0);

    complete_features(false, false, BLE_ERR_UNSUPP_REM_FEATURE);
    expect_events(2, BLE_ERR_UNSUPP_REM_FEATURE, 0, 0);
    assert(!connection.slave_conn);

    complete_features(false, false, 0);
    expect_events(0, -1, 0, 0);
    return 0;
}

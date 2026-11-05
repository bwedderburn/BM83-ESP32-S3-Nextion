/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *  http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

#endif
}

void
ble_gap_event_connect_call(uint16_t conn_handle, int status)
{
    struct ble_gap_event event;
    uint16_t handle = le16toh(conn_handle);

    memset(&event, 0, sizeof event);
    event.type = BLE_GAP_EVENT_CONNECT;
    event.connect.status = status;
    event.connect.conn_handle = handle;

#if MYNEWT_VAL(BLE_PERIODIC_ADV_WITH_RESPONSES)
    event.connect.sync_handle = pawr_sync_handle;
    event.connect.adv_handle  = pawr_adv_handle;
#endif

    ble_gap_event_listener_call(&event);
#if NIMBLE_BLE_CONNECT
    ble_gap_call_conn_event_cb(&event, handle);
#endif

//TODO : Remove duplication of event
    event.type = BLE_GAP_EVENT_LINK_ESTAB;
    event.link_estab.status = status;
    event.link_estab.conn_handle = handle;

#if MYNEWT_VAL(BLE_PERIODIC_ADV_WITH_RESPONSES)
    event.link_estab.sync_handle = pawr_sync_handle;
    event.link_estab.adv_handle  = pawr_adv_handle;
#endif

    ble_gap_event_listener_call(&event);
#if NIMBLE_BLE_CONNECT
    ble_gap_call_conn_event_cb(&event, handle);
#endif

    if (status == 0 ) {
        ble_hs_hci_util_set_data_len(le16toh(conn_handle), BLE_HCI_SUGG_DEF_DATALEN_TX_OCTETS_MAX,
                BLE_HCI_SUGG_DEF_DATALEN_TX_TIME_MAX);
    }
}

void
ble_gap_rx_rd_rem_sup_feat_complete(const struct ble_hci_ev_le_subev_rd_rem_used_feat *ev)
{
#if NIMBLE_BLE_CONNECT
    struct ble_hs_conn *conn;

    ble_hs_lock();

    conn = ble_hs_conn_find(le16toh(ev->conn_handle));

    ble_hs_unlock();

    if (ev->status == BLE_ERR_CONN_ESTABLISHMENT) {
        /* Failed for 0x3E. Reconnection will automatically happen */
        return;
    }

    if ((conn != NULL) &&  (conn->bhc_flags & BLE_HS_CONN_F_MASTER)) {
        if (ev->status == 0) {
#if MYNEWT_VAL(BT_NIMBLE_MEM_OPTIMIZATION)
            conn->supported_feat = !!(get_le32(ev->features) & BLE_HS_HCI_LE_FEAT_CONN_PARAM_REQUEST);
#else
            conn->supported_feat = get_le32(ev->features);
#endif
        }
        ble_gap_rd_rem_ver_tx(ev->conn_handle);

    } else {
        if (conn != NULL) {
            if (ev->status == 0) {
#if MYNEWT_VAL(BT_NIMBLE_MEM_OPTIMIZATION)
                conn->supported_feat = !!(get_le32(ev->features) & BLE_HS_HCI_LE_FEAT_CONN_PARAM_REQUEST);
#else
                conn->supported_feat = get_le32(ev->features);
#endif
            }
            ble_gap_event_connect_call(ev->conn_handle, ev->status);
            conn->slave_conn = 1;
        } else if (ev->status != 0) {
            ble_gap_event_connect_call(ev->conn_handle, ev->status);
        }
    }
#endif
}

void
ble_gap_rx_rd_rem_ver_info_complete(const struct ble_hci_ev_rd_rem_ver_info_cmp *ev)

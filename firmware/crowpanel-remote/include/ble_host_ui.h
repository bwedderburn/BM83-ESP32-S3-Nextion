#pragma once
#include <lvgl.h>
#include "espnow_link.h"

// LVGL and policy model stay in the main task; receive callbacks only queue.
void ble_host_ui_init(espnow_log_fn log);
void ble_host_ui_show(lv_obj_t *screen);
bool ble_host_ui_accept(const uint8_t *frame, size_t length, uint32_t now);
void ble_host_ui_tick(uint32_t now);
void ble_host_ui_invalidate_link();
bool ble_host_ui_holding();
bool ble_host_ui_supported(uint32_t now);
void ble_host_ui_summary(uint32_t now, char *out, size_t capacity);

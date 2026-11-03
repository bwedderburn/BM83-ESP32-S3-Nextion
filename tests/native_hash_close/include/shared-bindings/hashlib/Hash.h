#pragma once
#include "py/obj.h"
#include "shared-module/hashlib/Hash.h"
void common_hal_hashlib_hash_update(hashlib_hash_obj_t *self, const uint8_t *data, size_t size);
void common_hal_hashlib_hash_digest(hashlib_hash_obj_t *self, uint8_t *data, size_t size);
size_t common_hal_hashlib_hash_get_digest_size(hashlib_hash_obj_t *self);
void common_hal_hashlib_hash_deinit(hashlib_hash_obj_t *self);
bool common_hal_hashlib_hash_deinited(hashlib_hash_obj_t *self);

#pragma once
#include <string.h>
#include "shared-bindings/hashlib/Hash.h"
bool common_hal_hashlib_new(hashlib_hash_obj_t *self, const char *algorithm);

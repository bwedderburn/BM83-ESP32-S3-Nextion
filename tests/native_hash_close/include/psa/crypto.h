#pragma once
#include <stddef.h>
#include <stdint.h>
typedef int psa_status_t;
typedef unsigned int psa_algorithm_t;
typedef struct { void *context; psa_algorithm_t algorithm; } psa_hash_operation_t;
#define PSA_SUCCESS 0
#define PSA_ERROR_GENERIC_ERROR (-1)
#define PSA_ALG_SHA_1 1
#define PSA_ALG_SHA_256 256
#define PSA_HASH_LENGTH(algorithm) ((algorithm) == PSA_ALG_SHA_1 ? 20 : 32)
#define PSA_HASH_OPERATION_INIT { NULL, 0 }
static inline psa_hash_operation_t psa_hash_operation_init(void) {
    return (psa_hash_operation_t)PSA_HASH_OPERATION_INIT;
}
psa_status_t psa_crypto_init(void);
psa_status_t psa_hash_setup(psa_hash_operation_t *operation, psa_algorithm_t algorithm);
psa_status_t psa_hash_update(psa_hash_operation_t *operation, const uint8_t *data, size_t size);
psa_status_t psa_hash_clone(const psa_hash_operation_t *source, psa_hash_operation_t *clone);
psa_status_t psa_hash_finish(psa_hash_operation_t *operation, uint8_t *data, size_t size, size_t *used);
psa_status_t psa_hash_abort(psa_hash_operation_t *operation);

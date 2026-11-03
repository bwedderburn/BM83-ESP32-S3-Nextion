/* Host PSA ownership model linked to the actual patched CircuitPython HAL.
 * Host SHA checks digest data; injection models partial allocation/errors.
 * This does not emulate ESP32 DMA, native heap, GC scheduling or radio timing.
 */
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef __APPLE__
#include <CommonCrypto/CommonDigest.h>
#else
#include <openssl/sha.h>
#endif
#include "shared-bindings/hashlib/__init__.h"

typedef struct { uint8_t data[1024]; size_t size; } context_t;
static jmp_buf raised;
static int error_kind, live, peak, aborts;
static int fail_init, fail_setup, fail_update, fail_clone, fail_finish, wrong_length;
static hashlib_hash_obj_t self;
_Noreturn void mp_raise_RuntimeError(const char *message) {
    assert(message && message[0]); error_kind = 2; longjmp(raised, 1);
}
_Noreturn void mp_raise_ValueError(const char *message) {
    assert(message && message[0]); error_kind = 1; longjmp(raised, 1);
}
#define EXPECT_ERROR(kind, expression) do { \
    error_kind = 0; \
    if (setjmp(raised) == 0) { expression; assert(!"expected exception"); } \
    assert(error_kind == (kind)); \
} while (0)
psa_status_t psa_crypto_init(void) { return fail_init ? -1 : PSA_SUCCESS; }
psa_status_t psa_hash_setup(psa_hash_operation_t *op, psa_algorithm_t alg) {
    assert(!op->context); op->context = calloc(1, sizeof(context_t)); assert(op->context);
    op->algorithm = alg; live++; if (live > peak) peak = live;
    return fail_setup ? -1 : PSA_SUCCESS;
}
psa_status_t psa_hash_update(psa_hash_operation_t *op, const uint8_t *data, size_t size) {
    assert(op->context); if (fail_update) return -1;
    context_t *ctx = op->context; assert(ctx->size + size <= sizeof(ctx->data));
    memcpy(ctx->data + ctx->size, data, size); ctx->size += size; return PSA_SUCCESS;
}
psa_status_t psa_hash_clone(const psa_hash_operation_t *source, psa_hash_operation_t *clone) {
    assert(source->context && !clone->context);
    clone->context = malloc(sizeof(context_t)); assert(clone->context);
    memcpy(clone->context, source->context, sizeof(context_t)); clone->algorithm = source->algorithm;
    live++; if (live > peak) peak = live;
    return fail_clone ? -1 : PSA_SUCCESS;
}
psa_status_t psa_hash_abort(psa_hash_operation_t *op) {
    aborts++; if (op->context) { free(op->context); op->context = NULL; live--; }
    return PSA_SUCCESS;
}
psa_status_t psa_hash_finish(psa_hash_operation_t *op, uint8_t *data, size_t size, size_t *used) {
    assert(op->context); if (fail_finish) return -1;
    context_t *ctx = op->context; *used = PSA_HASH_LENGTH(op->algorithm); assert(size >= *used);
#ifdef __APPLE__
    if (op->algorithm == PSA_ALG_SHA_1) CC_SHA1(ctx->data, (CC_LONG)ctx->size, data);
    else CC_SHA256(ctx->data, (CC_LONG)ctx->size, data);
#else
    if (op->algorithm == PSA_ALG_SHA_1) SHA1(ctx->data, ctx->size, data);
    else SHA256(ctx->data, ctx->size, data);
#endif
    if (wrong_length) *used = 0;
    return psa_hash_abort(op);
}
static void digest_equals(const char *expected) {
    uint8_t data[32]; char hex[65];
    common_hal_hashlib_hash_digest(&self, data, sizeof(data));
    size_t size = common_hal_hashlib_hash_get_digest_size(&self);
    for (size_t i = 0; i < size; i++) sprintf(hex + 2 * i, "%02x", data[i]);
    assert(strcmp(hex, expected) == 0 && live == 1);
}
static void reset_faults(void) { fail_init = fail_setup = fail_update = fail_clone = fail_finish = wrong_length = 0; }
static void close_twice(void) {
    common_hal_hashlib_hash_deinit(&self); assert(live == 0);
    int previous = aborts; common_hal_hashlib_hash_deinit(&self); assert(aborts == previous);
    assert(common_hal_hashlib_hash_deinited(&self));
}
int main(void) {
    uint8_t output[32];
    assert(common_hal_hashlib_new(&self, "sha1"));
    digest_equals("da39a3ee5e6b4b0d3255bfef95601890afd80709");
    common_hal_hashlib_hash_update(&self, (const uint8_t *)"abc", 3);
    digest_equals("a9993e364706816aba3e25717850c26c9cd0d89d"); close_twice();
    assert(common_hal_hashlib_new(&self, "sha256"));
    digest_equals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    common_hal_hashlib_hash_update(&self, (const uint8_t *)"abc", 3);
    digest_equals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    digest_equals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    common_hal_hashlib_hash_update(&self, (const uint8_t *)"def", 3);
    digest_equals("bef57ec7f53a6d40beb640a780a639c83bc29ac8a9816f1fc6c5c6dcd93c4721");
    EXPECT_ERROR(1, common_hal_hashlib_hash_digest(&self, output, 1)); assert(live == 1); close_twice();
    EXPECT_ERROR(1, common_hal_hashlib_hash_update(&self, (const uint8_t *)"x", 1));
    EXPECT_ERROR(1, common_hal_hashlib_hash_digest(&self, output, sizeof(output))); assert(live == 0);
    assert(!common_hal_hashlib_new(&self, "unsupported")); close_twice();
    fail_init = 1; EXPECT_ERROR(2, common_hal_hashlib_new(&self, "sha256")); close_twice(); reset_faults();
    fail_setup = 1; EXPECT_ERROR(2, common_hal_hashlib_new(&self, "sha256")); close_twice(); reset_faults();
    assert(common_hal_hashlib_new(&self, "sha256")); fail_update = 1;
    EXPECT_ERROR(2, common_hal_hashlib_hash_update(&self, (const uint8_t *)"abc", 3)); close_twice(); reset_faults();
    for (int fault = 0; fault < 3; fault++) {
        assert(common_hal_hashlib_new(&self, "sha256"));
        common_hal_hashlib_hash_update(&self, (const uint8_t *)"abc", 3);
        fail_clone = fault == 0; fail_finish = fault == 1; wrong_length = fault == 2;
        EXPECT_ERROR(2, common_hal_hashlib_hash_digest(&self, output, sizeof(output))); assert(live == 1);
        reset_faults(); digest_equals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"); close_twice();
    }
    for (int i = 0; i < 1000; i++) {
        assert(common_hal_hashlib_new(&self, "sha256")); common_hal_hashlib_hash_update(&self, (const uint8_t *)"abc", 3);
        digest_equals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"); close_twice();
    }
    assert(live == 0 && peak == 2);
    puts("PASS native Hash lifecycle: vectors, repeat/update, close, injected failures, 1000 cycles");
    return 0;
}

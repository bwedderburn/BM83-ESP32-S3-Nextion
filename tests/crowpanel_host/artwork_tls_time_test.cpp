#include "tls_time.h"
#include <assert.h>
#include <stdio.h>

using artwork_tls_time::Date;
using artwork_tls_time::certificate_valid_now;
using artwork_tls_time::valid;

int main() {
    const Date from = {2026, 10, 1, 0, 0, 0};
    const Date until = {2026, 10, 24, 23, 59, 59};
    assert(certificate_valid_now(from, until, {2026, 10, 24, 13, 0, 0}));
    assert(certificate_valid_now(from, until, from));
    assert(certificate_valid_now(from, until, until));
    assert(!certificate_valid_now(from, until, {2026, 9, 30, 23, 59, 59}));
    assert(!certificate_valid_now(from, until, {2026, 10, 25, 0, 0, 0}));
    assert(!certificate_valid_now(until, from, from));
    assert(!certificate_valid_now(from, until, {1970, 1, 1, 0, 0, 0}));
    assert(valid({2024, 2, 29, 23, 59, 59}));
    assert(valid({2000, 2, 29, 0, 0, 0}));
    assert(!valid({2100, 2, 29, 0, 0, 0}));
    assert(!valid({2026, 2, 29, 0, 0, 0}));
    assert(!valid({2026, 4, 31, 0, 0, 0}));
    assert(!valid({2026, 0, 1, 0, 0, 0}));
    assert(!valid({2026, 13, 1, 0, 0, 0}));
    assert(!valid({2026, 10, 24, 24, 0, 0}));
    assert(!valid({2026, 10, 24, 0, 60, 0}));
    assert(!valid({2026, 10, 24, 0, 0, 60}));
    assert(!valid({2026, 10, 0, 0, 0, 0}));
    assert(certificate_valid_now({1950, 1, 1, 0, 0, 0}, {2050, 1, 1, 0, 0, 0}, from));
    puts("19 UTC certificate date scenarios passed");
}

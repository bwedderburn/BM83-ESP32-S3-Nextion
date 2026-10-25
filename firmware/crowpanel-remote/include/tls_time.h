// Pure UTC certificate date checks for SDKs built without MBEDTLS_HAVE_TIME_DATE.
#pragma once

namespace artwork_tls_time {

struct Date { int year, month, day, hour, minute, second; };

inline bool valid(const Date &date) {
    if (date.year < 1900 || date.year > 9999 || date.month < 1 || date.month > 12 ||
        date.hour < 0 || date.hour > 23 || date.minute < 0 || date.minute > 59 ||
        date.second < 0 || date.second > 59) return false;
    static const int MONTH_DAYS[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    int days = MONTH_DAYS[date.month - 1];
    const bool leap = date.year % 4 == 0 && (date.year % 100 != 0 || date.year % 400 == 0);
    if (date.month == 2 && leap) ++days;
    return date.day >= 1 && date.day <= days;
}

inline int compare(const Date &a, const Date &b) {
    const int left[] = {a.year, a.month, a.day, a.hour, a.minute, a.second};
    const int right[] = {b.year, b.month, b.day, b.hour, b.minute, b.second};
    for (unsigned i = 0; i < 6; ++i) {
        if (left[i] != right[i]) return left[i] < right[i] ? -1 : 1;
    }
    return 0;
}

inline bool certificate_valid_now(const Date &not_before, const Date &not_after, const Date &utc_now) {
    return valid(not_before) && valid(not_after) && valid(utc_now) &&
           compare(not_before, not_after) <= 0 && compare(not_before, utc_now) <= 0 &&
           compare(utc_now, not_after) <= 0;
}

}  // namespace artwork_tls_time

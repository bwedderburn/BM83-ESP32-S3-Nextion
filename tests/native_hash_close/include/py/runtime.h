#pragma once
#define MP_ERROR_TEXT(message) message
_Noreturn void mp_raise_RuntimeError(const char *message);
_Noreturn void mp_raise_ValueError(const char *message);

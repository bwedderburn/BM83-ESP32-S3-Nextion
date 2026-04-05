try:
    from micropython import const
except ImportError:  # pragma: no cover - host Python fallback
    def const(value):
        return value


__all__ = ("const",)

try:
    from micropython import const
except ImportError:  # pragma: no cover - host Python fallback
    def const(value):
        """Return ``value`` unchanged when MicroPython's const is unavailable."""
        return value


__all__ = ("const",)

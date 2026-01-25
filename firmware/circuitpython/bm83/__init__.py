"""BM83 Bluetooth module interface."""
from .bm83 import Bm83

# Export EQ constants for test compatibility
EQ_OFF = 0
EQ_USER = 11  # Aligned with Bm83.EQ_SEQ and EQ_L mapping
EQ_LABELS = Bm83.EQ_LABELS
EQ_SEQ = Bm83.EQ_SEQ

__all__ = ['Bm83', 'EQ_OFF', 'EQ_USER', 'EQ_LABELS', 'EQ_SEQ']

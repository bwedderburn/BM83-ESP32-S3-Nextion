from nextion.display import Nextion
from unittest import mock


class DummyUART:
    def __init__(self):
        self.written = []
        self.to_read = bytearray()
        self.in_waiting = 0

    def write(self, data):
        self.written.append(data)

    def read(self, n):
        data = self.to_read[:n]
        self.to_read = self.to_read[n:]
        self.in_waiting = len(self.to_read)
        return data

def test_nextion_enqueue_and_tick():
    uart = DummyUART()
    nx = Nextion(uart)
    nx.enqueue("tEQ0.txt=\"TEST\"")
    nx.tick()
    assert any(b"tEQ0.txt=" in cmd for cmd in uart.written)

def test_nextion_read_token():
    uart = DummyUART()
    token = b"BT_EQ\xFF\xFF\xFF"
    uart.to_read += token
    uart.in_waiting = len(uart.to_read)
    nx = Nextion(uart)
    tokens, _ = nx.read()
    assert tokens == [b"BT_EQ"]

def test_nextion_queue_overflow():
    """Test that queue refuses to grow beyond max_queue_size"""
    uart = DummyUART()
    nx = Nextion(uart)
    max_size = nx._max_queue_size
    
    # Fill queue to max
    for i in range(max_size):
        nx.enqueue(f"cmd_{i}")
    assert len(nx._txq) == max_size
    
    # Additional enqueue should be dropped
    nx.enqueue("cmd_overflow")
    assert len(nx._txq) == max_size
    assert "cmd_overflow" not in nx._txq

def test_nextion_token_throttle():
    """Test that all tokens are throttled within throttle window"""
    uart = DummyUART()
    nx = Nextion(uart)
    
    with mock.patch('nextion.display.time.monotonic') as mock_time:
        # First token at time 0
        mock_time.return_value = 0.0
        uart.to_read = b"BT_EQ\xFF\xFF\xFF"
        uart.in_waiting = len(uart.to_read)
        tokens, _ = nx.read()
        assert len(tokens) == 1
        assert tokens[0] == b"BT_EQ"
        
        # Second token at 0.1s (within throttle window) - should be discarded
        mock_time.return_value = 0.1
        uart.to_read = b"BT_POWER\xFF\xFF\xFF"
        uart.in_waiting = len(uart.to_read)
        tokens, _ = nx.read()
        assert len(tokens) == 0  # Throttled (all tokens in window are dropped)
        # BT_POWER should be consumed/discarded, not in buffer
        assert b"BT_POWER" not in nx._rx
        
        # Third token after throttle window - should be accepted
        mock_time.return_value = 0.16
        uart.to_read = b"BT_NEXT\xFF\xFF\xFF"
        uart.in_waiting = len(uart.to_read)
        tokens, _ = nx.read()
        assert len(tokens) == 1
        assert tokens[0] == b"BT_NEXT"

def test_nextion_page_change_during_throttle():
    """Test that page-change frames are processed even during token throttle"""
    uart = DummyUART()
    nx = Nextion(uart)
    
    with mock.patch('nextion.display.time.monotonic') as mock_time:
        # First token at time 0
        mock_time.return_value = 0.0
        uart.to_read = b"BT_EQ\xFF\xFF\xFF"
        uart.in_waiting = len(uart.to_read)
        tokens, page_changed = nx.read()
        assert len(tokens) == 1
        
        # Page-change frame at 0.05s (within throttle window)
        mock_time.return_value = 0.05
        uart.to_read = b"\x66\x01\xFF\xFF\xFF"  # Page change to page 1
        uart.in_waiting = len(uart.to_read)
        tokens, page_changed = nx.read()
        assert len(tokens) == 0  # No tokens during throttle
        assert page_changed  # But page change still processed
        assert nx.current_page == 1

def test_nextion_multiple_buffered_tokens_throttled():
    """Test that multiple buffered tokens are individually throttled"""
    uart = DummyUART()
    nx = Nextion(uart)
    
    with mock.patch('nextion.display.time.monotonic') as mock_time:
        # First token at time 0
        mock_time.return_value = 0.0
        uart.to_read = b"BT_EQ\xFF\xFF\xFF"
        uart.in_waiting = len(uart.to_read)
        tokens, _ = nx.read()
        assert len(tokens) == 1
        assert tokens[0] == b"BT_EQ"
        
        # Multiple tokens already buffered at 0.05s (within throttle window)
        mock_time.return_value = 0.05
        uart.to_read = b"BT_POWER\xFF\xFF\xFFBT_NEXT\xFF\xFF\xFFBT_PLAY\xFF\xFF\xFF"
        uart.in_waiting = len(uart.to_read)
        tokens, _ = nx.read()
        # All should be throttled/discarded since they're processed within window
        assert len(tokens) == 0
        assert len(nx._rx) == 0  # All consumed


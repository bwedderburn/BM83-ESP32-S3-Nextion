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
        
        # Second token at 0.1s (within throttle window)
        mock_time.return_value = 0.1
        uart.to_read = b"BT_POWER\xFF\xFF\xFF"
        uart.in_waiting = len(uart.to_read)
        tokens, _ = nx.read()
        assert len(tokens) == 0  # Throttled (all tokens in window)
        # BT_POWER should still be in buffer
        assert b"BT_POWER" in nx._rx
        
        # After throttle window (0.15s + 0.01s margin)
        mock_time.return_value = 0.16
        tokens, _ = nx.read()
        assert len(tokens) == 1
        assert tokens[0] == b"BT_POWER"


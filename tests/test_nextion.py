from nextion.display import AUX_OBJ_PAGE0, AUX_OBJ_PAGE1, Nextion
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


def test_aux_objects_use_distinct_page_targets():
    assert AUX_OBJ_PAGE0 == "tAUX0"
    assert AUX_OBJ_PAGE1 == "tAUX1"


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
    assert len(nx.tx_queue) == max_size

    # Additional enqueue should be dropped
    nx.enqueue("cmd_overflow")
    assert len(nx.tx_queue) == max_size
    assert "cmd_overflow" not in nx.tx_queue


def test_nextion_tx_queue_consumes_in_order():
    """Tick should consume queue in FIFO order and update tx_queue view."""
    uart = DummyUART()
    nx = Nextion(uart)
    nx.enqueue("cmd_1")
    nx.enqueue("cmd_2")

    with mock.patch('nextion.display.time.monotonic') as mock_time:
        mock_time.return_value = 0.1
        nx.tick()
        assert any(b"cmd_1" in cmd for cmd in uart.written)
        assert nx.tx_queue == ["cmd_2"]

        mock_time.return_value = 0.2
        nx.tick()
        assert any(b"cmd_2" in cmd for cmd in uart.written)
        assert nx.tx_queue == []


def test_nextion_token_throttle_different_tokens_allowed():
    """Tokens within window are allowed when they differ; duplicates are dropped elsewhere."""
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

        # Second token at 0.1s (within throttle window) - different token should pass
        mock_time.return_value = 0.1
        uart.to_read = b"BT_POWER\xFF\xFF\xFF"
        uart.in_waiting = len(uart.to_read)
        tokens, _ = nx.read()
        assert tokens == [b"BT_POWER"]  # Allowed because different token

        # Third token (still within window but new) - should be accepted
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
    """Buffered burst keeps different tokens; duplicates in burst are dropped."""
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
        uart.to_read = b"BT_POWER\xFF\xFF\xFFBT_POWER\xFF\xFF\xFFBT_PLAY\xFF\xFF\xFF"
        uart.in_waiting = len(uart.to_read)
        tokens, _ = nx.read()
        # First POWER allowed, duplicate POWER dropped, PLAY allowed
        assert tokens == [b"BT_POWER", b"BT_PLAY"]


def test_nextion_token_throttle_allows_different_tokens():
    """Ensure throttle only suppresses duplicates within the window."""
    uart = DummyUART()
    nx = Nextion(uart)

    with mock.patch('nextion.display.time.monotonic') as mock_time:
        mock_time.return_value = 0.0
        uart.to_read = b"BT_VOLUP_P\xFF\xFF\xFF"
        uart.in_waiting = len(uart.to_read)
        tokens, _ = nx.read()
        assert tokens == [b"BT_VOLUP_P"]

        # Within throttle window but different token should be accepted
        mock_time.return_value = 0.05
        uart.to_read = b"BT_VOLUP_R\xFF\xFF\xFF"
        uart.in_waiting = len(uart.to_read)
        tokens, _ = nx.read()
        assert tokens == [b"BT_VOLUP_R"]


def test_nextion_token_throttle_blocks_duplicate():
    """Duplicate tokens within the throttle window should be dropped."""
    uart = DummyUART()
    nx = Nextion(uart)

    with mock.patch('nextion.display.time.monotonic') as mock_time:
        mock_time.return_value = 0.0
        uart.to_read = b"BT_POWER\xFF\xFF\xFF"
        uart.in_waiting = len(uart.to_read)
        tokens, _ = nx.read()
        assert tokens == [b"BT_POWER"]

        # Same token within throttle window should be suppressed
        mock_time.return_value = 0.05
        uart.to_read = b"BT_POWER\xFF\xFF\xFF"
        uart.in_waiting = len(uart.to_read)
        tokens, _ = nx.read()
        assert tokens == []


def test_nextion_token_with_trailing_garbage():
    """Test that tokens with trailing garbage bytes are properly cleaned"""
    uart = DummyUART()
    nx = Nextion(uart)

    # Simulate token with trailing garbage (e.g., from page change event)
    # This is what happens when print "BT_VOLUP_P" is followed by a page event
    uart.to_read = b"BT_VOLUP_Pf\x00\xFF\xFF\xFF"
    uart.in_waiting = len(uart.to_read)
    tokens, _ = nx.read()

    # Should extract clean token without the trailing 'f\x00'
    assert len(tokens) == 1
    assert tokens[0] == b"BT_VOLUP_P"


def test_nextion_token_with_leading_garbage():
    """Test that tokens with leading garbage bytes are properly cleaned"""
    uart = DummyUART()
    nx = Nextion(uart)

    # Simulate token with leading garbage
    uart.to_read = b"\x01\x02BT_PLAY\xFF\xFF\xFF"
    uart.in_waiting = len(uart.to_read)
    tokens, _ = nx.read()

    # Should extract clean token without the leading bytes
    assert len(tokens) == 1
    assert tokens[0] == b"BT_PLAY"


def test_nextion_rx_buffer_capped_on_termless_garbage():
    """A line feeding TERM-less garbage must not grow the RX buffer forever.

    Regression for the unbounded-buffer finding in the 2026-08 review: a
    disconnected display / floating RX pin / wrong baud can stream bytes
    that never contain the 0xFF 0xFF 0xFF terminator; without a cap the
    buffer grows ~960 B/s at 9600 baud until the heap starves.
    """
    uart = DummyUART()
    nx = Nextion(uart)
    for _ in range(200):
        uart.to_read += b"\x00" * 200
        uart.in_waiting = len(uart.to_read)
        nx.read()
    assert len(nx.rx_buffer) <= 512


def test_nextion_rx_cap_still_parses_tokens_after_trim():
    """After a garbage flood triggers the trim, real frames must still parse."""
    uart = DummyUART()
    nx = Nextion(uart)
    uart.to_read += b"\x00" * 2000  # flood with TERM-less noise
    uart.in_waiting = len(uart.to_read)
    nx.read()
    uart.to_read += b"BT_PLAY\xFF\xFF\xFF"
    uart.in_waiting = len(uart.to_read)
    tokens = []
    for _ in range(20):  # read() pulls <=256 bytes per call
        got, _ = nx.read()
        tokens.extend(got)
    assert b"BT_PLAY" in tokens

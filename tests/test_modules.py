"""Tests for the modular implementation."""
from __future__ import annotations

import utils
import bm83
import nextion


# =============================================================================
# Utils tests
# =============================================================================


def test_utils_hexdump():
    """Test hexdump function."""
    assert utils.hexdump(b"") == "<empty>"
    assert utils.hexdump(b"\xFF") == "FF"
    assert utils.hexdump(b"\x01\x02\x03") == "01 02 03"


def test_utils_sanitize_text():
    """Test text sanitization."""
    assert utils.sanitize_text("Hello\nWorld") == "Hello World"
    assert utils.sanitize_text('Test "quotes"') == "Test 'quotes'"
    long_text = "A" * 200
    result = utils.sanitize_text(long_text)
    assert len(result) <= 100
    assert result.endswith("...")


def test_utils_fmt_ms():
    """Test time formatting."""
    assert utils.fmt_ms(0) == "00:00"
    assert utils.fmt_ms(60000) == "01:00"
    assert utils.fmt_ms(125000) == "02:05"
    assert utils.fmt_ms(-1000) == "00:00"  # negative handled


# =============================================================================
# BM83 tests
# =============================================================================


def test_bm83_frame():
    """Test BM83 frame construction."""
    bm = bm83.Bm83()
    frame = bm.frame(0x0F)  # READ_BD_ADDR opcode, no payload
    assert frame[0] == 0xAA  # Start byte
    assert frame[1] == 0x00  # len_hi
    assert frame[2] == 0x01  # len_lo (1 byte for opcode)
    assert frame[3] == 0x0F  # opcode
    assert frame[4] == 0xF0  # checksum (corrected: makes total sum to 0)


def test_bm83_checksum():
    """Test checksum validation."""
    bm = bm83.Bm83()
    # Valid checksum: opcode 0x0F, checksum 0xF0 (corrected to match actual implementation)
    assert bm._checksum_valid(bytes([0x0F, 0xF0]))
    # Invalid checksum
    assert not bm._checksum_valid(bytes([0x0F, 0x00]))


def test_bm83_parse_metadata():
    """Test AVRCP metadata parsing."""
    # Construct test metadata: attr_id=1 (title), length=5, text="Hello"
    data = bytes([0x01, 0x00, 0x05]) + b"Hello"
    metadata = bm83.Bm83.parse_avrcp_metadata(data)
    assert metadata.get("title") == "Hello"


def test_bm83_eq_constants():
    """Test EQ constants."""
    assert bm83.EQ_OFF == 0
    assert bm83.EQ_USER == 11  # Aligned with Bm83.EQ_SEQ and EQ_L
    assert len(bm83.EQ_LABELS) == 11
    assert len(bm83.EQ_SEQ) == 11


# =============================================================================
# Nextion tests
# =============================================================================


def test_nextion_ascii_check():
    """Test ASCII validation."""
    assert nextion.ascii_upper_uscore(b"BT_PLAY")
    assert nextion.ascii_upper_uscore(b"TEST 123")
    assert not nextion.ascii_upper_uscore(b"bt_play")  # lowercase
    assert not nextion.ascii_upper_uscore(b"")  # empty


def test_nextion_token_map():
    """Test token mappings."""
    assert b"EQ_OFF" in nextion.EQ_MAP
    assert nextion.EQ_MAP[b"EQ_OFF"] == 0
    assert b"BT_PLAY" in nextion.TOKENS
    assert len(nextion.TOKENS) == len(nextion.TOK_BT) + len(nextion.TOK_EQ)


def test_nextion_process_bytes():
    """Test token processing."""
    nx = nextion.Nextion()

    handled_tokens = []

    def token_handler(token):
        handled_tokens.append(token)

    # Send a clean token
    nx.process_bytes(b"BT_PLAY" + nextion.TERM, token_handler)
    assert b"BT_PLAY" in handled_tokens

    # Test with noise
    handled_tokens.clear()
    nx.rx_buffer.clear()
    nx.process_bytes(bytes([0x1A]) + b"BT_NEXT" + nextion.TERM, token_handler)
    assert b"BT_NEXT" in handled_tokens


def test_nextion_queue():
    """Test command queue."""
    nx = nextion.Nextion()
    nx.send_cmd("test1")
    nx.send_cmd("test2")
    assert len(nx.tx_queue) == 2

from __future__ import annotations

from bm83.bm83 import Bm83
from nextion.display import Nextion, TERM


class MockUART:
    def __init__(self):
        self.to_read = bytearray()
        self.in_waiting = 0

    def write(self, _data):
        return None

    def read(self, n):
        out = self.to_read[:n]
        self.to_read = self.to_read[n:]
        self.in_waiting = len(self.to_read)
        return bytes(out)


def _frame(op, payload=b""):
    body = bytes([op]) + payload
    ln = len(body)
    hi, lo = (ln >> 8) & 0xFF, ln & 0xFF
    chk = (-((hi + lo + sum(body)) & 0xFF)) & 0xFF
    return bytes([0xAA, hi, lo]) + body + bytes([chk])


def test_nextion_burst_token_stream_recovers_from_noise_and_fragmentation():
    nx = Nextion()
    handled = []

    token_frames = [
        b"\x00BT_PLAY\x00" + TERM,
        b"BT_NEXT" + TERM,
        b"\x1AEQ_POP" + TERM,
        b"BT_PREV" + TERM,
    ]
    burst = b"noise" + b"".join(token_frames) + b"partial"

    # Feed as non-uniform fragments (stress-style burst input)
    splits = (1, 7, 19, 31, 48, len(burst))
    start = 0
    for end in splits:
        nx.process_bytes(burst[start:end], handled.append)
        start = end

    # incomplete trailing bytes should remain buffered and not emit token
    assert nx.rx_buffer.endswith(b"partial")
    assert handled == [b"BT_PLAY", b"BT_NEXT", b"EQ_POP", b"BT_PREV"]


def test_bm83_fragmented_frames_and_checksum_recovery_under_burst_load():
    uart = MockUART()
    bm = Bm83(uart)

    good1 = _frame(Bm83.EVT_EQ_MODE_IND, b"\x03")
    good2 = _frame(Bm83.EVT_BTM_STATUS, b"\x06")
    bad = bytearray(_frame(Bm83.EVT_EQ_MODE_IND, b"\x05"))
    bad[-1] ^= 0xFF  # force checksum failure

    # Burst stream contains fragmented valid frame, corrupted frame, then valid recovery frame.
    burst = good1[:3] + good1[3:] + bytes(bad) + good2

    # Feed in small chunks to stress parser's incremental recovery behavior.
    for i in range(0, len(burst), 2):
        uart.to_read.extend(burst[i : i + 2])
    uart.in_waiting = len(uart.to_read)

    events = []
    while uart.in_waiting:
        events.extend(bm.poll(max_read=5, max_events=8))

    assert events == [
        (Bm83.EVT_EQ_MODE_IND, b"\x03"),
        (Bm83.EVT_BTM_STATUS, b"\x06"),
    ]


def _gea_attr(aid, text):
    val = text.encode("utf-8")
    return aid.to_bytes(4, "big") + b"\x00\x00" + len(val).to_bytes(2, "big") + val


def _gea_params(is_end, attr_num, total_len, part):
    # pdu_id=0x20 (GetElementAttributes), placeholder, resp, is_end, attr_num, total_len(16-bit BE)
    return bytes([0x20, 0x00, 0x01, is_end, attr_num]) + total_len.to_bytes(2, "big") + part


def _assert_gea_idle(bm):
    assert len(bm._gea_frag) == 0
    assert bm._gea_expect_len is None
    assert bm._gea_frag_at == 0.0


def test_gea_oversize_header_rejected_without_buffering():
    bm = Bm83(None)
    for total_len in (Bm83.GEA_MAX_LEN + 1, 0xFFFF):
        assert bm.parse_gea_0x5d(_gea_params(0x00, 1, total_len, b"\x41" * 32)) is None
        _assert_gea_idle(bm)
        # A final fragment claiming the same oversize length is rejected too.
        assert bm.parse_gea_0x5d(_gea_params(0x01, 1, total_len, b"\x41" * 32)) is None
        _assert_gea_idle(bm)


def test_gea_oversize_header_resets_partial_reassembly_then_valid_parses():
    bm = Bm83(None)
    old = _gea_attr(1, "Old Title")
    assert bm.parse_gea_0x5d(_gea_params(0x00, 1, len(old), old[:6])) is None
    assert bm._gea_expect_len == len(old)

    assert bm.parse_gea_0x5d(_gea_params(0x00, 1, 0xFFFF, b"\x00" * 64)) is None
    _assert_gea_idle(bm)

    # The tail of the abandoned response must not stitch onto anything.
    assert bm.parse_gea_0x5d(_gea_params(0x01, 1, len(old), old[6:])) is None
    _assert_gea_idle(bm)

    fresh = _gea_attr(1, "New Title") + _gea_attr(2, "New Artist")
    part1 = _gea_params(0x00, 2, len(fresh), fresh[:11])
    part2 = _gea_params(0x01, 2, len(fresh), fresh[11:])
    assert bm.parse_gea_0x5d(part1) is None
    resp, attrs = bm.parse_gea_0x5d(part2)
    assert resp == 0x01
    assert attrs == {1: "New Title", 2: "New Artist"}
    _assert_gea_idle(bm)


def test_gea_response_at_exact_cap_still_reassembles():
    bm = Bm83(None)
    value = "x" * (Bm83.GEA_MAX_LEN - 8)
    payload = _gea_attr(3, value)
    assert len(payload) == Bm83.GEA_MAX_LEN

    chunk = 500
    pieces = [payload[i : i + chunk] for i in range(0, len(payload), chunk)]
    for piece in pieces[:-1]:
        assert bm.parse_gea_0x5d(_gea_params(0x00, 1, len(payload), piece)) is None
        assert len(bm._gea_frag) <= Bm83.GEA_MAX_LEN
    resp, attrs = bm.parse_gea_0x5d(_gea_params(0x01, 1, len(payload), pieces[-1]))
    assert attrs == {3: value}


def test_gea_oversize_stream_over_uart_never_grows_buffer_past_cap():
    """End-to-end: valid UART frames carrying an oversize GEA header, then a good one."""
    uart = MockUART()
    bm = Bm83(uart)

    stream = bytearray()
    # Twenty well-formed, checksum-valid frames all claiming a 64 KiB response.
    for i in range(20):
        is_end = 0x01 if i == 19 else 0x00
        stream += _frame(Bm83.EVT_AVRCP_VENDOR_DEP_RSP, _gea_params(is_end, 7, 0xFFFF, b"\x5A" * 200))
    good = _gea_attr(1, "Recovered") + _gea_attr(2, "Artist")
    stream += _frame(Bm83.EVT_AVRCP_VENDOR_DEP_RSP, _gea_params(0x00, 2, len(good), good[:9]))
    stream += _frame(Bm83.EVT_AVRCP_VENDOR_DEP_RSP, _gea_params(0x01, 2, len(good), good[9:]))
    uart.to_read.extend(stream)
    uart.in_waiting = len(uart.to_read)

    results = []
    peak = 0
    while uart.in_waiting:
        for op, params in bm.poll(max_read=64, max_events=8):
            assert op == Bm83.EVT_AVRCP_VENDOR_DEP_RSP
            out = bm.parse_gea_0x5d(params)
            peak = max(peak, len(bm._gea_frag))
            if out is not None:
                results.append(out)

    assert peak <= Bm83.GEA_MAX_LEN
    assert results == [(0x01, {1: "Recovered", 2: "Artist"})]
    _assert_gea_idle(bm)

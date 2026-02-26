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

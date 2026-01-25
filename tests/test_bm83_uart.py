from bm83.bm83 import Bm83


class MockUART:
    def __init__(self):
        self.writes = []
        self.to_read = bytearray()
        self.in_waiting = 0

    def write(self, data):
        self.writes.append(data)

    def read(self, n):
        out = self.to_read[:n]
        self.to_read = self.to_read[n:]
        self.in_waiting = len(self.to_read)
        return out

def frame_to_bytes(op, payload):
    b = bytes([op]) + payload
    ln = len(b)
    hi, lo = (ln >> 8) & 0xFF, ln & 0xFF
    checksum = (-((hi + lo + sum(b)) & 0xFF)) & 0xFF
    return bytes([0xAA, hi, lo]) + b + bytes([checksum])

def test_bm83_send_command():
    uart = MockUART()
    bm = Bm83(uart)
    bm.send(Bm83.OP_READ_BD_ADDR)
    assert uart.writes  # something was written
    assert uart.writes[0].startswith(b'\xAA')  # start of frame

def test_bm83_poll_event_parsing():
    uart = MockUART()
    bm = Bm83(uart)
    # Simulate a valid EVT_EQ_MODE_IND with mode=0x05
    op = Bm83.EVT_EQ_MODE_IND
    payload = bytes([0x05])
    pkt = frame_to_bytes(op, payload)
    uart.to_read += pkt
    uart.in_waiting = len(pkt)
    events = bm.poll()
    assert len(events) == 1
    evt_op, evt_data = events[0]
    assert evt_op == op
    assert evt_data == payload

def test_bm83_invalid_checksum_skips_packet():
    uart = MockUART()
    bm = Bm83(uart)
    # Create a packet with invalid checksum
    bad_packet = bytearray([0xAA, 0x00, 0x01, 0x01, 0x00])  # wrong checksum
    uart.to_read += bad_packet
    uart.in_waiting = len(bad_packet)
    events = bm.poll()
    assert events == []

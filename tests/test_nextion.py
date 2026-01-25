from nextion.display import Nextion


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

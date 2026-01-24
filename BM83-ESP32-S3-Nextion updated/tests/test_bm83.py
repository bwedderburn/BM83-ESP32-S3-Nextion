from bm83.bm83 import Bm83

def test_checksum():
    hi, lo = 0x00, 0x03
    body = bytes([0x01, 0x02, 0x03])
    chk = Bm83._checksum(hi, lo, body)
    total = (hi + lo + sum(body) + chk) & 0xFF
    assert total == 0

def test_avc_payload():
    pdu = 0x30
    params = b"\x01\x02"
    payload = Bm83._avc_payload(pdu, params)
    assert payload.startswith(b"\x30\x00")
    assert payload[4:] == params

from bm83.bm83 import Bm83


def test_avrcp_parse_metadata_attrs():
    bm = Bm83(None)

    # Simulated raw GEA data: 1 attr (title="Test Song"), complete
    attr_id = (1).to_bytes(4, "big")     # title
    str_val = b"Test Song"
    str_len = len(str_val).to_bytes(2, "big")
    full_payload = attr_id + b"\x00\x00" + str_len + str_val

    params = bytes([
        0x20,  # pdu_id
        0x00,  # placeholder
        0x01,  # resp
        0x01,  # is_end
        0x01,  # attr count
    ]) + len(full_payload).to_bytes(2, "big") + full_payload

    result = bm.parse_gea_0x5d(params)
    assert result is not None
    resp, attrs = result
    assert 1 in attrs
    assert attrs[1] == "Test Song"

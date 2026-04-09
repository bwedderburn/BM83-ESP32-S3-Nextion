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


def test_avrcp_parse_metadata_fragmented_response_reassembles_cleanly():
    bm = Bm83(None)

    def attr(aid, text):
        val = text.encode("utf-8")
        return aid.to_bytes(4, "big") + b"\x00\x00" + len(val).to_bytes(2, "big") + val

    payload = attr(1, "Test Song") + attr(7, "773")
    total_len = len(payload).to_bytes(2, "big")

    part1 = bytes([0x20, 0x00, 0x01, 0x00, 0x02]) + total_len + payload[:10]
    part2 = bytes([0x20, 0x00, 0x01, 0x01, 0x02]) + total_len + payload[10:]

    assert bm.parse_gea_0x5d(part1) is None
    resp, attrs = bm.parse_gea_0x5d(part2)
    assert resp == 0x01
    assert attrs[1] == "Test Song"
    assert attrs[7] == "773"


def test_avrcp_parse_metadata_resets_stale_fragment_on_new_length():
    bm = Bm83(None)

    def attr(aid, text):
        val = text.encode("utf-8")
        return aid.to_bytes(4, "big") + b"\x00\x00" + len(val).to_bytes(2, "big") + val

    stale_payload = attr(1, "Old Title")
    fresh_payload = attr(2, "New Artist")

    stale = bytes([0x20, 0x00, 0x01, 0x00, 0x01]) + len(stale_payload).to_bytes(2, "big") + stale_payload[:6]
    fresh = bytes([0x20, 0x00, 0x01, 0x01, 0x01]) + len(fresh_payload).to_bytes(2, "big") + fresh_payload

    assert bm.parse_gea_0x5d(stale) is None
    resp, attrs = bm.parse_gea_0x5d(fresh)
    assert resp == 0x01
    assert attrs == {2: "New Artist"}

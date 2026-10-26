"""Decode complete primary advertising packets independently of the name budget."""
import sys
from types import ModuleType, SimpleNamespace

import pytest

from blehid import ble as module


class Advertisement:
    # Adafruit ProvideServicesAdvertisement(HID): 16-bit UUID list + flags.
    base = b"\x03\x02\x12\x18\x02\x01\x06"

    def __init__(self, service):
        self.service = service
        self.complete_name = None

    def __bytes__(self):
        data = self.base
        if self.complete_name is not None:
            encoded = self.complete_name.encode("utf-8")
            data += bytes((len(encoded) + 1, 0x09)) + encoded
        return data


@pytest.fixture
def advertisements(monkeypatch):
    standard = ModuleType("adafruit_ble.advertising.standard")
    standard.ProvideServicesAdvertisement = Advertisement
    monkeypatch.setitem(sys.modules, "adafruit_ble.advertising.standard", standard)
    return Advertisement


def fields(data):
    result = {}
    offset = 0
    while offset < len(data):
        size = data[offset]
        assert size >= 1 and offset + size < len(data)
        result[data[offset + 1]] = data[offset + 2:offset + size + 1]
        offset += size + 1
    assert offset == len(data)
    return result


def test_preferred_name_is_complete_in_primary_packet(advertisements):
    name = "B's Groovy Music CTRL"
    service = object()
    advertisement = module._named_advertisement(service, name)
    payload = bytes(advertisement)
    assert advertisement.service is service
    assert len(name.encode("utf-8")) == 21
    assert len(payload) == 30
    assert fields(payload) == {0x02: b"\x12\x18", 0x01: b"\x06", 0x09: name.encode("utf-8")}


@pytest.mark.parametrize("name,primary_name", [
    ("x" * 22, True), ("x" * 23, False),
    ("é" * 11, True), ("é" * 12, False),
    ("B's Groovy Music CTRL_1", False),
])
def test_budget_counts_utf8_and_preserves_services(advertisements, name, primary_name):
    payload = bytes(module._named_advertisement(object(), name))
    assert len(payload) <= 31
    decoded = fields(payload)
    assert decoded[0x02] == b"\x12\x18" and decoded[0x01] == b"\x06"
    assert (0x09 in decoded) is primary_name
    if primary_name:
        assert decoded[0x09].decode("utf-8") == name


def test_budget_uses_encoded_base_packet_not_assumed_size(advertisements, monkeypatch):
    monkeypatch.setattr(advertisements, "base", advertisements.base + b"\x04\xff\x01\x02\x03")
    payload = bytes(module._named_advertisement(object(), "B's Groovy Music CTRL"))
    assert len(payload) == 12
    assert 0x09 not in fields(payload)


def test_explicit_erase_rename_rebuilds_name_and_keeps_full_gap_fallback(advertisements):
    hid = module.BleHid(True, "B's Groovy Music CTRL")
    hid._hid = object()
    hid._ble = SimpleNamespace(name=hid.name)
    hid._adv = module._named_advertisement(hid._hid, hid.name)
    assert 0x09 in fields(bytes(hid._adv))
    hid._update_ble_name(1)
    assert hid.name == hid._ble.name == "B's Groovy Music CTRL_1"
    assert len(bytes(hid._adv)) == 7
    assert 0x09 not in fields(bytes(hid._adv))  # no stale old primary name
    # BLERadio.start_advertising's unchanged default uses this GAP name in
    # its scan response when no custom scan_response is supplied.

"""Verify the advertised HID roles and the real BleHid setup/send path."""
import sys
import types

from blehid import ble as ble_mod
from blehid.ble import BleHid


def parse_report_map(data):
    """Decode HID short items independently of Adafruit's report-map parser."""
    globals_ = {}
    locals_ = {}
    stack = []
    collections = []
    reports = []
    pages = set()
    offset = 0
    while offset < len(data):
        prefix = data[offset]
        offset += 1
        assert prefix != 0xFE, "unexpected HID long item"
        size = (0, 1, 2, 4)[prefix & 3]
        assert offset + size <= len(data), "truncated HID short item"
        raw = data[offset:offset + size]
        offset += size
        kind, tag = (prefix >> 2) & 3, prefix >> 4
        value = int.from_bytes(raw, "little")
        if kind == 1:  # Global item: state survives collection/input items.
            globals_[tag] = value
            if tag == 0:
                pages.add(value)
        elif kind == 2:
            locals_[tag] = value
        elif kind == 0:
            if tag == 10:  # Collection
                collection = (globals_.get(0), locals_.get(0), value)
                if not stack:
                    collections.append(collection)
                stack.append(collection)
            elif tag == 12:  # End Collection
                assert stack, "unbalanced HID collection"
                stack.pop()
            elif tag in (8, 9, 11):  # Input, Output, Feature
                assert stack, "HID report outside a collection"
                reports.append({"kind": tag, "flags": value, "collection": stack[0],
                                "globals": dict(globals_), "locals": dict(locals_)})
            else:
                raise AssertionError("unexpected HID main item")
            locals_ = {}
        else:
            raise AssertionError("unexpected reserved HID item")
    assert not stack, "unclosed HID collection"
    return collections, reports, pages


def test_report_map_has_only_one_consumer_input():
    collections, reports, pages = parse_report_map(ble_mod._CONSUMER_ONLY_HID_DESCRIPTOR)
    assert collections == [(0x0C, 0x01, 1)]  # Consumer Control / Application.
    assert pages == {0x0C}                  # No Desktop/Keyboard/LED pages.
    assert len(reports) == 1               # No keyboard, mouse, OUT or FEATURE reports.
    report = reports[0]
    assert report["kind"] == 8
    assert report["flags"] & 7 == 0         # Data, Array, Absolute.
    state, usages = report["globals"], report["locals"]
    assert state[8] == 3                   # Retain the existing consumer report ID.
    assert state[7] == 16 and state[9] == 1  # One unsigned two-byte selector.
    for code in (0xE2, 0xE9, 0xEA):        # Mute, Volume Increment, Volume Decrement.
        assert state[1] <= code <= state[2]
        assert usages[1] <= code <= usages[2]
    # Zero remains the existing all-released frame. For this Array descriptor
    # it is below the selector range, rather than a new keyboard key report.
    assert state[1] in (0, 1) and usages[1] in (0, 1)


class CharacteristicMarker:
    def __init__(self, uuid):
        self.uuid = uuid


class Device:
    usage_page = 0x0C
    usage = 0x01

    def __init__(self):
        self.reports = []

    def send_report(self, report):
        self.reports.append(bytes(report))


class HIDService:
    # Adafruit BLE 10.1.3 declares these on the base HIDService class.
    # Its Service initializer eagerly finds/binds inherited descriptors.
    boot_keyboard_in = CharacteristicMarker(0x2A22)
    boot_keyboard_out = CharacteristicMarker(0x2A32)
    protocol_mode = CharacteristicMarker(0x2A4E)
    report_map = CharacteristicMarker(0x2A4B)
    hid_information = CharacteristicMarker(0x2A4A)
    suspended = CharacteristicMarker(0x2A4C)

    def __init__(self, hid_descriptor=None):
        self.bound = {}
        # Match the upstream class-descriptor binding seam, rather than
        # treating a new report map as sufficient to remove boot reports.
        for name in dir(self.__class__):
            value = getattr(self.__class__, name)
            if isinstance(value, CharacteristicMarker):
                self.bound[name] = value.uuid
        assert hid_descriptor is not None, "default HID profile would include a keyboard"
        self.report_map = hid_descriptor
        collections, reports, _pages = parse_report_map(hid_descriptor)
        assert collections == [(0x0C, 0x01, 1)] and len(reports) == 1
        self.devices = [Device()]


class Connection:
    paired = False

    def pair(self):
        raise AssertionError("the peripheral must never initiate pairing")


class Radio:
    def __init__(self):
        self.name = ""
        self.connected = self.advertising = False
        self.connections = [Connection()]
        self.advertisements = []

    def __setattr__(self, name, value):
        assert name != "appearance", "do not introduce a GAP HID subtype"
        object.__setattr__(self, name, value)

    def start_advertising(self, advertisement):
        self.advertising = True
        self.advertisements.append(advertisement)

    def stop_advertising(self):
        self.advertising = False

    def erase_bonding(self):
        raise AssertionError("profile setup must not erase existing bonds")


class Advertisement:
    def __init__(self, service):
        self.service = service


class ConsumerControl:
    def __init__(self, devices):
        self.device = next(device for device in devices
                           if device.usage_page == 0x0C and device.usage == 0x01)

    def send(self, code):
        # Public ConsumerControl API sends an unsigned little-endian
        # selector, immediately followed by the all-released report.
        self.device.send_report(code.to_bytes(2, "little"))
        self.device.send_report(b"\x00\x00")


class Codes:
    VOLUME_INCREMENT = 0xE9
    VOLUME_DECREMENT = 0xEA
    MUTE = 0xE2


def test_real_setup_omits_boot_keyboard_and_sends_volume_and_mute(monkeypatch):
    modules = {
        "adafruit_ble": {"BLERadio": Radio},
        "adafruit_ble.advertising": {},
        "adafruit_ble.advertising.standard": {"ProvideServicesAdvertisement": Advertisement},
        "adafruit_ble.services": {},
        "adafruit_ble.services.standard": {},
        "adafruit_ble.services.standard.hid": {"HIDService": HIDService},
        "adafruit_hid": {},
        "adafruit_hid.consumer_control": {"ConsumerControl": ConsumerControl},
        "adafruit_hid.consumer_control_code": {"ConsumerControlCode": Codes},
    }
    for name, attrs in modules.items():
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    clock = [100000]
    monkeypatch.setattr(ble_mod, "ticks_ms", lambda: clock[0])
    monkeypatch.setattr(ble_mod.time, "monotonic", lambda: clock[0] / 1000)
    monkeypatch.setattr(ble_mod, "_read_ble_counter", lambda: 7)
    hid = BleHid(True, "Volume remote")
    hid.setup()
    assert hid._ready
    assert hid.name == hid._ble.name == "Volume remote_7"
    assert hid._hid.report_map == ble_mod._CONSUMER_ONLY_HID_DESCRIPTOR
    assert set(hid._hid.bound.values()) == {0x2A4B, 0x2A4A, 0x2A4C}
    assert hid._ble.advertisements[0].service is hid._hid
    assert hid._cc.device is hid._hid.devices[0]

    hid._ble.connected = True
    hid.tick()  # Exercise the unchanged passive pairing observer too.
    hid.volume(True)
    hid.volume(False)  # Same tick: preserve the existing 60ms send limiter.
    clock[0] += 60
    hid.volume(False)
    clock[0] += 60
    hid.mute()
    assert hid._cc.device.reports == [b"\xe9\x00", b"\x00\x00",
                                      b"\xea\x00", b"\x00\x00",
                                      b"\xe2\x00", b"\x00\x00"]

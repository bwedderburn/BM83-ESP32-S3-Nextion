"""Exercise real Python wire frames against the CrowPanel's C++ model."""
import os
import shutil
import subprocess  # nosec B404 - fixed local compiler and host-test binary only
from pathlib import Path

import pytest

from remote.now_playing import (
    FRAGMENT_SIZE, MAX_PAYLOAD, UNKNOWN, crc16, encode_frames,
)

ROOT = Path(__file__).resolve().parents[1]


def state(**changes):
    snapshot = dict(power_on=True, connected=True, aux=False, play_status=1, eq_index=2,
                    duration_ms=200000, position_ms=50000, position_age_ms=100,
                    clock_advancing=True, title='A "new" song', artist="Björk", album="Album with long title")
    snapshot.update(changes)
    return snapshot


def raw_frames(payload, session=42, seq=1):
    count = (len(payload) + FRAGMENT_SIZE - 1) // FRAGMENT_SIZE
    prefix = b"BMS2" + session.to_bytes(4, "big") + seq.to_bytes(2, "big")
    suffix = len(payload).to_bytes(2, "big") + crc16(payload).to_bytes(2, "big")
    return tuple(prefix + bytes((index, count)) + suffix + payload[index * 48:(index + 1) * 48]
                 for index in range(count))


def payload_of(frames):
    return b"".join(frame[16:] for frame in frames)


@pytest.fixture(scope="module")
def cpp_model(tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        pytest.skip("no C++ compiler on this machine")
    binary = tmp_path_factory.mktemp("now_playing_host") / ("model.exe" if os.name == "nt" else "model")
    result = subprocess.run(  # nosec B603 - fixed local source/include paths
        [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-pedantic",
         "-I" + str(ROOT / "firmware/crowpanel-remote/include"),
         str(ROOT / "tests/crowpanel_host/now_playing_test.cpp"), "-o", str(binary)],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return binary


def probe(binary, operations):
    commands = []
    for operation in operations:
        if operation[0] == "F":
            commands.append("F %d %s" % (operation[1] & UNKNOWN, operation[2].hex()))
        elif operation[0] == "P":
            commands.append("P %d" % (operation[1] & UNKNOWN))
        else:
            commands.append("R")
    result = subprocess.run(  # nosec B603 - locally built host probe; no hardware
        [str(binary)], input="\n".join(commands) + "\n", capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    results = []
    for line in result.stdout.splitlines():
        values = line.split()
        if values[0] != "P":
            results.append((values[0], int(values[1]) if len(values) > 1 else 0))
            continue
        names = ("fresh", "have", "position", "status", "eq", "duration", "sample", "age", "flags", "max_text")
        decoded = dict(zip(names, map(int, values[1:11])))
        decoded.update(zip(("title", "artist", "album"),
                           ("" if value == "-" else bytes.fromhex(value).decode("utf-8") for value in values[11:])))
        results.append(decoded)
    return results


def send(frames, now=1000):
    return [("F", now, frame) for frame in frames]


def test_known_crc_and_fixed_wire_layout():
    assert crc16(b"123456789") == 0x29B1
    frames = encode_frames(state(), 0x12345678, 0xABCD)
    assert frames[0][:12] == b"BMS2\x12\x34\x56\x78\xab\xcd\x00\x02"
    payload = payload_of(frames)
    assert payload[:3] == b"\x0b\x01\x02"
    assert int.from_bytes(payload[3:7], "big") == 200000
    assert int.from_bytes(payload[7:11], "big") == 50000
    assert int.from_bytes(payload[11:15], "big") == 100
    assert int.from_bytes(frames[0][12:14], "big") == len(payload)
    assert int.from_bytes(frames[0][14:16], "big") == crc16(payload)


def test_text_is_bounded_utf8_and_controls_are_sanitized():
    frames = encode_frames(state(title="x" * 95 + "🎵", artist="é" * 100, album="A\0B\nC\tD"), 1, 1)
    payload = payload_of(frames)
    lengths = payload[15:18]
    assert lengths == bytes((95, 96, 7))
    assert payload[18:18 + lengths[0]].decode("utf-8") == "x" * 95
    assert payload[-7:] == b"A B C D"
    assert all(len(frame) <= 64 for frame in frames)


def test_maximum_size_and_missing_fields():
    frames = encode_frames(state(title="x" * 96, artist="y" * 96, album="z" * 96), 1, 1)
    assert len(frames) == 7
    assert len(payload_of(frames)) == MAX_PAYLOAD
    assert len(frames[-1]) == 16 + MAX_PAYLOAD % 48
    empty = payload_of(encode_frames({}, 1, 1))
    assert empty[:3] == b"\x00\xff\xff"
    assert empty[3:15] == b"\xff" * 12
    assert empty[15:] == b"\x00\x00\x00"


@pytest.mark.parametrize("bad", [None, -1, UNKNOWN, UNKNOWN + 10, "invalid", float("inf")])
def test_invalid_timing_is_unknown(bad):
    payload = payload_of(encode_frames(state(position_ms=bad), 1, 1))
    assert payload[7:11] == b"\xff" * 4


def test_cross_language_atomic_text_and_clock(cpp_model):
    frames = encode_frames(state(), 42, 1)
    result = probe(cpp_model, [("P", 1000)] + send(frames) + [("P", 1500), ("P", 3000)])
    assert result[0]["have"] == 0
    assert [entry for entry in result if isinstance(entry, tuple)] == [("A", 0), ("A", 1)]
    assert result[-2]["title"] == 'A "new" song'
    assert result[-2]["artist"] == "Björk"
    assert result[-2]["album"] == "Album with long title"
    assert result[-2]["position"] == 50600
    assert result[-1]["position"] == 52100


def test_fragment_delay_uses_first_receipt_as_clock_anchor(cpp_model):
    frames = encode_frames(state(), 1, 1)
    result = probe(cpp_model, [("F", 1000, frames[0]), ("F", 1300, frames[1]), ("P", 1500)])
    assert result[-1]["position"] == 50600


def test_reordering_duplicates_and_lost_fragment_never_mix_tracks(cpp_model):
    old = encode_frames(state(title="old"), 1, 1)
    new = encode_frames(state(title="新" * 32, artist="a" * 96, album="b" * 96), 1, 2)
    next_track = encode_frames(state(title="third", position_ms=1200), 1, 3)
    result = probe(cpp_model, send(old) + send(new[:-1], 1200) + [("P", 1200)] +
                   send(tuple(reversed(next_track)), 1400) + send(new[-1:], 1500) + [("P", 1600)])
    assert result[len(old) + len(new) - 1]["title"] == "old"
    assert result[-1]["title"] == "third"
    assert result[-1]["position"] == 1500
    assert sum(entry == ("A", 1) for entry in result) == 2


def test_duplicate_snapshot_cannot_refresh_freshness(cpp_model):
    frames = encode_frames(state(), 1, 1)
    result = probe(cpp_model, send(frames) + send(frames, 6500) + [("P", 7000)])
    assert result[-1]["fresh"] == 0
    assert result[-1]["position"] == UNKNOWN


def test_corrupt_and_malformed_frames_preserve_committed_state(cpp_model):
    good = encode_frames(state(title="good"), 1, 1)
    new = encode_frames(state(title="bad"), 1, 2)
    corrupt = bytearray(new[-1])
    corrupt[-1] ^= 1
    malformed = []
    for offset, value in ((0, ord("X")), (10, 7), (11, 0), (12, 255)):
        frame = bytearray(new[0])
        frame[offset] = value
        malformed.append(bytes(frame))
    operations = send(good) + send(new[:-1], 1200) + send((bytes(corrupt),), 1200)
    operations += send(tuple(malformed) + (new[0][:-1], b"BMS2"), 1400) + [("P", 1500)]
    result = probe(cpp_model, operations)
    assert result[-1]["title"] == "good"
    assert sum(entry == ("A", 1) for entry in result) == 1


@pytest.mark.parametrize("offset,value", [(0, 16), (1, 5), (15, 97), (18, 0), (18, 0xFF)])
def test_invalid_payload_rejected_even_with_valid_crc(cpp_model, offset, value):
    payload = bytearray(payload_of(encode_frames(state(), 1, 1)))
    payload[offset] = value
    result = probe(cpp_model, send(raw_frames(payload)) + [("P", 1100)])
    assert result[-1]["have"] == 0


def test_sequence_wrap_and_reboot_retire_old_session(cpp_model):
    first = encode_frames(state(title="first"), 111, 65535)
    wrapped = encode_frames(state(title="wrapped"), 111, 0)
    reboot = encode_frames(state(title="reboot"), 222, 1)
    old = encode_frames(state(title="stale"), 111, 1)
    result = probe(cpp_model, send(first) + send(wrapped, 1100) + send(first, 1200) +
                   send(reboot, 1300) + send(old, 1400) + [("P", 1500)])
    assert result[-1]["title"] == "reboot"
    assert sum(entry == ("A", 1) for entry in result) == 3


def test_pause_seek_track_change_and_duration_clamp(cpp_model):
    paused = encode_frames(state(play_status=2, position_ms=50000), 1, 1)
    seek = encode_frames(state(play_status=1, position_ms=190000), 1, 2)
    next_track = encode_frames(state(title="next", position_ms=100, duration_ms=300), 1, 3)
    result = probe(cpp_model, send(paused) + [("P", 2000)] + send(seek, 2100) + [("P", 2200)] +
                   send(next_track, 2300) + [("P", 2600)])
    states = [entry for entry in result if isinstance(entry, dict)]
    assert [entry["position"] for entry in states] == [50000, 190200, 300]
    assert states[-1]["title"] == "next"


@pytest.mark.parametrize("changes", [
    dict(position_ms=None), dict(position_age_ms=None), dict(position_age_ms=5001),
    dict(power_on=False), dict(connected=False), dict(aux=True),
])
def test_unavailable_source_position_is_never_invented(cpp_model, changes):
    result = probe(cpp_model, send(encode_frames(state(**changes), 1, 1)) + [("P", 1100)])
    assert result[-1]["position"] == UNKNOWN


def test_clock_stops_when_source_sample_stale_despite_fresh_radio(cpp_model):
    first = encode_frames(state(position_age_ms=4900), 1, 1)
    stale = encode_frames(state(position_age_ms=7000), 1, 2)
    result = probe(cpp_model, send(first) + [("P", 1100), ("P", 1101)] +
                   send(stale, 1200) + [("P", 1200)])
    states = [entry for entry in result if isinstance(entry, dict)]
    assert states[0]["position"] == 55000
    assert states[1]["position"] == UNKNOWN
    assert states[2]["fresh"] == 1 and states[2]["position"] == UNKNOWN


def test_millis_wrap_and_reset(cpp_model):
    start = 0xFFFFFF00
    frames = encode_frames(state(), 1, 1)
    result = probe(cpp_model, send(frames, start) + [("P", start + 500), ("R",), ("P", start + 600)])
    assert result[-3]["position"] == 50600
    assert result[-1]["have"] == 0 and result[-1]["position"] == UNKNOWN


def test_expired_radio_snapshot_cannot_revive_after_full_millis_wrap(cpp_model):
    frames = encode_frames(state(), 1, 1)
    result = probe(cpp_model, send(frames, 1000) + [("P", 8000), ("P", 1001)] +
                   send(encode_frames(state(title="Fresh"), 1, 2), 1100) + [("P", 1100)])
    states = [entry for entry in result if isinstance(entry, dict)]
    assert states[0]["fresh"] == states[1]["fresh"] == 0
    assert states[-1]["fresh"] == 1


def test_interpolation_flag_defaults_false_and_never_fakes_pause_status(cpp_model):
    snapshot = state()
    del snapshot["clock_advancing"]
    frames = encode_frames(snapshot, 1, 1)
    assert payload_of(frames)[0] == 3
    result = probe(cpp_model, send(frames) + [("P", 1500), ("P", 3000)])
    assert result[-2]["position"] == result[-1]["position"] == 50000
    assert result[-1]["status"] == 1


def test_windows_playing_label_with_frozen_source_clock_stays_frozen(cpp_model):
    from remote.state_tx import StatePublisher

    now = [1000]
    publisher = StatePublisher(object(), clock=lambda: now[0], session=55)
    publisher.set_transport(True, True, False)
    publisher.note_status(1)
    publisher.note_position(12000, 180000)
    operations = send(encode_frames(publisher.snapshot(), 55, 1), now[0])
    operations += [("P", 1500)]
    now[0] = 2000
    publisher.note_position(13000)
    operations += send(encode_frames(publisher.snapshot(), 55, 2), now[0])
    operations += [("P", 2250)]
    # Windows keeps saying PLAYING, but actual source time stopped.
    now[0] = 3000
    publisher.note_position(13000)
    operations += send(encode_frames(publisher.snapshot(), 55, 3), now[0])
    operations += [("P", 3250), ("P", 3750)]
    now[0] = 4000
    publisher.note_position(13000)
    operations += send(encode_frames(publisher.snapshot(), 55, 4), now[0])
    operations += [("P", 4500)]
    now[0] = 5000
    publisher.note_position(14000)
    operations += send(encode_frames(publisher.snapshot(), 55, 5), now[0])
    operations += [("P", 5250)]
    result = [entry for entry in probe(cpp_model, operations) if isinstance(entry, dict)]
    assert [entry["position"] for entry in result] == [12000, 13250, 13000, 13000, 13000, 14250]
    assert all(entry["status"] == 1 for entry in result)


def test_actual_paused_status_always_suppresses_interpolation(cpp_model):
    frames = encode_frames(state(play_status=2, clock_advancing=True), 1, 1)
    result = probe(cpp_model, send(frames) + [("P", 1500), ("P", 3000)])
    assert result[-2]["position"] == result[-1]["position"] == 50000
    assert result[-1]["status"] == 2


def test_web_player_paused_counter_drift_is_held_without_hiding_raw_samples(cpp_model):
    operations = []
    for sequence, now, raw_position in ((1, 1000, 143360), (2, 5000, 148368), (3, 9000, 153393)):
        operations += send(encode_frames(state(play_status=2, clock_advancing=False,
                                                position_ms=raw_position, position_age_ms=1),
                                         1, sequence), now)
        operations += [("P", now + 250)]
    result = [entry for entry in probe(cpp_model, operations) if isinstance(entry, dict)]
    assert [entry["position"] for entry in result] == [143360, 143360, 143360]
    assert [entry["sample"] for entry in result] == [143360, 148368, 153393]
    assert all(entry["status"] == 2 and entry["fresh"] == 1 for entry in result)


def test_paused_seek_is_shown_on_resume_not_inferred_from_a_drifting_counter(cpp_model):
    operations = send(encode_frames(state(play_status=2, position_ms=50000), 1, 1))
    operations += send(encode_frames(state(play_status=2, position_ms=90000), 1, 2), 2000)
    operations += [("P", 2250)]
    operations += send(encode_frames(state(play_status=1, clock_advancing=True,
                                           position_ms=90000, position_age_ms=0), 1, 3), 3000)
    operations += [("P", 3250)]
    result = [entry for entry in probe(cpp_model, operations) if isinstance(entry, dict)]
    assert result[0]["position"] == 50000
    assert result[0]["sample"] == 90000
    assert result[1]["position"] == 90250
    assert result[1]["status"] == 1


@pytest.mark.parametrize("changed", [
    dict(title="A different track"),
    dict(artist="A different artist"),
    dict(album="A different known album"),
])
def test_known_track_identity_change_starts_a_new_paused_anchor(cpp_model, changed):
    operations = send(encode_frames(state(play_status=2, position_ms=50000), 1, 1))
    operations += send(encode_frames(state(play_status=2, position_ms=1200, **changed), 1, 2), 2000)
    operations += [("P", 2250)]
    result = probe(cpp_model, operations)
    assert result[-1]["position"] == 1200


def test_late_album_metadata_does_not_release_a_same_track_pause_hold(cpp_model):
    operations = send(encode_frames(state(play_status=2, position_ms=50000, album=""), 1, 1))
    operations += send(encode_frames(state(play_status=2, position_ms=55000, album="Album"), 1, 2), 2000)
    operations += [("P", 2250)]
    assert probe(cpp_model, operations)[-1]["position"] == 50000


@pytest.mark.parametrize("unavailable", [
    dict(position_ms=None), dict(position_age_ms=None), dict(position_age_ms=5001),
    dict(power_on=False), dict(connected=False), dict(aux=True),
])
def test_invalid_source_or_transport_clears_pause_hold(cpp_model, unavailable):
    operations = send(encode_frames(state(play_status=2, position_ms=50000), 1, 1))
    bad = state(play_status=2, position_ms=55000)
    bad.update(unavailable)
    operations += send(encode_frames(bad, 1, 2), 2000) + [("P", 2250)]
    operations += send(encode_frames(state(play_status=2, position_ms=60000), 1, 3), 3000)
    operations += [("P", 3250)]
    result = [entry for entry in probe(cpp_model, operations) if isinstance(entry, dict)]
    assert result[0]["position"] == UNKNOWN
    assert result[1]["position"] == 60000


def test_radio_expiry_then_fresh_paused_snapshot_does_not_reuse_old_anchor(cpp_model):
    operations = send(encode_frames(state(play_status=2, position_ms=50000), 1, 1))
    operations += [("P", 7000)]
    operations += send(encode_frames(state(play_status=2, position_ms=90000), 1, 2), 8000)
    operations += [("P", 8250)]
    result = [entry for entry in probe(cpp_model, operations) if isinstance(entry, dict)]
    assert result[0]["position"] == UNKNOWN and result[0]["fresh"] == 0
    assert result[1]["position"] == 90000


def test_controller_session_and_explicit_reset_retire_paused_anchor(cpp_model):
    operations = send(encode_frames(state(play_status=2, position_ms=50000), 1, 1))
    operations += send(encode_frames(state(play_status=2, position_ms=90000), 2, 1), 2000)
    operations += [("P", 2250), ("R",)]
    operations += send(encode_frames(state(play_status=2, position_ms=100000), 2, 2), 3000)
    operations += [("P", 3250)]
    result = [entry for entry in probe(cpp_model, operations) if isinstance(entry, dict)]
    assert [entry["position"] for entry in result] == [90000, 100000]


def test_track_invalidation_then_late_identity_does_not_keep_previous_track_anchor(cpp_model):
    operations = send(encode_frames(state(play_status=2, position_ms=50000), 1, 1))
    operations += send(encode_frames(state(play_status=2, position_ms=1000,
                                           title="", artist="", album=""), 1, 2), 2000)
    operations += [("P", 2250)]
    operations += send(encode_frames(state(play_status=2, position_ms=6000,
                                           title="New track", artist="New artist", album=""), 1, 3), 3000)
    operations += [("P", 3250)]
    result = [entry for entry in probe(cpp_model, operations) if isinstance(entry, dict)]
    assert [entry["position"] for entry in result] == [1000, 1000]


@pytest.mark.parametrize("play_status,clock_advancing", [(2, False), (2, True), (1, False), (3, False), (4, True)])
def test_all_displayed_positions_expire_with_elapsed_local_sample_age(cpp_model, play_status, clock_advancing):
    frames = encode_frames(state(play_status=play_status, clock_advancing=clock_advancing,
                                 position_ms=50000, position_age_ms=4900), 1, 1)
    result = probe(cpp_model, send(frames) + [("P", 1100), ("P", 1101)])
    assert result[-2]["fresh"] == result[-1]["fresh"] == 1
    assert result[-2]["position"] == 50000
    assert result[-1]["position"] == UNKNOWN
    assert result[-1]["status"] == play_status


def test_slow_paused_fragment_assembly_cannot_seed_an_expired_pause_hold(cpp_model):
    stale = encode_frames(state(play_status=2, clock_advancing=False, position_ms=50000,
                                position_age_ms=0), 1, 1)
    assert len(stale) == 2
    result = probe(cpp_model, [("F", 1000, stale[0]), ("F", 6200, stale[1]), ("P", 6200)] +
                   send(encode_frames(state(play_status=2, clock_advancing=False,
                                            position_ms=90000, position_age_ms=0), 1, 2), 6500) +
                   [("P", 6750)])
    states = [entry for entry in result if isinstance(entry, dict)]
    assert states[0]["fresh"] == 1 and states[0]["position"] == UNKNOWN
    assert states[1]["position"] == 90000


def test_expired_snapshot_accepts_fragment_zero_led_far_sequence_resync(cpp_model):
    original = encode_frames(state(title="original"), 7, 10)
    far = encode_frames(state(title="after long radio loss", position_ms=1000), 7, 40000)
    assert len(far) == 2
    operations = send(original) + send(far, 2000) + [("P", 2500)]
    # A trailing fragment alone is never a resync leader, even after expiry.
    operations += send(far[1:], 8000) + [("P", 8000)]
    operations += send(far[:1], 8100) + [("P", 8100)]
    operations += send(far[1:], 8200) + [("P", 8300)]
    result = probe(cpp_model, operations)
    states = [entry for entry in result if isinstance(entry, dict)]
    assert states[0]["fresh"] == 1 and states[0]["title"] == "original"
    assert states[1]["fresh"] == states[2]["fresh"] == 0
    assert states[1]["title"] == states[2]["title"] == "original"
    assert states[3]["fresh"] == 1 and states[3]["title"] == "after long radio loss"
    assert states[3]["position"] == 1300  # First fragment remains the time anchor.
    assert sum(entry == ("A", 1) for entry in result) == 2


def test_far_resync_can_replace_an_incomplete_assembly_only_when_expired(cpp_model):
    original = encode_frames(state(title="original"), 7, 10)
    pending = encode_frames(state(title="incomplete newer snapshot"), 7, 11)
    far = encode_frames(state(title="far sequence"), 7, 40000)
    operations = send(original) + send(pending[:1], 6500)
    operations += send(far, 6800) + [("P", 6900)]
    # Still fresh: neither the committed nor the pending sequence is displaced.
    operations += send(far[:1], 7100) + [("P", 7100)]
    operations += send(far[1:], 7200) + [("P", 7250)]
    result = probe(cpp_model, operations)
    states = [entry for entry in result if isinstance(entry, dict)]
    assert states[0]["fresh"] == 1 and states[0]["title"] == "original"
    assert states[1]["fresh"] == 0 and states[1]["title"] == "original"
    assert states[2]["fresh"] == 1 and states[2]["title"] == "far sequence"
    assert sum(entry == ("A", 1) for entry in result) == 2


def test_far_resync_crc_or_payload_failure_cannot_revive_expired_snapshot(cpp_model):
    original = encode_frames(state(title="original"), 7, 10)
    far = encode_frames(state(title="far sequence"), 7, 40000)
    corrupt = bytearray(far[-1])
    corrupt[-1] ^= 1
    malformed_payload = bytearray(payload_of(far))
    malformed_payload[1] = 5  # Invalid status, even under a correct CRC.
    malformed = raw_frames(malformed_payload, session=7, seq=40001)
    operations = send(original) + send(far[:1], 8000) + [("P", 8100)]
    operations += send((bytes(corrupt),), 8200) + [("P", 8250)]
    operations += send(malformed, 8300) + [("P", 8350)]
    operations += send(far, 8400) + [("P", 8500)]
    result = probe(cpp_model, operations)
    states = [entry for entry in result if isinstance(entry, dict)]
    assert all(entry["fresh"] == 0 and entry["position"] == UNKNOWN and entry["title"] == "original"
               for entry in states[:3])
    assert states[-1]["fresh"] == 1 and states[-1]["title"] == "far sequence"
    assert sum(entry == ("A", 1) for entry in result) == 2


def test_expired_resync_still_rejects_exact_duplicates_and_retired_boot_sessions(cpp_model):
    old_boot = encode_frames(state(title="retired"), 6, 1)
    current = encode_frames(state(title="current"), 7, 10)
    retired_far = encode_frames(state(title="retired replay"), 6, 40000)
    far = encode_frames(state(title="recovered"), 7, 40000)
    operations = send(old_boot) + send(current, 1500)
    operations += send(current, 8000) + send(retired_far, 8100) + [("P", 8150)]
    operations += send(far, 8200) + [("P", 8250)]
    operations += send(far, 15000) + [("P", 15100)]
    result = probe(cpp_model, operations)
    states = [entry for entry in result if isinstance(entry, dict)]
    assert states[0]["fresh"] == 0 and states[0]["title"] == "current"
    assert states[1]["fresh"] == 1 and states[1]["title"] == "recovered"
    assert states[2]["fresh"] == 0 and states[2]["title"] == "recovered"
    assert sum(entry == ("A", 1) for entry in result) == 3


def test_recent_old_sequence_remains_rejected_after_far_resync_commit(cpp_model):
    original = encode_frames(state(title="original"), 7, 10)
    far = encode_frames(state(title="recovered"), 7, 40000)
    previous = encode_frames(state(title="older"), 7, 39999)
    next_snapshot = encode_frames(state(title="next"), 7, 40001)
    result = probe(cpp_model, send(original) + send(far, 8000) + send(previous, 8200) +
                   [("P", 8250)] + send(next_snapshot, 8300) + [("P", 8350)])
    states = [entry for entry in result if isinstance(entry, dict)]
    assert states[0]["title"] == "recovered" and states[0]["fresh"] == 1
    assert states[1]["title"] == "next" and states[1]["fresh"] == 1
    assert sum(entry == ("A", 1) for entry in result) == 3

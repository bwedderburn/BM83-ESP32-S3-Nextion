"""Ensure the production UI uses the tested model and preserves radio ownership."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "firmware/crowpanel-remote/src"


def section(source, start, end):
    return source[source.index(start):source.index(end, source.index(start))]


def test_ui_exposes_explicit_actions_and_never_falls_back_to_legacy_tokens():
    source = (CPP / "ble_host_ui.cpp").read_text()
    for caption in ('"Disconnect"', '"Connect"', '"Pair new host"', '"Rename"'):
        assert caption in source
    send = section(source, "bool send_request(", "void close_alias(")
    assert "g_control.begin(" in send and "espnow_send_host_request(" in send
    assert "g_control.not_sent()" in send
    for forbidden in ("espnow_send_token", "BLE_ENABLE", "BLE_PAUSE", "BT_EBIND",
                      "espnow_link_rescan", "WiFi.mode", "ESP.restart", "microcontroller"):
        assert forbidden not in source
    # The named native transaction model is the only operation completion path.
    assert "g_control.tick(now)" in source and not re.search(r"g_control\.result\s*=(?!=)", source)


def test_incoming_frames_and_link_invalidations_reach_the_model_in_main_task():
    source = (CPP / "main.cpp").read_text()
    receive = section(source, "while ((rx_len = espnow_link_poll(", "const uint32_t now = millis();")
    assert 'memcmp(rx_frame, "BLS2", 4)' in receive
    assert 'memcmp(rx_frame, "BHP1", 4)' in receive
    assert "ble_host_ui_accept(rx_frame, rx_len, millis())" in receive
    assert "ble_host_ui_init(rlog)" in source
    assert source.count("ble_host_ui_invalidate_link();") == source.count("g_ble_control.reset();")
    assert "!ble_host_ui_holding()" in source
    # Existing media/status health still drives the Phase 1 passive recovery.
    assert "network_setup_peer_fresh(g_now_playing.fresh(now), g_ble_control.status.fresh(now)," in source


def test_binary_policy_send_never_discovers_or_resets_radio():
    source = (CPP / "espnow_link.cpp").read_text()
    send = section(source, "bool espnow_send_host_request(", "const char *espnow_link_status_str()")
    assert 'memcmp(frame, "BHC1", 4)' in send and "length > 56" in send
    assert "ble_status::crc16" in send
    assert send.index("g_idle_sweep.postpone(millis())") < send.index("send_once(")
    for forbidden in ("discover_channel(", "espnow_link_init(", "WiFi.mode(",
                      "network_setup", "g_fail_streak", "ESP.restart"):
        assert forbidden not in send


def test_buttons_are_disabled_for_stale_unsupported_or_incoherent_host_lists():
    source = (CPP / "ble_host_ui.cpp").read_text()
    update = section(source, "void refresh(", "}  // namespace")
    assert "g_control.decoder.coherent_list(now)" in update
    assert "enabled(g_disconnect, g_control.can_manage(now));" in update
    assert "enabled(g_connect, g_control.can_connect(now));" in update
    assert "enabled(g_rename, g_control.can_alias(now));" in update
    assert "g_control.decoder.list.count < hp::MAX_PEERS" in update
    assert "g_refreshing = true;" in update and "g_refreshing = false;" in update
    name = section(source, "void peer_name(", "void status_text(")
    assert "peer->alias" in name and '"Saved host %02x%02x%02x%02x"' in name
    assert not any(guess in name for guess in ("Windows", "macOS", "iPhone", "Linux"))


def test_startup_and_recovery_only_retry_the_readonly_handshake():
    source = (CPP / "ble_host_ui.cpp").read_text()
    tick = section(source, "void ble_host_ui_tick(", "void ble_host_ui_invalidate_link(")
    assert "g_control.handshake_request(now, frame, sizeof(frame))" in tick
    assert "espnow_send_host_request(frame, length)" in tick
    assert "send_request(" not in tick and "hp::SELECT" not in tick and "hp::ENROLL" not in tick
    assert "g_control.admitted(now)" in source

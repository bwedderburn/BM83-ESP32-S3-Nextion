"""Ensure the production UI uses the tested model and preserves radio ownership."""
import ast
from pathlib import Path
import re
import string

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "firmware/crowpanel-remote/src"


def section(source, start, end):
    return source[source.index(start):source.index(end, source.index(start))]


def test_ui_exposes_explicit_actions_and_never_falls_back_to_legacy_tokens():
    source = (CPP / "ble_host_ui.cpp").read_text()
    for caption in ('"Disconnect"', '"Connect"', '"Pair new host"', '"Rename"', '"Forget"'):
        assert caption in source
    send = section(source, "bool send_request(", "void close_alias(")
    assert "g_control.begin(" in send and "espnow_send_host_request(" in send
    assert "g_control.not_sent()" in send
    for forbidden in ("espnow_send_token", "BLE_ENABLE", "BLE_PAUSE", "BT_EBIND",
                      "espnow_link_rescan", "WiFi.mode", "ESP.restart", "microcontroller"):
        assert forbidden not in source
    # The named native transaction model is the only operation completion path.
    assert "g_control.tick(now)" in source and not re.search(r"g_control\.result\s*=(?!=)", source)


def test_settings_uses_volume_hosts_without_the_disabled_legacy_bond_erase():
    source = (CPP / "main.cpp").read_text()
    assert "BT_EBIND" not in source and '"Erase BLE bonds"' not in source
    assert 'make_button(g_settings_page, "Volume hosts"' in source
    assert "lv_obj_add_event_cb(g_ble_button, cb_ble_control, LV_EVENT_CLICKED, nullptr);" in source
    opening = section(source, "static void cb_ble_control(", "static void cb_network_settings(")
    assert "ble_host_ui_show(lv_scr_act())" in opening
    assert "espnow_send_token" not in opening


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


def test_rename_keys_keep_digits_visible_in_both_letter_cases():
    source = (CPP / "ble_host_ui.cpp").read_text(encoding="utf-8")
    punctuation = set()
    for mode, letters, case_key in (("LOWER", string.ascii_lowercase, "ABC"),
                                    ("UPPER", string.ascii_uppercase, "abc")):
        layout = section(source, f"ALIAS_{mode}_KEYS[]", "};")
        keys = [ast.literal_eval(label) for label in re.findall(r'"(?:[^"\\]|\\.)*"', layout)]
        assert keys[:10] == list("1234567890")
        assert set(letters) <= set(keys)
        assert case_key in keys and "Space" in keys and "1#" not in keys
        punctuation.update(keys)
    assert set(string.punctuation) <= punctuation



def test_forget_confirmation_rechecks_the_named_selection_and_sends_only_on_confirm():
    source = (CPP / "ble_host_ui.cpp").read_text()
    opening = section(source, "void forget(", "void refresh(")
    assert "g_control.can_forget(now)" in opening
    assert "memcpy(g_forget_id, peer->id" in opening
    assert "peer->alias" in opening and "peer->id[4]" in opening and "peer->id[7]" in opening
    assert '"Confirm", 520, 162, 150, confirm_forget' in opening
    assert "send_request(" not in opening
    confirm = section(source, "void confirm_forget(", "void forget(")
    assert confirm.index("g_control.can_forget(now)") < confirm.index("send_request(hp::FORGET)")
    assert confirm.index("hp::same_id(peer->id, g_forget_id)") < confirm.index("send_request(hp::FORGET)")
    assert "enabled(g_forget, g_control.can_forget(now));" in source
    close = section(source, "void close_modal(", "void choose(")
    assert "g_forget = nullptr" in close and "g_forget_modal = g_forget_error = nullptr" in close
    for caption, x in (("Disconnect", 20), ("Pair new host", 205), ("Rename", 390), ("Forget", 575)):
        assert f'"{caption}", {x}, 210, 165,' in source


def test_forget_success_precedes_generic_paused_message_and_has_specific_refusals():
    source = (CPP / "ble_host_ui.cpp").read_text()
    status = section(source, "void status_text(", "bool send_request(")
    assert "const hp::Result result = g_control.result_for_status(now);" in status
    assert "g_control.result ==" not in status
    success = status.index("result == hp::CONFIRMED && g_control.last_opcode() == hp::FORGET")
    paused = status.index('"Disconnected. Saved pairings are kept."')
    message = status.index('"Host forgotten on this unit. Other saved hosts are kept. Remove this unit on that host, then use Pair new host."')
    assert success < message < paused
    assert 'state.request_error == 8' in status and '"Disconnect first, then Forget."' in status
    assert 'state.request_error == 9' in status and '"This audio unit\'s runtime cannot forget hosts yet."' in status

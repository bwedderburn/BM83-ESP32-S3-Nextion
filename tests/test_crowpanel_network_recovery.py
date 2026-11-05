"""Safety wiring around the executable C++ recovery-policy regression tests."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "firmware/crowpanel-remote/src/network_setup.cpp"
MAIN = ROOT / "firmware/crowpanel-remote/src/main.cpp"
LINK = ROOT / "firmware/crowpanel-remote/src/espnow_link.cpp"


def function(source, start, end):
    return source[source.index(start):source.index(end, source.index(start))]


def test_automatic_recovery_never_uses_controller_management_callback():
    source = SETUP.read_text()
    explicit = function(source, "void retry_both(", "}  // namespace")
    tick = function(source, "void network_setup_tick()", "void network_setup_show(")
    assert source.count("g_retry_callback();") == 1
    assert "g_retry_callback();" in explicit
    assert "g_retry_callback" not in tick and "note_token(" not in tick
    assert "begin_join(g_active, false, JoinOrigin::Automatic);" in tick
    # Automatic retry permission cannot select the pending enrollment profile.
    assert "begin_join(g_pending" not in tick
    assert "!g_trial" in tick and "!g_export_open" in tick


def test_only_validated_models_supply_transport_health_and_ui_stays_independent():
    main = MAIN.read_text()
    assert ("network_setup_peer_fresh(g_now_playing.fresh(now), "
            "g_ble_control.status.fresh(now),") in main
    assert "snapshot_changed || ble_changed);" in main
    ui = function(main, "static void ui_set_now_playing(", "static void build_transport_controls(")
    assert "const bool fresh = g_now_playing.fresh(now);" in ui
    assert "g_ble_control.status.fresh" not in ui
    setup = SETUP.read_text()
    health = function(setup, "void network_setup_peer_fresh(", "bool network_setup_take_rescan_request(")
    assert "g_recovery.peer(playback_fresh, status_fresh, now);" in health
    assert "g_post_hop_receipts.observe(playback_fresh || status_fresh, newly_received, now);" in health


def test_sleep_and_user_retry_do_not_rearm_automatic_attempt_budget():
    source = SETUP.read_text()
    sleep = source[source.index("bool network_setup_prepare_sleep()"):]
    assert "g_recovery.suspend();" in sleep and "g_recovery.resume(millis());" in sleep
    assert "g_recovery.enable(" not in sleep
    assert "JoinOrigin::Resume" in sleep
    explicit = function(source, "void retry_both(", "}  // namespace")
    assert "g_recovery.disable();" in explicit
    # USB refusal belongs to the controller; the automatic path never asks it.
    assert "g_retry_callback();" in explicit


def test_rearm_requires_cached_committed_identity_not_just_wifi_association():
    source = SETUP.read_text()
    identity = function(source, "bool committed_target_connected(", "void restore_channel(")
    assert "g_trial || g_applying" in identity
    assert "g_target.ssid != g_active.ssid" in identity
    assert "memcmp(g_target.bssid, g_active.bssid, 6) != 0" in identity
    assert "g_target_check.due(associated, generation, now)" in identity
    assert "g_target_check.record(target_connected(), generation, now)" in identity
    tick = function(source, "void network_setup_tick()", "void network_setup_show(")
    assert "g_recovery.connected(committed_target_connected(now), now);" in tick
    for start, end in (("void begin_join(", "void abort_trial("),
                       ("void restore_channel(", "enum class JoinOrigin")):
        assert "g_target_check.clear();" in function(source, start, end)
    assert "g_active = g_target;\n        g_target_check.clear();" in source
    sleep = source[source.index("bool network_setup_prepare_sleep()"):]
    assert sleep.count("g_target_check.clear();") == 2


def test_idle_discovery_defers_to_network_ownership_and_sends_no_commands():
    source = SETUP.read_text()
    gate = function(source, "bool network_setup_idle_discovery_allowed()", "void network_setup_peer_fresh(")
    for blocked in ("!g_suspended", "!g_network_enabled", "!g_connecting", "!g_scanning",
                    "!g_retry_pending", "!g_trial", "!g_applying", "!g_export_open",
                    "!g_export_secret_tx", "!g_export_release_pending", "!g_completion_pending",
                    "!network_setup_serial_busy()", "WiFi.status() != WL_CONNECTED"):
        assert blocked in gate
    assert "g_active.valid" in gate and "g_recovery.idle_discovery_allowed(millis())" in gate
    link = LINK.read_text()
    listen = function(link, "bool espnow_link_idle_recovery_tick(", "uint32_t espnow_link_retries()")
    assert listen.count("esp_wifi_set_channel(") == 1
    for forbidden in ("send_once(", "esp_now_send(", "delay(", "while (", "discover_channel("):
        assert forbidden not in listen
    assert "g_idle_sweep.postpone(millis())" in listen  # Cooldown starts after the failed API returns.
    assert listen.index("if (result != ESP_OK)") < listen.index("g_channel = channel;", listen.index("if (result != ESP_OK)"))
    send = function(link, "bool espnow_send_token(", "const char *espnow_link_status_str()")
    assert send.index("g_idle_sweep.postpone(millis())") < send.index("send_once(")


def test_idle_hops_follow_validated_rx_and_preserve_the_stability_hold():
    main = MAIN.read_text()
    loop = main[main.index("void loop() {"):]
    assert loop.index("while ((rx_len = espnow_link_poll(") < loop.index("espnow_link_idle_recovery_tick(")
    assert "!preparing_sleep && g_ble_control.result != ble_control::WAITING" in loop
    hop = function(loop, "if (espnow_link_idle_recovery_tick(", "static uint32_t last_playback_refresh")
    assert "g_now_playing.reset();" in hop and "g_ble_control.reset();" in hop
    assert "network_setup_note_idle_channel_change();" in hop
    source = SETUP.read_text()
    missing = function(source, "if (g_network_enabled && !g_connecting", "if (!g_network_enabled &&")
    # Trial behavior stays explicit; committed missing-peer recovery no longer
    # makes a one-shot synchronous scan its only way to discover the peer.
    assert "if (g_trial) g_rescan_requested = true;" in missing
    tick = function(source, "void network_setup_tick()", "void network_setup_show(")
    assert tick.index("g_post_hop_receipts.ready()") < tick.index("g_recovery.begin_local_join(now)")

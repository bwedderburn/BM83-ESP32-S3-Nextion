"""Safety wiring around the executable C++ recovery-policy regression tests."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "firmware/crowpanel-remote/src/network_setup.cpp"
MAIN = ROOT / "firmware/crowpanel-remote/src/main.cpp"


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
            "g_ble_control.status.fresh(now));") in main
    ui = function(main, "static void ui_set_now_playing(", "static void build_transport_controls(")
    assert "const bool fresh = g_now_playing.fresh(now);" in ui
    assert "g_ble_control.status.fresh" not in ui
    setup = SETUP.read_text()
    health = function(setup, "void network_setup_peer_fresh(", "bool network_setup_take_rescan_request(")
    assert "g_recovery.peer(playback_fresh, status_fresh, millis());" in health


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

"""A CrowPanel-style Wi-Fi remote for the BM83 Bluetooth audio unit."""

import os
import sys
import time

APP_DIR = "/system/apps/bm83_remote"
try:
    os.chdir(APP_DIR)
except OSError:
    pass
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from models import BleControl, Playback, clamp_setting_index, clock_text, display_text
from artwork import Artwork
from protocol import configuration

try:
    import secrets
except ImportError:
    secrets = None

try:
    import wifi
except ImportError:
    wifi = None

try:
    from transport import Remote
except ImportError:
    Remote = None

badge.mode(HIRES | VSYNC)
screen.font = font.nope
screen.antialias = image.X2

BG = color.rgb(13, 17, 23)
PANEL = color.rgb(26, 34, 43)
WHITE = color.rgb(238, 244, 250)
MUTED = color.rgb(148, 160, 174)
ACCENT = color.rgb(211, 250, 55)
GREEN = color.rgb(66, 211, 120)
RED = color.rgb(255, 112, 105)


def fit_text(text, width, size=1):
    while text and screen.measure_text(text, size)[0] > width:
        text = text[:-1]
    return text


def wrap_text(text, width, size=1):
    lines = []
    line = ""
    for word in text.split():
        candidate = (line + " " + word).strip()
        if line and screen.measure_text(candidate, size)[0] > width:
            lines.append(line)
            line = fit_text(word, width, size)
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


class BM83Remote:
    def __init__(self):
        self.remote = None
        self.artwork = Artwork()
        self.playback = Playback()
        self.ble = BleControl()
        self.page = "now"
        self.setting_index = 0
        self.erase_confirm = False
        self.confirm_choice = 0
        self.feedback = "Waiting for audio unit"
        self.config = self._config()
        self.config_error = self.config is None
        self.wifi_ready = False
        self.wifi_error = ""
        self.sample_mode = False
        self.next_wifi = 0
        self.last_art_key = None
        self.unit_status = "Not connected"
        self.hold_action = None
        self._start_network()

    def _config(self):
        try:
            if secrets is None:
                raise ValueError("Create badge/secrets.py with Wi-Fi and BM83 settings")
            ssid = str(getattr(secrets, "WIFI_SSID", "") or "").strip()
            if not ssid:
                raise ValueError("Set WIFI_SSID and WIFI_PASSWORD in secrets.py")
            return configuration(secrets)
        except (ValueError, TypeError) as error:
            self.config_message = str(error)
            return None

    def _start_network(self):
        if not self.config_error and Remote is not None:
            try:
                self.remote = Remote(*self.config)
                self.unit_status = "Authenticating audio unit..."
            except Exception as error:
                self.feedback = "UDP setup failed: " + str(error)[:48]
                self.unit_status = "Audio unit unavailable"

    def _wifi(self, now):
        if self.config_error or wifi is None:
            return False
        if now < self.next_wifi and self.wifi_ready:
            return True
        try:
            self.wifi_ready = bool(wifi.connect())
            if not self.wifi_ready:
                try:
                    code, text = wifi.status()
                    self.wifi_error = text or ("Wi-Fi status %d" % code)
                except Exception:
                    self.wifi_error = "Connecting to Wi-Fi..."
            else:
                self.wifi_error = ""
            self.next_wifi = now + (1000 if not self.wifi_ready else 5000)
        except Exception as error:
            self.wifi_ready = False
            self.wifi_error = str(error)[:56]
            self.next_wifi = now + 2000
        return self.wifi_ready

    def _settings(self, now):
        choices = [
            ("Power", "BT_POWER"),
            ("Pair", "BT_PAIR"),
            ("Cycle EQ", "BT_EQ"),
            ("Erase BLE bonds", "BT_EBIND"),
            ("Wi-Fi / Artwork retry", "NET_RETRY"),
        ]
        if self.ble.available(now):
            pause = self.ble.state["mode"] == 0
            choices.append(("Pause volume remote" if pause else "Enable volume remote",
                            "BLE_PAUSE" if pause else "BLE_ENABLE"))
        return choices

    def _control(self, token, now):
        if self.remote is None:
            self.feedback = "Configure Wi-Fi and BM83 secrets first"
            return
        if token in ("BLE_PAUSE", "BLE_ENABLE") and not self.ble.available(now):
            self.feedback = "Fresh BLE status required"
            return
        if not self.remote.queue_command(token):
            self.feedback = self.remote.feedback

    def input(self, now):
        if badge.released(BUTTON_UP) or badge.released(BUTTON_DOWN):
            if self.remote:
                self.remote.release_volume()
            self.hold_action = None
        if self.page == "now":
            if badge.pressed(BUTTON_MENU):
                self.page = "settings"
                return
            if badge.pressed(BUTTON_BACK):
                self._control("BT_MUTE", now)
            if badge.pressed(BUTTON_LEFT):
                self._control("BT_PREV", now)
            if badge.pressed(BUTTON_RIGHT):
                self._control("BT_NEXT", now)
            if badge.pressed(BUTTON_SELECT):
                self._control("BT_PLAY", now)
            if badge.pressed(BUTTON_DOWN):
                if self.remote:
                    self.remote.volume("BT_VOLDN")
                    self.hold_action = "down"
            if badge.pressed(BUTTON_UP):
                if self.remote:
                    self.remote.volume("BT_VOLUP")
                    self.hold_action = "up"
            return

        if badge.pressed(BUTTON_BACK) or badge.pressed(BUTTON_MENU):
            if self.erase_confirm:
                self.erase_confirm = False
            else:
                self.page = "now"
            return
        choices = self._settings(now)
        self.setting_index = clamp_setting_index(self.setting_index, len(choices))
        if self.erase_confirm:
            if badge.pressed(BUTTON_UP) or badge.pressed(BUTTON_DOWN):
                self.confirm_choice = 1 - self.confirm_choice
            if badge.pressed(BUTTON_SELECT):
                if self.confirm_choice == 1:
                    self._control("BT_EBIND", now)
                self.erase_confirm = False
            return
        if badge.pressed(BUTTON_UP):
            self.setting_index = (self.setting_index - 1) % len(choices)
        if badge.pressed(BUTTON_DOWN):
            self.setting_index = (self.setting_index + 1) % len(choices)
        if badge.pressed(BUTTON_SELECT):
            token = choices[self.setting_index][1]
            if token == "BT_EBIND":
                self.erase_confirm = True
                self.confirm_choice = 0
            elif token == "NET_RETRY":
                self._control(token, now)
                if self.remote:
                    self.remote.queue_command("STATUS")
                self.artwork.retry(now)
                self.wifi_ready = False
                self.next_wifi = now
            else:
                self._control(token, now)

    def inject_sample(self):
        sample = {
            "power_on": True, "connected": True, "aux": False,
            "clock_advancing": True, "play_status": 1, "eq_index": 2,
            "duration_ms": 238000, "position_ms": 71800, "position_age_ms": 120,
            "title": "Around the World", "artist": "Daft Punk",
            "album": "Homework", "eq": "ROCK",
        }
        now = badge.ticks
        self.playback.accept(sample, now)
        self.ble.accept({"session": 1, "sequence": 1, "mode": 0, "flags": 15,
                         "error": 0, "req_client": None, "req_seq": None}, now)
        self.sample_mode = True
        self.feedback = "Sample state (no commands sent)"
        self.artwork.set_result(sample)

    def step(self, now):
        self.input(now)
        if self.sample_mode:
            return
        if not self.config_error:
            connected = self._wifi(now)
            if connected and self.remote:
                self.remote.step(now)
                self.playback = self.remote.playback
                self.ble = self.remote.ble
                self.feedback = self.remote.feedback
                self.unit_status = ("Authenticated audio unit" if self.remote.unit
                                    else "Waiting for audio unit")
            elif not connected:
                self.unit_status = "Wi-Fi: " + (self.wifi_error or "connecting")
            state = self.playback.state if self.playback.fresh(now) else None
            if state:
                key = (state["artist"], state["album"])
                if key != self.last_art_key:
                    self.last_art_key = key
                    self.artwork.start(key[0], key[1], now)
            self.artwork.step(now, connected)

    def draw(self, now):
        screen.pen = BG
        screen.rectangle(screen.clip)
        screen.pen = WHITE
        screen.text(fit_text("BM83 Remote", 190, 2), 10, 7, 2)
        screen.pen = MUTED
        status = "SETTINGS" if self.page == "settings" else self.unit_status
        screen.text(fit_text(status, 100), 210, 13)
        screen.pen = ACCENT
        screen.line(10, 34, 310, 34)

        if self.config_error and not self.sample_mode:
            self._draw_config()
        elif self.page == "settings":
            self._draw_settings(now)
        else:
            self._draw_now(now)

    def _draw_config(self):
        screen.pen = PANEL
        screen.shape(shape.rounded_rectangle(12, 49, 296, 150, 8))
        screen.pen = ACCENT
        screen.text("Setup required", 24, 60, 2)
        screen.pen = WHITE
        lines = wrap_text(self.config_message, 270)[:3]
        for i, line in enumerate(lines[:3]):
            screen.text(line, 24, 88 + i * 15)
        screen.pen = MUTED
        screen.text("No credentials stored in this app.", 12, 174)
        screen.text("Wi-Fi and BM83_HOST, PORT, KEY are required.", 12, 191)
        screen.text("Simulator: exec inject_sample_state()", 12, 215)

    def _draw_now(self, now):
        state = self.playback.state if self.playback.fresh(now) else None
        screen.pen = PANEL
        screen.shape(shape.rounded_rectangle(12, 45, 114, 114, 7))
        if self.artwork.image:
            screen.blit(self.artwork.image, rect(14, 47, 110, 110))
        else:
            screen.pen = ACCENT
            screen.text("BM83", 43, 82, 2)
            screen.pen = MUTED
            screen.text(fit_text(self.artwork.message, 100), 18, 118)

        screen.pen = WHITE
        if state:
            title = display_text(state["title"]) or "Unknown title"
            artist = display_text(state["artist"]) or "Unknown artist"
            album = display_text(state["album"]) or "Unknown album"
            for i, line in enumerate(wrap_text(title, 170)[:2]):
                screen.text(line, 137, 51 + i * 12)
            screen.pen = ACCENT
            screen.text(fit_text(artist, 170), 137, 79)
            screen.pen = MUTED
            screen.text(fit_text(album, 170), 137, 98)
            if state["aux"]:
                playback = "AUX"
            elif not state["power_on"]:
                playback = "Power off"
            elif not state["connected"]:
                playback = "Disconnected"
            elif state["play_status"] == 1:
                playback = "Playing"
            elif state["play_status"] == 2:
                playback = "Paused"
            else:
                playback = "Playback status unknown"
            screen.pen = GREEN if state["play_status"] == 1 else MUTED
            screen.text(fit_text(playback, 170), 137, 117)
            screen.pen = MUTED
            screen.text(fit_text("EQ " + display_text(state.get("eq", "")), 170),
                        137, 136)
            pos = self.playback.position(now)
            duration = state["duration_ms"]
        else:
            screen.pen = WHITE
            screen.text(fit_text("Waiting for audio unit", 170), 137, 72)
            screen.pen = MUTED
            screen.text(fit_text("No fresh playback snapshot", 170), 137, 98)
            pos = duration = None

        screen.pen = color.rgb(60, 72, 84)
        screen.shape(shape.rounded_rectangle(14, 174, 292, 7, 3))
        if duration and pos is not None:
            width = max(0, min(292, int(292 * pos / duration)))
            if width:
                screen.pen = ACCENT
                screen.shape(shape.rounded_rectangle(14, 174, width, 7, 3))
        screen.pen = MUTED
        screen.text(clock_text(pos), 14, 187)
        screen.text(clock_text(duration), 272, 187)
        screen.pen = WHITE
        screen.text(fit_text("LEFT prev  SELECT play/pause  RIGHT next", 300), 10, 204)
        screen.text(fit_text("BACK mute  UP/DOWN volume  MENU settings", 300), 10, 216)
        screen.pen = ACCENT if "no reply" not in self.feedback.lower() else RED
        screen.text(fit_text(self.feedback, 292), 14, 228)

    def _draw_settings(self, now):
        choices = self._settings(now)
        self.setting_index = clamp_setting_index(self.setting_index, len(choices))
        screen.pen = WHITE
        screen.text("Device controls", 16, 48, 2)
        for i, (label, _) in enumerate(choices):
            y = 72 + i * 22
            screen.pen = PANEL if i == self.setting_index else BG
            screen.shape(shape.rounded_rectangle(15, y - 2, 290, 19, 3))
            screen.pen = ACCENT if i == self.setting_index else WHITE
            screen.text(fit_text(("> " if i == self.setting_index else "  ") + label,
                                 276), 22, y)
        if self.erase_confirm:
            screen.pen = color.rgb(30, 20, 20)
            screen.shape(shape.rounded_rectangle(30, 123, 260, 74, 6))
            screen.pen = RED
            screen.text("Erase BLE bonds?", 48, 134, 2)
            screen.pen = WHITE
            screen.text(("> " if not self.confirm_choice else "  ") + "Cancel", 52, 160)
            screen.text(("> " if self.confirm_choice else "  ") + "Erase", 164, 160)
        if self.ble.state and self.ble.fresh(now):
            ble = self.ble.state
            modes = ("Enabled", "Pausing", "Paused", "Error")
            summary = "Volume remote: " + modes[ble["mode"]]
            feedback = self.ble.result or "Fresh status"
        else:
            summary, feedback = "Volume remote unavailable", "Waiting for fresh BLE status"
        screen.pen = MUTED
        screen.text(fit_text(summary, 288), 16, 204)
        screen.pen = ACCENT
        screen.text(fit_text(feedback, 288), 16, 216)
        screen.pen = WHITE
        screen.text(fit_text(self.feedback, 288), 16, 228)

    def update(self):
        now = badge.ticks
        self.step(now)
        self.draw(now)


app = BM83Remote()


def inject_sample_state():
    app.inject_sample()


def update():
    app.update()


def on_exit():
    try:
        if app.remote:
            app.remote.close(badge.ticks, time.sleep_ms)
    finally:
        app.artwork.close()


run(update)

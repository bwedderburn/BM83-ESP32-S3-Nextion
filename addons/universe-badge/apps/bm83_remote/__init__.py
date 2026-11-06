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

from models import (BleControl, HID_READY_FLAGS, Playback, clamp_setting_index, clock_text,
                    display_text, elapsed, source_label)
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
LOCAL_RETRY_FEEDBACK = "Local retry: badge Wi-Fi/artwork only"
BATTERY_REFRESH_MS = 10000
MENU_ROWS = 6
VOLUME_HOST_ACTIONS = (
    ("Disconnect", "disconnect"),
    ("Select saved host", "select"),
    ("Pair new host", "enroll"),
    ("Open Windows app", "open_windows"),
)


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
        self.volume_index = 0
        self.host_id = None
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
        self.artwork_retry_pending = False
        self.unit_status = "Not connected"
        self.hold_action = None
        self.battery_read_at = None
        self.battery_percent = None
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
        if self.config_error:
            return
        if Remote is None:
            self.feedback = "Wi-Fi/UDP unavailable: no socket support"
            self.unit_status = "No UDP socket"
            return
        try:
            self.remote = Remote(*self.config)
            self.unit_status = "Authenticating"
        except Exception as error:
            self.feedback = "UDP setup failed: " + str(error)[:48]
            self.unit_status = "UDP failed"

    def _wifi(self, now):
        if self.config_error or wifi is None:
            return False
        if self.next_wifi and 0 < ((self.next_wifi - now) & 0xffffffff) < 0x80000000:
            return self.wifi_ready
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
            # Zero is the initial-attempt sentinel, never an armed deadline.
            self.next_wifi = ((now + (1000 if not self.wifi_ready else 5000)) & 0xffffffff) or 1
        except Exception as error:
            self.wifi_ready = False
            self.wifi_error = str(error)[:56]
            self.next_wifi = ((now + 2000) & 0xffffffff) or 1
        return self.wifi_ready

    def _settings(self, now):
        choices = [
            ("Power", "BT_POWER"),
            ("Pair", "BT_PAIR"),
            ("Cycle EQ", "BT_EQ"),
            ("Erase BLE bonds", "BT_EBIND"),
            ("Badge Wi-Fi / artwork retry", "LOCAL_RETRY"),
            ("Volume hosts", "VOLUME_HOSTS"),
        ]
        if self.ble.available(now):
            pause = self.ble.state["mode"] == 0
            choices.append(("Pause volume remote" if pause else "Enable volume remote",
                            "BLE_PAUSE" if pause else "BLE_ENABLE"))
        return choices

    def _control(self, command, now):
        if self.remote is None:
            self.feedback = ("Configure Wi-Fi and BM83 secrets first" if self.config_error
                             else "Wi-Fi/UDP unavailable - command not sent")
            return
        if command in ("BLE_PAUSE", "BLE_ENABLE") and not self.ble.available(now):
            self.feedback = "Fresh BLE status required"
            return
        if not self.remote.queue_command(command):
            self.feedback = self.remote.feedback

    def input(self, now):
        if ((self.hold_action == "up" and badge.released(BUTTON_UP))
                or (self.hold_action == "down" and badge.released(BUTTON_DOWN))):
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

        if self.page in ("volume", "saved_hosts"):
            self._volume_input(now)
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
            command = choices[self.setting_index][1]
            if command == "BT_EBIND":
                self.erase_confirm = True
                self.confirm_choice = 0
            elif command == "VOLUME_HOSTS":
                self.page = "volume"
                self.volume_index = 0
                if self.remote and not self.sample_mode:
                    self.remote.host_menu(True)
            elif command == "LOCAL_RETRY":
                # Badge-local only: never asks the audio unit to reconnect or reload.
                # Retry may create/decode an artwork request. Defer that work
                # until the authenticated remote has finished any transaction.
                self.artwork_retry_pending = True
                rearm_clock = getattr(self.artwork, "rearm_clock", None)
                if callable(rearm_clock):
                    rearm_clock()
                self.wifi_ready = False
                self.next_wifi = now
                self.feedback = LOCAL_RETRY_FEEDBACK
                if self.remote:
                    self.remote.feedback = LOCAL_RETRY_FEEDBACK
            else:
                self._control(command, now)

    def _host_state(self, now):
        hosts = getattr(self.remote, "hosts", None)
        if not self.sample_mode and self.wifi_ready and hosts and hosts.fresh(now):
            return hosts.state
        return None

    def _saved_hosts(self, now):
        state = self._host_state(now)
        return state["peers"] if state else None

    def _saved_index(self, peers):
        for index, peer in enumerate(peers):
            if peer["id"] == self.host_id:
                return index
        return None

    def _volume_input(self, now):
        menu = badge.pressed(BUTTON_MENU)
        if menu or badge.pressed(BUTTON_BACK):
            if self.page == "saved_hosts" and not menu:
                self.page = "volume"
            else:
                self.page = "now" if menu else "settings"
                if self.remote and not self.sample_mode:
                    self.remote.host_menu(False)
            return

        up, down = badge.pressed(BUTTON_UP), badge.pressed(BUTTON_DOWN)
        move = int(down) - int(up)
        selected = badge.pressed(BUTTON_SELECT)
        if self.page == "volume":
            self.volume_index = (self.volume_index + move) % len(VOLUME_HOST_ACTIONS)
            if selected and not move:
                command = VOLUME_HOST_ACTIONS[self.volume_index][1]
                if command == "select":
                    self.host_id = None
                    self.page = "saved_hosts"
                elif self.remote and not self.sample_mode:
                    self.remote.queue_host(command, now)
            return

        peers = self._saved_hosts(now)
        if not peers:
            return
        index = self._saved_index(peers)
        if move:
            next_index = (index + move) % len(peers) if index is not None else 0
            self.host_id = peers[next_index]["id"]
        elif selected and index is not None and not self.sample_mode:
            if self.remote.queue_host("select", now, host=self.host_id):
                self.page = "volume"

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

    def _artwork_idle(self):
        remote = self.remote
        return bool(remote and remote.unit and remote.client
                    and remote.pending is None and not remote.queue
                    and not remote.volume_queue and remote.held_volume is None
                    and not getattr(remote, "host_page", False)
                    and not getattr(getattr(remote, "hosts", None), "busy", False))

    def step(self, now):
        self.input(now)
        if self.sample_mode:
            return
        if not self.config_error:
            connected = self._wifi(now)
            if self.remote:
                # Even offline frames age pending work and discard unsent
                # presses. Releases for presses already sent remain queued.
                self.remote.step(now, connected=connected)
                if self.remote.held_volume is None:
                    self.hold_action = None
            if connected and self.remote:
                self.playback = self.remote.playback
                self.ble = self.remote.ble
                self.feedback = self.remote.feedback
                self.unit_status = "Authenticated" if self.remote.unit else "Awaiting unit"
            elif connected:
                self.unit_status = "No UDP socket" if Remote is None else "UDP failed"
            elif not connected:
                self.unit_status = "Wi-Fi offline"
                if self.remote:
                    self.feedback = "Wi-Fi: " + (self.wifi_error or "connecting")
            if not connected:
                # Offline cancellation/resume bookkeeping must still run even
                # while a UDP transaction or volume release remains pending.
                self.artwork.step(now, False)
            elif self._artwork_idle():
                state = self.playback.state if self.playback.fresh(now) else None
                if state and (state["artist"], state["album"]) != self.last_art_key:
                    key = (state["artist"], state["album"])
                    self.artwork.start(key[0], key[1], now)
                    # Read the latest album only at dispatch, and never latch
                    # a deferred lookup as if it had already started.
                    self.last_art_key = key
                    self.artwork_retry_pending = False
                elif state and self.artwork_retry_pending:
                    self.artwork.retry(now)
                    self.artwork_retry_pending = False
                else:
                    # One background operation per frame. The underlying fetch
                    # may still block in DNS or file/image work; this gate only
                    # keeps it outside in-flight UDP/control deadlines.
                    self.artwork.step(now, True)

    def _draw_battery(self, now):
        if self.battery_read_at is None or elapsed(now, self.battery_read_at) >= BATTERY_REFRESH_MS:
            self.battery_read_at = now
            try:
                percent = badge.battery_level()
            except (AttributeError, OSError, RuntimeError, ValueError, ArithmeticError):
                percent = None
            self.battery_percent = percent if type(percent) is int and 0 <= percent <= 100 else None
        percent = self.battery_percent
        if percent is None:
            return

        screen.pen = MUTED
        screen.rectangle(285, 2, 22, 9)
        screen.rectangle(307, 4, 3, 5)
        screen.pen = BG
        screen.rectangle(286, 3, 20, 7)
        if percent > 0:
            screen.pen = RED if percent <= 20 else GREEN
            screen.rectangle(287, 4, (18 * percent + 99) // 100, 5)

    def draw(self, now):
        screen.pen = BG
        screen.rectangle(screen.clip)
        screen.pen = WHITE
        screen.text(fit_text("BM83 Remote", 190, 2), 10, 7, 2)
        if self.page == "now":
            self._draw_battery(now)
        screen.pen = MUTED
        status = "SETTINGS" if self.page != "now" else self.unit_status
        screen.text(fit_text(status, 100), 210, 13)
        screen.pen = ACCENT
        screen.line(10, 34, 310, 34)

        if self.config_error and not self.sample_mode:
            self._draw_config()
        elif self.page == "settings":
            self._draw_settings(now)
        elif self.page == "volume":
            self._draw_volume(now)
        elif self.page == "saved_hosts":
            self._draw_saved_hosts(now)
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
            lines = wrap_text(self.artwork.message, 100)[:4]
            top = 118 - 12 * max(0, len(lines) - 3)
            screen.pen = ACCENT
            screen.text("BM83", 43, top - 36, 2)
            screen.pen = MUTED
            for i, line in enumerate(lines):
                screen.text(line, 18, top + i * 12)

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
            elif state["play_status"] == 0:
                playback = "Stopped"
            elif state["play_status"] in (3, 4):
                playback = "Seeking"
            else:
                playback = "Playback status unknown"
            screen.pen = GREEN if state["play_status"] == 1 else MUTED
            screen.text(fit_text(playback, 170), 137, 117)
            screen.pen = MUTED
            screen.text(fit_text("EQ " + display_text(state.get("eq", "")), 170),
                        137, 136)
            source = source_label(state)
            if source:
                screen.text(source, 137, 155)
            pos = self.playback.position(now)
            duration = state["duration_ms"]
        else:
            screen.pen = WHITE
            screen.text(fit_text("Waiting for audio unit", 170), 137, 72)
            screen.pen = MUTED
            for i, line in enumerate(wrap_text("No fresh playback snapshot", 170)[:2]):
                screen.text(line, 137, 98 + i * 12)
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

    def _draw_menu(self, title, labels, index, row_status=None):
        screen.pen = WHITE
        screen.text(fit_text(title, 288, 2), 16, 48, 2)
        start = 0 if index is None else max(0, index - MENU_ROWS + 1)
        for i in range(start, min(len(labels), start + MENU_ROWS)):
            y = 72 + (i - start) * 22
            selected = i == index
            screen.pen = PANEL if selected else BG
            screen.shape(shape.rounded_rectangle(15, y - 2, 290, 19, 3))
            screen.pen = ACCENT if selected else WHITE
            status = row_status[i] if row_status else ""
            label_width = 207 if status else 276
            screen.text(fit_text(("> " if selected else "  ") + labels[i], label_width), 22, y)
            if status:
                screen.pen = MUTED
                screen.text(status, 235, y)

    def _draw_settings(self, now):
        choices = self._settings(now)
        self.setting_index = clamp_setting_index(self.setting_index, len(choices))
        self._draw_menu("Device controls", [label for label, _ in choices], self.setting_index)
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

    def _host_name(self, identity, peers):
        for peer in peers:
            if peer["id"] == identity:
                alias = display_text(peer["alias"])
                if alias:
                    return alias
                break
        return "Saved host " + identity[-8:]

    def _draw_volume(self, now):
        self._draw_menu("Volume hosts", [label for label, _ in VOLUME_HOST_ACTIONS], self.volume_index)
        hosts = getattr(self.remote, "hosts", None)
        state = self._host_state(now)
        if not state:
            summary = "Waiting for fresh volume host status"
        elif state["state"] == "ENROLLING":
            summary = "Pairing window: %d seconds left" % state["remaining"]
        elif (state["state"] == "CONNECTED" and state["connected"]
              and state["flags"] & HID_READY_FLAGS == HID_READY_FLAGS):
            summary = "Volume host: " + self._host_name(state["connected"], state["peers"] or ())
        elif state["state"] == "CONNECTED":
            summary = "Waiting for volume link to be ready"
        elif state["state"] == "WAITING" and state["target"]:
            summary = "Waiting for " + self._host_name(state["target"], state["peers"] or ())
        else:
            summary = "Volume remote: " + state["state"].lower()

        screen.pen = MUTED
        screen.text(fit_text(summary, 288), 16, 174)
        screen.pen = ACCENT
        feedback = hosts.result if hosts else ""
        if not feedback and state and VOLUME_HOST_ACTIONS[self.volume_index][1] == "open_windows":
            ready = state["launch_ready"] and state["launch"] != "PENDING"
            feedback = "Windows launcher ready" if ready else "Windows launcher unavailable"
        for i, line in enumerate(wrap_text(feedback, 288)[:2]):
            screen.text(line, 16, 191 + i * 13)
        screen.pen = WHITE
        screen.text("SELECT choose   BACK settings", 16, 228)

    def _draw_saved_hosts(self, now):
        state = self._host_state(now)
        peers = state["peers"] if state else None
        if peers and self.host_id is None:
            self.host_id = peers[0]["id"]
        index = self._saved_index(peers or ())
        labels, statuses = [], []
        for peer in peers or ():
            labels.append(display_text(peer["alias"]) or "Saved host " + peer["id"][-8:])
            status = "Current" if peer["id"] == state["connected"] else ""
            statuses.append(status if peer["resumable"] else "Unavailable")
        self._draw_menu("Saved volume hosts", labels, index, statuses)
        if peers is None:
            feedback = "Waiting for a fresh saved-host list"
        elif not peers:
            feedback = "No saved hosts. Use Pair new host."
        elif index is None:
            feedback = "Host list changed. Use UP/DOWN."
        else:
            feedback = getattr(self.remote.hosts, "result", "")
        screen.pen = ACCENT
        screen.text(fit_text(feedback, 288), 16, 205)
        screen.pen = WHITE
        screen.text("SELECT connect   BACK volume hosts", 16, 228)

    def update(self):
        now = badge.ticks
        self.step(now)
        # Background APIs may consume real time. Do not render stale snapshots
        # as fresh merely because the frame's original tick predates that work.
        self.draw(badge.ticks)


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

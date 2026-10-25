"""Paced Now Playing snapshots using existing AVRCP observations only.

No BM83 commands are sent here. Source time is a real position sample plus
its age, so frequent radio snapshots cannot revive a stalled playback clock.
"""
import os

from utils.ticks import ticks_diff, ticks_ms
from .now_playing import UNKNOWN, encode_frames

SNAPSHOT_PERIOD_MS = 1000
FRAME_GAP_MS = 40
SNAPSHOT_DEADLINE_MS = 2000
SOURCE_TIME_MAX_AGE_MS = 5000
MOTION_STALL_MS = 500


class StatePublisher:
    """Cache source observations and send at most one small frame per tick."""

    def __init__(self, remote, clock=None, session=None, log=print):
        self._remote = remote
        self._clock = ticks_ms if clock is None else clock
        self._log = log
        self._session = int.from_bytes(os.urandom(4), "big") if session is None else session
        self._seq = 0
        self._frames = ()
        self._index = 0
        self._next_snapshot = None
        self._next_frame = None
        self._started = None
        self._transport = (False, False, False, True)
        self._eq = 0
        self._title = ""
        self._artist = ""
        self._album = ""
        self._status = None
        self._duration = None
        self._position = None
        self._position_at = None
        self._clock_advancing = False
        self._motion_position = None
        self._motion_at = None

    def _dirty(self, restart=True):
        if restart:
            self._frames = ()
        self._next_snapshot = None

    def _reset_motion(self):
        self._clock_advancing = False
        self._motion_position = self._motion_at = None

    def clear_track(self):
        """Invalidate old text and timing at a track/session boundary."""
        if (self._title or self._artist or self._album or self._status is not None
                or self._duration is not None or self._position is not None or self._clock_advancing):
            self._title = self._artist = self._album = ""
            self._status = self._duration = self._position = self._position_at = None
            self._reset_motion()
            self._dirty()

    def set_transport(self, power_on, connected, aux, suspended=False):
        """Clear unavailable sources without changing controller decisions."""
        value = (bool(power_on), bool(connected), bool(aux), bool(suspended))
        if value != self._transport:
            self._transport = value
            self._dirty()
        if not power_on or not connected or aux or suspended:
            self.clear_track()

    def set_eq(self, mode):
        if mode != self._eq:
            self._eq = mode
            self._dirty()

    def note_attributes(self, attrs):
        """Keep full display text separately from Nextion's ASCII clipping."""
        changed = False
        for attr, field in ((1, "_title"), (2, "_artist"), (3, "_album")):
            if attr in attrs:
                text = attrs[attr]
                if isinstance(text, (bytes, bytearray)):
                    text = text.decode("utf-8", "replace")
                text = str(text)[:96]
                if getattr(self, field) != text:
                    setattr(self, field, text)
                    changed = True
        if changed:
            self._dirty()

    def note_status(self, status):
        """Await a new position when the source changes playback state."""
        if status != self._status:
            self._status = status
            self._position = self._position_at = None
            self._reset_motion()
            self._dirty()

    def note_duration(self, duration_ms):
        if duration_ms is not None and duration_ms > 0 and duration_ms != self._duration:
            self._duration = duration_ms
            self._dirty(restart=False)

    def note_position(self, position_ms, duration_ms=None):
        """Observe source clock motion independently of its playback label.

        Some sources keep reporting PLAYING while paused. Only genuine
        position advances permit interpolation; radio repeats are not source
        observations. Closely spaced duplicate GPS/notification samples must
        not freeze a coarse, one-second-resolution source clock.
        """
        self.note_duration(duration_ms)
        now = self._clock()
        was_advancing = self._clock_advancing
        restart = False
        if position_ms is not None and not 0 <= position_ms < UNKNOWN:
            position_ms = None
        if position_ms is None or self._status != 1:
            self._reset_motion()
            restart = position_ms is None
        else:
            elapsed = ticks_diff(now, self._motion_at) if self._motion_at is not None else None
            if self._motion_position is None or elapsed is None or elapsed < 0 or elapsed > SOURCE_TIME_MAX_AGE_MS:
                self._clock_advancing = False
                self._motion_position, self._motion_at = position_ms, now
            elif position_ms > self._motion_position:
                self._clock_advancing = True
                self._motion_position, self._motion_at = position_ms, now
            elif position_ms < self._motion_position:
                self._clock_advancing = False
                self._motion_position, self._motion_at = position_ms, now
                restart = True
            elif elapsed >= MOTION_STALL_MS:
                self._clock_advancing = False
        self._position = position_ms
        self._position_at = now if position_ms is not None else None
        # Let an atomic snapshot finish even when source timing arrives more
        # often than slow radio callbacks. Stop predictions promptly when
        # genuine samples establish that the source clock has frozen.
        self._dirty(restart=restart or (was_advancing and not self._clock_advancing))

    def snapshot(self, now=None):
        """Return source data, retaining the original timing sample's age."""
        now = self._clock() if now is None else now
        power, connected, aux, suspended = self._transport
        active = power and connected and not aux and not suspended
        # Unknown duration + zero position is what unsupported Mac sources
        # return. Do not animate a convincing but invented clock from that.
        valid_time = self._duration is not None or (self._position is not None and self._position > 0)
        position = self._position if active and valid_time else None
        age = None
        if position is not None and self._position_at is not None:
            age = ticks_diff(now, self._position_at)
            if age < 0 or age > SOURCE_TIME_MAX_AGE_MS:
                # Latch expiry so a stalled source cannot become fresh again
                # when the device tick counter eventually wraps.
                self._position = self._position_at = position = age = None
                self._reset_motion()
        return {
            "power_on": power, "connected": connected and not suspended, "aux": aux,
            "play_status": self._status if active else None, "eq_index": self._eq,
            "duration_ms": self._duration if active else None,
            "position_ms": position, "position_age_ms": age,
            "clock_advancing": bool(active and position is not None and self._status == 1 and self._clock_advancing),
            "title": self._title if active else "", "artist": self._artist if active else "",
            "album": self._album if active else "",
        }

    def tick(self):
        """Pace complete periodic snapshots; failures leave controls running."""
        if not self._remote.state_tx_enabled:
            return
        now = self._clock()
        if self._frames and ticks_diff(now, self._started) >= SNAPSHOT_DEADLINE_MS:
            self._frames = ()
            self._next_snapshot = now
        if not self._remote.state_tx_ready():
            return
        if self._next_frame is not None and ticks_diff(now, self._next_frame) < 0:
            return
        if not self._frames:
            if self._next_snapshot is not None and ticks_diff(now, self._next_snapshot) < 0:
                return
            try:
                self._seq = (self._seq + 1) & 0xFFFF
                self._frames = encode_frames(self.snapshot(now), self._session, self._seq)
            except Exception as e:
                self._next_snapshot = (now + SNAPSHOT_PERIOD_MS) % (1 << 29)
                self._log("[REMOTE] snapshot encoding failed: %r" % (e,))
                return
            self._index = 0
            self._started = now
        frame = self._frames[self._index]
        if self._remote.send_state_frame(frame):
            self._index += 1
            if self._index == len(self._frames):
                self._frames = ()
                self._next_snapshot = (now + SNAPSHOT_PERIOD_MS) % (1 << 29)
        else:
            self._frames = ()
            self._next_snapshot = (now + SNAPSHOT_PERIOD_MS) % (1 << 29)
        self._next_frame = (now + FRAME_GAP_MS) % (1 << 29)

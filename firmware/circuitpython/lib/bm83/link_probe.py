"""One read-only boot reconciliation for an already streaming BM83.

An MCU reload can miss the module's original profile-establishment events.
Read_Link_Status (AudioUARTCommandSet v2.09 pp.32, 189-190) has no
preconditions. Its exact seven-byte reply authorizes a single GetPlayStatus
query only when database 0 already reports AVRCP. No reply here establishes
power or link state: the normal AVRCP evidence path remains authoritative.
"""
import time

START_DELAY_S = 2.5
REPLY_TIMEOUT_S = 5.0
READ_LINK_STATUS = 0x0D
LINK_STATUS_REPLY = 0x1E
AVRCP_CONNECTED = 0x04


class StartupLinkProbe:
    """Send at most two status queries without issuing playback controls."""

    def __init__(self, bm, enabled=False, clock=None, log=print):
        self._bm = bm
        self._enabled = bool(enabled)
        self._clock = time.monotonic if clock is None else clock
        self._log = log
        self._created = self._clock()
        self._attempted = False
        self._pending_until = None

    def _eligible(self):
        bm = self._bm
        return (not bm.power_on and not bm.connected and not bm._explicit_off
                and bm._power_state is None and not bm._power_confirm_deadline)

    def tick(self, now=None):
        """Make one delayed attempt; never retry after a timeout or refusal."""
        if not self._enabled:
            return False
        now = self._clock() if now is None else now
        if self._pending_until is not None:
            if now >= self._pending_until or not self._eligible():
                self._pending_until = None
            return False
        if self._attempted or now - self._created < START_DELAY_S:
            return False
        self._attempted = True
        if not self._eligible():
            return False
        self._pending_until = now + REPLY_TIMEOUT_S
        self._bm.send(READ_LINK_STATUS, b"\x00")
        self._log("[BTM] startup link-status probe")
        return True

    def note_event(self, op, params, now=None):
        """Consume only the requested status reply; retain all power guards."""
        if self._pending_until is None:
            return False
        now = self._clock() if now is None else now
        if now >= self._pending_until or not self._eligible():
            self._pending_until = None
            return False
        if op != LINK_STATUS_REPLY or len(params) != 7:
            return False
        self._pending_until = None
        # Reply fields: device state, db0/db1 profile flags, db0/db1 playback,
        # db0/db1 streaming. Bit 2 of the database flags means AVRCP is up.
        # A reported soft-off state must not authorize a contradictory flag.
        if params[0] == 0 or not params[1] & AVRCP_CONNECTED:
            return False
        self._bm.avrcp_get_play_status(0)
        self._log("[BTM] existing AVRCP session -> query play status")
        return True

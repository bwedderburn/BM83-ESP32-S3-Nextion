import time
import gc
from utils.common import dprint, _sanitize_text

# endregion
TERM = b"\xFF\xFF\xFF"

# EQ mapping for test compatibility
EQ_MAP = {
    b"EQ_OFF": 0,
    b"EQ_SOFT": 1,
    b"EQ_BASS": 2,
    b"EQ_TREBLE": 3,
    b"EQ_CLASSICAL": 4,
    b"EQ_ROCK": 5,
    b"EQ_JAZZ": 6,
    b"EQ_POP": 7,
    b"EQ_DANCE": 8,
    b"EQ_RNB": 9,
    b"EQ_USER": 11  # Aligned with BM83 EQ_SEQ and EQ_L
}

# Token sets for test compatibility
TOK_BT = {
    b"BT_POWER", b"BT_POWEROFF", b"BT_PAIR", b"BT_PLAY", b"BT_PREV",
    b"BT_NEXT", b"BT_EQ", b"BT_VOLUP", b"BT_VOLDN", b"BT_EBIND",
    # Press/release tokens for hold-and-repeat volume controls
    b"BT_VOLUP_P", b"BT_VOLUP_R", b"BT_VOLDN_P", b"BT_VOLDN_R"
}
TOK_EQ = set(EQ_MAP.keys())  # Populated from EQ_MAP keys

TOKENS = TOK_BT | TOK_EQ  # Combined token set

# endregion


def ascii_upper_uscore(token):
    if not token:
        return False
    for b in token:
        # Allow: A-Z (65-90), 0-9 (48-57), _ (95), space (32)
        if not (48 <= b <= 57 or 65 <= b <= 90 or b == 95 or b == 32):
            return False
    return True


EQ_OBJ_PAGE0 = "tEQ0"
EQ_OBJ_PAGE1 = "tEQ1"
AUX_OBJ_PAGE1 = "tAUX1"

# endregion
NX_RUNTIME = {
    "title": "tTitle", "artist": "tArtist", "album": "tAlbum", "genre": "tGenre",
    "time_cur": "tTIME_CUR", "time": "tTime", "track_num": "tTrack_num",
    "total_tracks": "tTotalTracks"
}

# endregion
# Class: Nextion - Represents the Nextion class.
class Nextion:
# region Nextion
# Nextion class encapsulates functionality related to nextion. #
    __slots__ = (
        "uart",
        "_rx",
        "current_page",
        "_last_sendme_at",
        "_sendme_period_s",
        "_txq",
        "_tx_head",
        "_last_tx_at",
        "_tx_interval_s",
        "_max_queue_size",
        "_last_token_at",
        "_token_throttle_s",
        "_last_token",
        "_telemetry_enabled",
        "_rx_hwm",
        "_txq_hwm",
        "_token_burst_hwm",
        "_read_samples",
        "_mem_free_low",
    )
    # Loop through items
# Function: __init__ - Defines the behavior for `__init__`.
    def __init__(self, uart=None):
# region __init__
    # __init__ handles   init   logic. #
        self.uart = uart
        self._rx = bytearray()

# endregion
        self.current_page = None
        self._last_sendme_at = 0.0
        self._sendme_period_s = 0.5

# endregion
        self._txq = []
        self._tx_head = 0
        self._last_tx_at = 0.0
        self._tx_interval_s = 0.04
        self._max_queue_size = 36  # Tuned from stress telemetry: queue peak stayed <=22

# endregion
        self._last_token_at = -1.0  # Initialize to past to allow first token
        self._token_throttle_s = 0.12  # Tuned from stress telemetry: filters bounce, preserves fast taps
        self._last_token = None  # Track last token value for smarter throttling
        self._telemetry_enabled = False
        self._rx_hwm = 0
        self._txq_hwm = 0
        self._token_burst_hwm = 0
        self._read_samples = 0
        self._mem_free_low = None

    def enable_telemetry(self, enabled=True):
        self._telemetry_enabled = bool(enabled)

    def telemetry_snapshot(self):
        return {
            "rx_hwm": self._rx_hwm,
            "txq_hwm": self._txq_hwm,
            "queue_cap": self._max_queue_size,
            "token_burst_hwm": self._token_burst_hwm,
            "read_samples": self._read_samples,
            "mem_free_low": self._mem_free_low,
        }

    def _telemetry_touch(self):
        if not self._telemetry_enabled:
            return
        free = None
        try:
            free = gc.mem_free()
        except Exception:
            free = None
        if free is not None and (self._mem_free_low is None or free < self._mem_free_low):
            self._mem_free_low = free

# endregion

    # Properties for test compatibility
    @property
    def rx_buffer(self):
        return self._rx

    @property
    def tx_queue(self):
        return self._txq[self._tx_head:]

    def send_cmd(self, cmd):
        self.enqueue(cmd)

# endregion
    # Loop through items
# Function: boot_sync - Defines the behavior for `boot_sync`.
    def boot_sync(self, delay_s=0.8):
# region boot_sync
    # boot_sync handles boot sync logic. #
        time.sleep(delay_s)
        self._rx = bytearray()
        self._txq.clear()
        self._tx_head = 0
        self.current_page = None
        self._last_sendme_at = 0.0
        self._last_tx_at = 0.0
        self.enqueue("bkcmd=3")
        self.enqueue("sendme")

# endregion
    # Loop through items
# Function: enqueue - Defines the behavior for `enqueue`.
    def enqueue(self, cmd):
# region enqueue
    # enqueue handles enqueue logic. #
        active_len = len(self._txq) - self._tx_head
        if active_len >= self._max_queue_size:
            # Truncate command for readability in debug logs (30 chars is enough to identify command type)
            dprint("[NX] queue full, dropping:", cmd[:30])
            return
        self._txq.append(cmd)
        if self._telemetry_enabled and active_len + 1 > self._txq_hwm:
            self._txq_hwm = active_len + 1

# endregion
    # Loop through items
# Function: sendme_tick - Defines the behavior for `sendme_tick`.
    def sendme_tick(self):
# region sendme_tick
    # sendme_tick handles sendme tick logic. #
        now = time.monotonic()
    # Conditional check
        if (now - self._last_sendme_at) >= self._sendme_period_s:
            self._last_sendme_at = now
            self.enqueue("sendme")

# endregion
    # Loop through items
# Function: tick - Defines the behavior for `tick`.
    def tick(self):
# region tick
    # tick handles tick logic. #
        self.sendme_tick()
        now = time.monotonic()
    # Conditional check
        if (len(self._txq) - self._tx_head) <= 0 or (now - self._last_tx_at) < self._tx_interval_s:
            return
        cmd = self._txq[self._tx_head]
        self._tx_head += 1
        # Compact the queue periodically to avoid unbounded growth of consumed items
        if self._tx_head >= 16 and self._tx_head >= (len(self._txq) // 2):
            del self._txq[:self._tx_head]
            self._tx_head = 0
    # Try block to catch exceptions
        try:
            self.uart.write(cmd.encode("ascii", "replace") + TERM)
            self._last_tx_at = now
    # Handle exceptions
        except Exception as e:
            dprint("[NX] write err:", e)

# endregion
    # Loop through items
# Function: _read_more - Defines the behavior for `_read_more`.
    def _read_more(self):
# region _read_more
    # _read_more handles  read more logic. #
    # Try block to catch exceptions
        try:
            n = getattr(self.uart, "in_waiting", 0) or 0
            chunk = self.uart.read(min(256, n)) if n else None
    # Handle exceptions
        except Exception as e:
            dprint("[NX] read err:", e)
            return
    # Conditional check
        if chunk:
            self._rx.extend(chunk)
            if self._telemetry_enabled and len(self._rx) > self._rx_hwm:
                self._rx_hwm = len(self._rx)

# endregion
    # Loop through items
# Function: _pop_frame - Defines the behavior for `_pop_frame`.
    def _pop_frame(self):
# region _pop_frame
    # _pop_frame handles  pop frame logic. #
        i = self._rx.find(TERM)
    # Conditional check
        if i < 0:
    # Return the result
            return None
# endregion
        frame = bytes(self._rx[:i])
        self._rx = self._rx[i + 3:]
    # Return the result
        return frame
# endregion

# endregion
    @staticmethod
    # Loop through items
# Function: _extract_token - Extract clean token from frame by removing noise
    def _extract_token(frame):
# region _extract_token
    # _extract_token handles token extraction logic. #
        f = frame.strip()
        if not f:
            return None

        # Remove leading and trailing non-token bytes (filter noise)
        # Valid token bytes: A-Z (65-90), 0-9 (48-57), _ (95)
        start = 0
        while start < len(f) and not (48 <= f[start] <= 57 or 65 <= f[start] <= 90 or f[start] == 95):
            start += 1

        end = len(f)
        while end > start and not (48 <= f[end - 1] <= 57 or 65 <= f[end - 1] <= 90 or f[end - 1] == 95):
            end -= 1

        return f[start:end] if start < end else None
# endregion

# endregion
    @staticmethod
    # Loop through items
# Function: _is_token_frame - Defines the behavior for `_is_token_frame`.
    def _is_token_frame(frame):
# region _is_token_frame
    # _is_token_frame handles  is token frame logic. #
        # Extract clean token
        f = Nextion._extract_token(frame)
        # Conditional check
        if not f:
            return None
# endregion
    # Loop through items
        for b in f:
    # Conditional check
            if 48 <= b <= 57 or 65 <= b <= 90 or b == 95:
                continue
    # Return the result
            return None
# endregion
        # Return the cleaned token if it's recognized
        return f if f in TOKENS else None
# endregion

# endregion
    # Loop through items
# Function: read - Defines the behavior for `read`.
    def read(self, max_tokens=6):
# region read
    # read handles read logic. #
        tokens = []
        page_changed = False
        self._read_more()
    # While loop execution
        while True:
            frame = self._pop_frame()
    # Conditional check
            if frame is None:
                break
    # Conditional check
            if len(frame) >= 2 and frame[0] == 0x66:
                pageid = frame[1]
    # Conditional check
                if self.current_page != pageid:
                    self.current_page = pageid
                    page_changed = True
                continue
    # Conditional check
            clean_token = self._is_token_frame(frame)
            if clean_token:
                now = time.monotonic()
                # Throttle only duplicate tokens within the window; allow different tokens
                if (now - self._last_token_at) < self._token_throttle_s and clean_token == self._last_token:
                    continue  # Discard duplicate within throttle window
                self._last_token_at = now
                self._last_token = clean_token
                tokens.append(clean_token)
    # Conditional check
                if len(tokens) >= max_tokens:
                    break
        if self._telemetry_enabled:
            burst = len(tokens)
            self._read_samples += 1
            if burst > self._token_burst_hwm:
                self._token_burst_hwm = burst
            self._telemetry_touch()
    # Return the result
        return tokens, page_changed
# endregion

# endregion
    # Loop through items
# Function: process_bytes - Process raw bytes from UART and call handler for tokens
    def process_bytes(self, data, token_handler=None):
# region process_bytes
    # process_bytes handles byte processing logic for test compatibility. #
        if not data:
            return

        # Add data to buffer
        self._rx.extend(data)

        # Extract and process tokens
        while True:
            frame = self._pop_frame()
            if frame is None:
                break

            # Check if it's a valid token and get cleaned token
            clean_token = self._is_token_frame(frame)
            if clean_token and token_handler:
                token_handler(clean_token)
# endregion

# endregion
    # Loop through items
# Function: set_text_active_page - Defines the behavior for `set_text_active_page`.
    def set_text_active_page(self, obj, txt):
# region set_text_active_page
    # set_text_active_page handles set text active page logic. #
        safe = _sanitize_text(txt)
        self.enqueue('%s.txt="%s"' % (obj, safe))

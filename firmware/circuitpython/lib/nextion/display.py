import time
from utils.common import dprint, _sanitize_text

TERM = b"\xFF\xFF\xFF"

# RX buffer cap. Valid Nextion frames are tiny (<32 bytes), so the buffer
# only grows past this when the line is feeding TERM-less garbage (display
# disconnected, floating RX pin, wrong baud). Without a cap that garbage
# accumulates forever (~960 B/s at 9600 baud) and eventually starves the
# CircuitPython heap. Keep a tail on trim so a legitimate partial frame
# that straddles the cut can still resync on its terminator.
_RX_MAX = 512
_RX_KEEP = 128

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
    b"BT_NEXT", b"BT_EQ", b"BT_VOLUP", b"BT_VOLDN",
    # Retain documented Erase Bonds token for HMI/docs compatibility.
    b"BT_EBIND",
    # Press/release tokens for hold-and-repeat volume controls
    b"BT_VOLUP_P", b"BT_VOLUP_R", b"BT_VOLDN_P", b"BT_VOLDN_R"
}
TOK_EQ = set(EQ_MAP.keys())  # Populated from EQ_MAP keys

TOKENS = TOK_BT | TOK_EQ  # Combined token set

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
AUX_OBJ_PAGE0 = "tAUX0"
AUX_OBJ_PAGE1 = "tAUX1"

NX_RUNTIME = {
    "title": "tTitle", "artist": "tArtist", "album": "tAlbum", "genre": "tGenre",
    "time_cur": "tTIME_CUR", "time": "tTime", "track_num": "tTrack_num",
    "total_tracks": "tTotalTracks"
}

class Nextion:
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
    )
    def __init__(self, uart=None):
        self.uart = uart
        self._rx = bytearray()

        self.current_page = None
        self._last_sendme_at = 0.0
        self._sendme_period_s = 0.5

        self._txq = []
        self._tx_head = 0
        self._last_tx_at = 0.0
        self._tx_interval_s = 0.035
        self._max_queue_size = 50  # Prevent unbounded growth

        self._last_token_at = -1.0  # Initialize to past to allow first token
        self._token_throttle_s = 0.15  # Duplicate tokens within this window are dropped
        self._last_token = None  # Track last token value for smarter throttling

    # Properties for test compatibility
    @property
    def rx_buffer(self):
        return self._rx

    @property
    def tx_queue(self):
        return self._txq[self._tx_head:]

    def send_cmd(self, cmd):
        self.enqueue(cmd)

    def boot_sync(self, delay_s=0.8):
        time.sleep(delay_s)
        self._rx = bytearray()
        self._txq.clear()
        self._tx_head = 0
        self.current_page = None
        self._last_sendme_at = 0.0
        self._last_tx_at = 0.0
        self.enqueue("bkcmd=3")
        self.enqueue("sendme")

    def enqueue(self, cmd):
        active_len = len(self._txq) - self._tx_head
        if active_len >= self._max_queue_size:
            # Truncate command for readability in debug logs (30 chars is enough to identify command type)
            dprint("[NX] queue full, dropping:", cmd[:30])
            return
        self._txq.append(cmd)

    def sendme_tick(self):
        now = time.monotonic()
        if (now - self._last_sendme_at) >= self._sendme_period_s:
            self._last_sendme_at = now
            self.enqueue("sendme")

    def tick(self):
        self.sendme_tick()
        now = time.monotonic()
        if (len(self._txq) - self._tx_head) <= 0 or (now - self._last_tx_at) < self._tx_interval_s:
            return
        cmd = self._txq[self._tx_head]
        self._tx_head += 1
        # Compact the queue periodically to avoid unbounded growth of consumed items
        if self._tx_head >= 16 and self._tx_head >= (len(self._txq) // 2):
            del self._txq[:self._tx_head]
            self._tx_head = 0
        try:
            self.uart.write(cmd.encode("ascii", "replace") + TERM)
            self._last_tx_at = now
        except Exception as e:
            dprint("[NX] write err:", e)

    def _read_more(self):
        try:
            n = getattr(self.uart, "in_waiting", 0) or 0
            chunk = self.uart.read(min(256, n)) if n else None
        except Exception as e:
            dprint("[NX] read err:", e)
            return
        if chunk:
            self._rx.extend(chunk)
            if len(self._rx) > _RX_MAX:
                dprint("[NX] rx overflow, trimming to", _RX_KEEP)
                self._rx = self._rx[-_RX_KEEP:]

    def _pop_frame(self):
        i = self._rx.find(TERM)
        if i < 0:
            return None
        frame = bytes(self._rx[:i])
        # CircuitPython bytearray doesn't support slice deletion — reassign.
        self._rx = self._rx[i + 3:]
        return frame

    @staticmethod
    def _extract_token(frame):
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

    @staticmethod
    def _is_token_frame(frame):
        # Extract clean token
        f = Nextion._extract_token(frame)
        if not f:
            return None
        for b in f:
            if 48 <= b <= 57 or 65 <= b <= 90 or b == 95:
                continue
            return None
        # Return the cleaned token if it's recognized
        return f if f in TOKENS else None

    def read(self, max_tokens=6):
        tokens = []
        page_changed = False
        self._read_more()
        while True:
            frame = self._pop_frame()
            if frame is None:
                break
            if len(frame) >= 2 and frame[0] == 0x66:
                pageid = frame[1]
                if self.current_page != pageid:
                    self.current_page = pageid
                    page_changed = True
                continue
            clean_token = self._is_token_frame(frame)
            if clean_token:
                now = time.monotonic()
                # Throttle only duplicate tokens within the window; allow different tokens
                if (now - self._last_token_at) < self._token_throttle_s and clean_token == self._last_token:
                    continue  # Discard duplicate within throttle window
                self._last_token_at = now
                self._last_token = clean_token
                tokens.append(clean_token)
                if len(tokens) >= max_tokens:
                    break
        return tokens, page_changed

    def process_bytes(self, data, token_handler=None):
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

    def set_text_active_page(self, obj, txt):
        safe = _sanitize_text(txt)
        self.enqueue('%s.txt="%s"' % (obj, safe))

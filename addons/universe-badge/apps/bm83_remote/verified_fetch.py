"""Certificate-required artwork transport; the frozen fetch parser stays intact.

_connect is adapted from Pimoroni's MIT-licensed AsyncFetch at commit
 ee84772fb7f7d5424e9593029caba815c6f89c80 (2026 Pimoroni Ltd).
See artwork_trust/LICENSE-Pimoroni-MIT.txt and artwork_trust/README.md.
No code path calls AsyncFetch's unauthenticated _connect implementation.
"""

import errno
import time

try:
    import fetch
    import socket
    import tls
except ImportError:
    fetch = socket = tls = None

try:
    import ntptime
except ImportError:
    ntptime = None

APP_TRUST = "/system/apps/bm83_remote/artwork_trust"
CA_COUNT = 118
MAX_CA_BYTES = 8192
MIN_TLS_YEAR = 2026
MAX_TLS_YEAR = 2099
HOSTS = ("musicbrainz.org", "coverartarchive.org", "api.deezer.com",
         "cdn-images.dzcdn.net", "archive.org")
_Context = None
_Base = getattr(fetch, "AsyncFetch", object)


def clock_ready():
    try:
        year = time.gmtime()[0]
        return MIN_TLS_YEAR <= year <= MAX_TLS_YEAR
    except (AttributeError, TypeError, ValueError, OverflowError, OSError):
        return False


def _require_clock():
    if not clock_ready():
        raise ValueError("Artwork needs a valid UTC clock")


class ClockRecovery:
    """At most three existing NTP calls, serviced only by the app's idle gate."""
    def __init__(self):
        self.rearm()

    def rearm(self):
        # Pure bookkeeping; this is safe while a UDP command is outstanding.
        self.attempts = 0
        self.next_at = None
        self.message = "Artwork needs a valid UTC clock"

    def step(self, now):
        if clock_ready():
            self.message = ""
            return True
        if self.attempts >= 3:
            return False
        if (self.next_at is not None
                and ((now - self.next_at) & 0xffffffff) >= 0x80000000):
            return False
        timeout = getattr(ntptime, "timeout", None)
        if (not callable(getattr(ntptime, "settime", None))
                or not isinstance(timeout, (int, float))
                or isinstance(timeout, bool) or not 0 < timeout <= 1):
            self.attempts = 3
            self.message = "Artwork needs clock sync support"
            return False
        self.attempts += 1
        delay = 5000 if self.attempts == 1 else 30000
        self.next_at = (now + delay) & 0xffffffff
        try:
            ntptime.settime()
        except Exception:
            self.message = "Artwork needs UTC clock; sync failed"
        else:
            self.message = ("Clock ready; artwork waiting" if clock_ready()
                            else "Artwork needs a valid UTC clock")
        # An NTP attempt owns this whole background turn, even if successful.
        return False


def _load_ca(context):
    # The badge's native API is positional DER-only. Each load MUST append to
    # this one context's CA chain; physical positive/negative tests are a release
    # gate. Loading the concatenated store as one DER would silently lose roots.
    with open(APP_TRUST + "/roots.der-store", "rb") as source:
        if source.read(7) != b"BMCA1\x00\x76":
            raise ValueError("Artwork CA bundle rejected")
        for _ in range(CA_COUNT):
            size = source.read(2)
            if len(size) != 2:
                raise ValueError("Artwork CA bundle truncated")
            size = (size[0] << 8) | size[1]
            if not 64 <= size <= MAX_CA_BYTES:
                raise ValueError("Artwork CA certificate too large")
            der = source.read(size)
            if len(der) != size or der[0] != 0x30:
                raise ValueError("Artwork CA bundle truncated")
            context.load_verify_locations(der)
        if source.read(1):
            raise ValueError("Artwork CA bundle trailer rejected")


def _context():
    global _Context
    _require_clock()
    required = getattr(tls, "CERT_REQUIRED", None)
    if required is None or not callable(getattr(tls, "SSLContext", None)):
        raise ValueError("Artwork needs verified TLS support")
    if _Context is not None:
        if _Context.verify_mode != required:
            raise ValueError("Artwork TLS verification disabled")
        return _Context
    protocol = getattr(tls, "PROTOCOL_TLS_CLIENT", None)
    if protocol is None:
        raise ValueError("Artwork needs verified TLS support")
    context = tls.SSLContext(protocol)
    if not all(callable(getattr(context, name, None))
               for name in ("load_verify_locations", "wrap_socket")):
        raise ValueError("Artwork needs verified TLS support")
    context.verify_mode = required
    if context.verify_mode != required:
        raise ValueError("Artwork TLS verification disabled")
    _load_ca(context)
    # Keep one context only after a complete, successful trust-store load.
    _Context = context
    return context


def release_context():
    """Drop the app-owned cache on exit, after its active request is cancelled."""
    global _Context
    _Context = None


def _allowed_host(host):
    return (isinstance(host, str) and host == host.lower()
            and (host in HOSTS or host.endswith(".archive.org"))
            and all("a" <= char <= "z" or "0" <= char <= "9" or char in ".-"
                    for char in host))


class VerifiedFetch(_Base):
    def fetch(self, *args, **kwargs):
        _require_clock()
        return super().fetch(*args, **kwargs)

    def update(self):
        try:
            _require_clock()
            return super().update()
        except Exception:
            self.reset()
            raise

    def _connect(self):
        # Verify support, trust anchors and clock BEFORE even resolving a host.
        context = _context()
        self._phase = "dns"
        if self._addr_info is None:
            self._addr_info = socket.getaddrinfo(
                self._host, self._port, 0, socket.SOCK_STREAM)[0]
        sock_family, sock_type, sock_proto, _, sock_addr = self._addr_info
        sock = None
        try:
            sock = socket.socket(sock_family, sock_type, sock_proto)
            sock.setblocking(False)
            self._phase = "connect"
            try:
                sock.connect(sock_addr)
            except OSError as error:
                code = getattr(error, "errno", None)
                if code is None and error.args:
                    code = error.args[0]
                if code != errno.EINPROGRESS:
                    raise
            # The certificate-required context validates the requested hostname;
            # the parser's first nonblocking write advances the TLS handshake.
            wrapped = context.wrap_socket(
                sock, server_hostname=self._host, do_handshake_on_connect=False)
            if wrapped is None:
                raise ValueError("Artwork TLS socket unavailable")
            sock = wrapped
            sock.setblocking(False)
        except Exception:
            if sock is not None:
                sock.close()
            self._addr_info = None
            raise
        self._sock = sock
        yield


def create(host, use_tls, max_bytes, timeout):
    """Factory seam used by artwork; never instantiate the insecure base class."""
    if (_Base is object or not _allowed_host(host) or use_tls is not True
            or not isinstance(max_bytes, int) or isinstance(max_bytes, bool)
            or not 0 < max_bytes <= 131072 or not 0 < timeout <= 10
            or not all(callable(getattr(_Base, name, None))
                       for name in ("fetch", "update", "reset"))):
        raise ValueError("verified bounded fetch support required")
    _context()
    return VerifiedFetch(host, use_tls=True, max_bytes=max_bytes, timeout=timeout)

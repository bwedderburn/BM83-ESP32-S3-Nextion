#!/usr/bin/env python3
"""Read macOS Now Playing metadata and send a bounded LAN-only UDP snapshot.

The bridge never controls playback. A CoreAudio default-output check prevents
Mac speaker playback from replacing metadata from a phone using the BM83.
"""
import argparse
import errno
import ipaddress
import json
import math
import os
from pathlib import Path
import secrets
import signal
import socket
import stat
# Fixed local compiler/reader argv; no shell or network-supplied commands.
import subprocess  # nosec B404
import sys
import time

MAX_PACKET_BYTES = 1400
MAX_TEXT_BYTES = 256
MAX_MILLISECONDS = 2147483647
DEFAULT_PORT = 8766
DEFAULT_INTERVAL = 2.0
BASE = Path(__file__).resolve().parent


class BridgeError(ValueError):
    """A safe-to-display configuration or snapshot error."""


def load_config(path):
    """Read a private, user-owned profile without exposing its token in errors."""
    try:
        fd = os.open(os.fspath(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as profile:
            info = os.fstat(profile.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise BridgeError("Bridge profile must be user-owned and private (chmod 600).")
            text = profile.read(4097)
        if len(text) > 4096:
            raise BridgeError("Bridge profile is too large.")
        data = json.loads(text)
    except BridgeError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise BridgeError("Cannot read bridge profile; check its path, permissions and JSON.") from None
    if not isinstance(data, dict):
        raise BridgeError("Bridge profile must be a JSON object.")
    if not isinstance(data.get("host"), str):
        raise BridgeError("Bridge host must be the receiver's IPv4 address.")
    try:
        address = ipaddress.ip_address(data["host"])
    except ValueError:
        raise BridgeError("Bridge host must be the receiver's IPv4 address.") from None
    if address.version != 4 or address.is_multicast or address.is_unspecified or str(address) == "255.255.255.255":
        raise BridgeError("Bridge host must be a unicast IPv4 address.")
    port = data.get("port", DEFAULT_PORT)
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        raise BridgeError("Bridge port must be between 1024 and 65535.")
    token = data.get("token")
    if (not isinstance(token, str) or not 32 <= len(token) <= 128
            or any(character not in "0123456789abcdefABCDEF" for character in token)):
        raise BridgeError("Bridge token must contain 32 to 128 hexadecimal characters.")
    target = data.get("target_output", "BM83")
    if not isinstance(target, str) or not target.strip() or len(target.encode("utf-8")) > MAX_TEXT_BYTES:
        raise BridgeError("Bridge target_output must be a nonempty device name.")
    interval = data.get("interval", DEFAULT_INTERVAL)
    interval = finite_number(interval)
    if interval is None:
        raise BridgeError("Bridge interval must be a finite number.")
    if not 0.5 <= interval <= 3.0:
        raise BridgeError("Bridge interval must be between 0.5 and 3 seconds.")
    return {"host": str(address), "port": port, "token": token,
            "target_output": target.strip(), "interval": float(interval)}


def clean_text(value):
    """Bound UTF-8 text without splitting a multibyte character or retaining controls."""
    if not isinstance(value, str):
        return ""
    value = " ".join(value.replace("\x00", " ").split())
    value = "".join(character for character in value if ord(character) >= 32 and ord(character) != 127)
    return value.encode("utf-8", errors="replace")[:MAX_TEXT_BYTES].decode("utf-8", errors="ignore")


def finite_number(value):
    """Return a finite numeric value, excluding JSON booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except OverflowError:
        return None
    return value if math.isfinite(value) else None


def milliseconds(value):
    """Convert a finite nonnegative duration in seconds to bounded milliseconds."""
    value = finite_number(value)
    if value is None or value < 0:
        return None
    return int(min(MAX_MILLISECONDS / 1000.0, value) * 1000)


def normalize_snapshot(raw, target_output="BM83", now=None):
    """Translate a native read into wire fields, clearing when BM83 is not output."""
    stopped = {"state": "stopped", "title": "", "artist": "", "album": "",
               "duration_ms": None, "position_ms": None}
    if not isinstance(raw, dict) or raw.get("error"):
        return stopped
    output = raw.get("output_name")
    if not isinstance(output, str) or output.casefold() != target_output.casefold():
        return stopped
    title = clean_text(raw.get("title"))
    if not raw.get("has_item") or not title:
        return stopped
    rate = finite_number(raw.get("rate"))
    state = "playing" if rate is not None and rate > 0 else "paused"
    duration = milliseconds(raw.get("duration"))
    position = finite_number(raw.get("elapsed"))
    timestamp = finite_number(raw.get("timestamp"))
    now = time.time() if now is None else now
    if position is not None and state == "playing" and timestamp is not None:
        position += max(0.0, now - timestamp) * rate
    position = milliseconds(position)
    if duration is not None and position is not None:
        position = min(duration, position)
    return {"state": state, "title": title, "artist": clean_text(raw.get("artist")),
            "album": clean_text(raw.get("album")), "duration_ms": duration, "position_ms": position}


def encode_packet(metadata, token, session, sequence):
    """Encode one versioned authenticated snapshot with a strict datagram bound."""
    packet = {"v": 1, "token": token, "session": session, "seq": sequence}
    packet.update(metadata)
    for field in ("title", "artist", "album"):
        packet[field] = clean_text(packet.get(field))
    try:
        while True:
            data = json.dumps(packet, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            if len(data) <= MAX_PACKET_BYTES:
                return data
            longest = max(("title", "artist", "album"), key=lambda field: len(packet[field].encode("utf-8")))
            encoded = packet[longest].encode("utf-8")
            if not encoded:
                raise BridgeError("Metadata snapshot exceeds the packet limit.")
            # JSON escaping may make text larger than its UTF-8 form. Reduce
            # only display fields; authentication/session data is never cut.
            packet[longest] = encoded[:-max(1, (len(data) - MAX_PACKET_BYTES + 1) // 2)].decode("utf-8", "ignore")
    except (ValueError, TypeError):
        raise BridgeError("Cannot encode metadata snapshot.") from None


def build_helper(output=None):
    """Build the local Objective-C reader with Xcode Command Line Tools."""
    output = Path(output) if output else BASE / "build" / "now_playing.dylib"
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Fixed compiler argv and local source/output paths, no shell.
        subprocess.run(  # nosec B603
            ["/usr/bin/clang", "-fobjc-arc", "-dynamiclib", "-framework", "Foundation",
             "-framework", "CoreAudio", str(BASE / "now_playing.m"), "-o", str(output)], check=True)
    except (OSError, subprocess.CalledProcessError):
        raise BridgeError("Cannot build reader; install Xcode Command Line Tools and retry.") from None
    return output


def read_snapshot(helper=None):
    """Read metadata and the active audio output, with no playback or UI actions."""
    helper = Path(helper) if helper else BASE / "build" / "now_playing.dylib"
    if not helper.is_file():
        raise BridgeError("Native reader missing; run bridge.py --build-helper first.")
    try:
        # Fixed local reader and resolved local helper, no shell.
        result = subprocess.run(  # nosec B603
            ["/usr/bin/perl", str(BASE / "read_now_playing.pl"), str(helper.resolve())],
            check=True, capture_output=True, timeout=4, text=True)
        if len(result.stdout) > 16384:
            raise BridgeError("Native reader produced an oversized snapshot.")
        raw = json.loads(result.stdout)
    except BridgeError:
        raise
    except (OSError, subprocess.SubprocessError, ValueError):
        raise BridgeError("Native Now Playing reader failed or timed out.") from None
    if not isinstance(raw, dict) or raw.get("error"):
        raise BridgeError("Native Now Playing API is unavailable.")
    return raw


class Sender:
    """Emit monotonic snapshots for one process session; never log its token."""

    def __init__(self, config, transport=None):
        self.config = config
        self.owns_transport = transport is None
        self.transport = transport if transport is not None else socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.session = secrets.token_hex(8)
        self.sequence = 0

    def send(self, raw, now=None):
        """Send a current snapshot or an explicit stopped/clear heartbeat."""
        self.sequence += 1
        if self.sequence > 2147483647:
            self.session = secrets.token_hex(8)
            self.sequence = 1
        metadata = normalize_snapshot(raw, self.config["target_output"], now)
        data = encode_packet(metadata, self.config["token"], self.session, self.sequence)
        self.transport.sendto(data, (self.config["host"], self.config["port"]))
        return metadata

    def refresh_transport(self):
        """Discard a failed socket's route cache before the next heartbeat."""
        if not self.owns_transport:
            return False
        try:
            replacement = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except OSError:
            return False
        self.transport.close()
        self.transport = replacement
        return True

    def close(self):
        """Close the UDP socket."""
        self.transport.close()


class NetworkDiagnostics:
    """Rate-limit network diagnostics without printing tokens or addresses."""

    def __init__(self, log=None, interval=30.0):
        self.log = log if log is not None else self._log
        self.interval = interval
        self.failures = 0
        self.last_log = None
        self.last_errno = None

    @staticmethod
    def _log(message):
        print("[metadata-bridge] " + message, file=sys.stderr, flush=True)

    def failed(self, error, now=None):
        """Record a failure, logging first occurrence, changed errno and every 30s."""
        now = time.monotonic() if now is None else now
        self.failures += 1
        code = error.errno
        if self.last_log is None or code != self.last_errno or now - self.last_log >= self.interval:
            label = errno.errorcode.get(code, "UNKNOWN")
            self.log("UDP send failed (errno={}, {}, consecutive={}); retrying".format(code, label, self.failures))
            self.last_log = now
            self.last_errno = code

    def recovered(self):
        """Log one recovery after a run of failures."""
        if self.failures:
            self.log("UDP sending recovered after {} failed attempts".format(self.failures))
        self.failures = 0
        self.last_log = None
        self.last_errno = None


def main(argv=None):
    """CLI used both interactively and by a user LaunchAgent."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="private receiver profile (token stays out of command arguments)")
    parser.add_argument("--helper", type=Path, help="compiled native reader, if outside the default build directory")
    parser.add_argument("--build-helper", action="store_true", help="compile the local native reader and exit")
    parser.add_argument("--snapshot", action="store_true", help="print one read-only local snapshot, without network traffic")
    parser.add_argument("--once", action="store_true", help="send one snapshot and exit")
    args = parser.parse_args(argv)
    try:
        if args.build_helper:
            print(build_helper(args.helper))
            return 0
        if args.snapshot:
            print(json.dumps(read_snapshot(args.helper), ensure_ascii=False, sort_keys=True))
            return 0
        if not args.config:
            parser.error("--config is required to send metadata")
        config = load_config(args.config)
        sender = Sender(config)
        running = True

        def stop(_signal, _frame):
            nonlocal running
            running = False

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        had_error = False
        network = NetworkDiagnostics()
        try:
            while running:
                started = time.monotonic()
                try:
                    raw = read_snapshot(args.helper)
                    if had_error:
                        print("[metadata-bridge] Now Playing reader recovered", file=sys.stderr, flush=True)
                    had_error = False
                except BridgeError as error:
                    raw = {}
                    if not had_error:
                        print("[metadata-bridge] " + str(error), file=sys.stderr, flush=True)
                    had_error = True
                try:
                    sender.send(raw)
                    network.recovered()
                except OSError as error:
                    network.failed(error)
                    sender.refresh_transport()
                    if args.once:
                        raise BridgeError("Cannot send metadata; verify receiver address and LAN connection.") from None
                if args.once:
                    return 1 if had_error else 0
                deadline = started + config["interval"]
                while running and time.monotonic() < deadline:
                    time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
        finally:
            if not args.once:
                try:
                    sender.send({})
                except OSError:
                    pass
            sender.close()
        return 0
    except BridgeError as error:
        print("[metadata-bridge] " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

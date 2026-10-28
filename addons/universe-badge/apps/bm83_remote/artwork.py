"""Asynchronous MusicBrainz/Cover Art Archive lookup and bounded JPEG cache."""

import binascii
import gc
import hashlib
import json
import os

try:
    import fetch
except ImportError:
    fetch = None

USER_AGENT = "BM83-Badge-Remote/1.0 (https://github.com/badger/home)"
MAX_JSON = 32768
MAX_JPEG = 131072
CACHE_COUNT = 4
HTTP_GAP_MS = 1100
MAX_REDIRECTS = 3
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
# MusicBrainz sheds load with 503 ("web server is currently busy") even when the
# request rate is well within its limits; about 40% of searches hit it on site Wi-Fi.
BUSY_STATUSES = (429, 502, 503, 504)
MB_RETRIES = 3
FETCH_TIMEOUT_SECONDS = 10
HOSTS = ("musicbrainz.org", "coverartarchive.org", "api.deezer.com",
         "cdn-images.dzcdn.net", "archive.org")
MBID_CHARS = "0123456789abcdef-"


class BoundedRequest:
    """Pump a size-limited response in memory, then write a complete cache file.

    Upstream Badgeware AsyncFetch limits buffered responses with max_bytes;
    its .to(file) path bypasses that bound. reset() stops cooperative I/O and
    closes the socket, so an unfinished request cannot outlive cancellation.
    https://github.com/pimoroni/tufty2350/blob/ee84772fb7f7d5424e9593029caba815c6f89c80/modules/common/fetch.py
    """

    def __init__(self, url, headers, destination, limit):
        factory = getattr(fetch, "AsyncFetch", None)
        if not callable(factory):
            raise ValueError("bounded fetch support required")
        host, _, path = url[8:].partition("/")
        try:
            core = factory(host, use_tls=True, max_bytes=limit,
                           timeout=FETCH_TIMEOUT_SECONDS)
        except TypeError:
            raise ValueError("bounded fetch support required")
        if not all(callable(getattr(core, name, None))
                   for name in ("fetch", "update", "reset")):
            raise ValueError("bounded fetch support required")
        self._fetch = core
        self.destination = destination
        self.limit = limit
        self.error = None
        self._finished = False
        self._cancelled = False
        # fetch() only configures the cooperative operation; update() does I/O.
        try:
            core.fetch("/" + path, headers=headers)
        except Exception:
            core.reset()
            raise

    @property
    def done(self):
        return self._finished

    def __bool__(self):
        if self._cancelled:
            return False
        if not self._finished:
            try:
                self._fetch.update()
                if not self._fetch.done:
                    return False
                body = self._fetch.body
                if len(body) > self.limit:
                    raise ValueError("Artwork response too large")
                with open(self.destination, "wb") as target:
                    target.write(body)
            except Exception as error:
                self.error = error
            self._finished = True
            try:
                self._fetch.reset()
            except Exception as error:
                self.error = error
        return self.error is None

    def cancel(self):
        self._cancelled = True
        self._finished = True
        self._fetch.reset()


def _allowed_url(url):
    if (not isinstance(url, str) or not url.startswith("https://") or len(url) > 512
            or any(ord(char) <= 32 or ord(char) >= 127 for char in url)):
        return False
    host = url[8:].split("/", 1)[0].lower()
    if not host or any(not (_ascii_alnum(char) or char in ".-") for char in host):
        return False
    return host in HOSTS or host.endswith(".archive.org")


def _redirect_url(request):
    # fetch never follows redirects and only exposes Location on its core object.
    core = getattr(request, "_fetch", None)
    if getattr(core, "http_status", None) not in REDIRECT_STATUSES:
        return None
    headers = getattr(core, "http_response_headers", None)
    if isinstance(headers, dict):
        for name in headers:
            if isinstance(name, str) and name.lower() == "location":
                value = headers[name]
                return value if isinstance(value, str) else None
    return None


def _quote(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _url_encode(value):
    safe = b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.~"
    out = []
    for byte in value.encode("utf-8"):
        out.append(chr(byte) if byte in safe else "%%%02X" % byte)
    return "".join(out)


def _normal(value, remaster=False):
    value = " ".join(value.strip().split()).lower()
    value = value.replace("\u2018", "'").replace("\u2019", "'")
    value = value.replace("\u201c", '"').replace("\u201d", '"')
    value = value.replace("\u2026", "...")
    for char in "\u2010\u2011\u2012\u2013\u2014\u2212":
        value = value.replace(char, "-")
    if remaster:
        for suffix in (" (remaster)", " (remastered)", " [remaster]", " [remastered]"):
            if value.endswith(suffix):
                value = value[:-len(suffix)]
                break
        # Strictly remove a trailing year + remaster qualifier.
        for word in ("remaster", "remastered"):
            for left, right in ((" (", ")"), (" [", "]"), (" - ", "")):
                suffix = left + word
                if value.endswith(right) and right:
                    body = value[:-len(right)]
                else:
                    body = value
                if suffix in body:
                    prefix, annotation = body.rsplit(suffix, 1)
                    year = annotation.strip()
                    if prefix and (not year or (len(year) == 4 and year.isdigit()
                                               and year[:2] in ("19", "20"))):
                        value = prefix
                        break
            else:
                continue
            break
    return value


def _identity(value, remaster=False):
    value = _normal(value, remaster)
    out = []
    for index, char in enumerate(value):
        if (char == "'" and index > 0 and index + 1 < len(value)
                and _ascii_alnum(value[index - 1]) and _ascii_alnum(value[index + 1])):
            continue
        out.append(char)
    return "".join(out)


def _ascii_alnum(value):
    return ("a" <= value <= "z" or "A" <= value <= "Z" or "0" <= value <= "9")


def _valid_mbid(value):
    return (isinstance(value, str) and len(value) == 36
            and all(c in MBID_CHARS for c in value.lower())
            and all(value[i] == "-" for i in (8, 13, 18, 23))
            and any(c != "0" and c != "-" for c in value))


def _artist_credit_matches(credit, artist):
    if not isinstance(credit, list) or len(credit) != 1 or not isinstance(credit[0], dict):
        return False
    entry = credit[0]
    credited = entry.get("name")
    obj = entry.get("artist")
    if not isinstance(obj, dict):
        return False
    requested = _normal(artist)
    names = [credited, obj.get("name")]
    aliases = obj.get("aliases", [])
    if aliases:
        if (not _valid_mbid(obj.get("id")) or not isinstance(aliases, list)
                or len(aliases) > 16):
            return False
        for alias in aliases:
            if not isinstance(alias, dict) or not isinstance(alias.get("name"), str):
                return False
            if alias.get("type") not in (None, "Artist name", "Legal name", "Search hint"):
                return False
            names.append(alias["name"])
    return any(isinstance(name, str) and _normal(name) == requested for name in names)


def _match_group(data, artist, album):
    if not isinstance(data, dict) or type(data.get("count")) is not int:
        return None
    groups = data.get("release-groups")
    if not isinstance(groups, list) or len(groups) != data["count"] or len(groups) > 8:
        return None
    matches = {}
    target_artist, target_album = _normal(artist), _identity(album, True)
    for group in groups:
        if not isinstance(group, dict) or type(group.get("score")) is not int:
            continue
        if group["score"] < 95 or group["score"] > 100:
            continue
        if not _valid_mbid(group.get("id")):
            continue
        title = group.get("title")
        if not isinstance(title, str) or _identity(title, True) != target_album:
            # Only known source labels can be stripped, and only with matching type.
            base, expected_type = _source_album(album)
            if (not expected_type or not isinstance(title, str)
                    or _identity(title, True) != _identity(base, True)
                    or group.get("primary-type") != expected_type):
                continue
        if not _artist_credit_matches(group.get("artist-credit"), target_artist):
            continue
        secondary = group.get("secondary-types", [])
        if not isinstance(secondary, list) or "Compilation" in secondary:
            continue
        matches[group["id"].lower()] = group["score"]
    if len(matches) != 1:
        return None
    return next(iter(matches))


def _source_album(album):
    suffixes = ((" - ep", "EP"), (" - single", "Single"),
                (" (encore edition)", "Album"), (" [encore edition]", "Album"),
                (" - encore edition", "Album"))
    value = _normal(album, True)
    for suffix, kind in suffixes:
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[:-len(suffix)], kind
    return value, None


def _fallback_query(artist, album):
    base, _ = _source_album(album)
    tokens = base.split()
    if not tokens or len(tokens) > 8 or any(
            not token or any(not _ascii_alnum(char) for char in token) for token in tokens):
        return None
    terms = [token + ("~1" if len(token) >= 4 else "") for token in tokens]
    return "releasegroup:(" + " AND ".join(terms) + ") AND artist:" + _quote(artist)


def _jpeg_size(path):
    try:
        return os.stat(path)[6]
    except OSError:
        return -1


def _jpeg_dimensions(data):
    if len(data) < 4 or data[:2] != b"\xff\xd8" or data[-2:] != b"\xff\xd9":
        raise ValueError("Incomplete JPEG")
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 255:
            raise ValueError("Invalid JPEG marker")
        marker = data[offset + 1]
        while marker == 255 and offset + 2 < len(data):
            offset += 1
            marker = data[offset + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        length = (data[offset + 2] << 8) | data[offset + 3]
        if length < 2 or offset + 2 + length > len(data):
            raise ValueError("Invalid JPEG segment")
        if marker == 0xC2:
            raise ValueError("Progressive JPEG")
        if marker == 0xC0:
            if length < 8:
                raise ValueError("Invalid JPEG dimensions")
            height = (data[offset + 5] << 8) | data[offset + 6]
            width = (data[offset + 7] << 8) | data[offset + 8]
            if not (0 < width <= 320 and 0 < height <= 320):
                raise ValueError("JPEG dimensions out of range")
            return width, height, True
        if marker == 0xDA:
            break
        offset += length + 2
    raise ValueError("Expected baseline JPEG")


class Artwork:
    def __init__(self, directory="/state/bm83_art"):
        self.directory = directory
        self.request = None
        self.temp = None
        self.stage = ""
        self.key = None
        self.artist = self.album = ""
        self.path = None
        self.image = None
        self.message = "No cover"
        self.next_http = 0
        self.last_mb_at = None
        self.started = 0
        self.group = None
        self.fallback_used = False
        self.busy = 0
        self.deezer_id = None
        self.hops = 0
        self._make_dir()

    def _make_dir(self):
        try:
            os.mkdir(self.directory)
        except OSError:
            pass
        try:
            for name in os.listdir(self.directory):
                if name.endswith(".tmp"):
                    self._remove_temp(self.directory + "/" + name)
        except OSError as error:
            if not error.args or error.args[0] not in (2, 3):
                print("BM83 artwork cache cleanup:", str(error)[:64])

    def _remove_temp(self, path):
        if not path:
            return
        try:
            os.remove(path)
        except OSError as error:
            if not error.args or error.args[0] != 2:
                print("BM83 artwork temp cleanup:", str(error)[:64])

    def _dispose_request(self):
        request, self.request = self.request, None
        path, self.temp = self.temp, None
        if request is not None:
            try:
                request.cancel()
            except Exception as error:
                print("BM83 artwork request cleanup:", str(error)[:64])
        self._remove_temp(path)

    def close(self):
        self.cancel()

    def _cache_key(self, artist, album):
        value = (_normal(artist) + "\0" + _normal(album, True)).encode("utf-8")
        return binascii.hexlify(hashlib.sha256(value).digest()[:8]).decode()

    def _path(self, key, suffix):
        return self.directory + "/" + key + suffix

    def start(self, artist, album, now):
        if not isinstance(artist, str) or not isinstance(album, str) or not artist or not album:
            self.cancel()
            self.key = None
            self.artist = self.album = ""
            self.message = "No album artwork"
            return
        if len(artist) > 96 or len(album) > 96:
            self.cancel()
            self.key = None
            self.artist = self.album = ""
            self.message = "Artwork metadata too long"
            return
        key = self._cache_key(artist, album)
        if key == self.key and (self.image is not None or self.stage):
            return
        self.cancel()
        self.key, self.artist, self.album = key, artist, album
        cached = self._path(key, ".jpg")
        size = _jpeg_size(cached)
        if 4 <= size <= MAX_JPEG:
            try:
                self.image = self._decode(cached)
                self.path = cached
                self.message = ""
                return
            except Exception:
                try:
                    os.remove(cached)
                except OSError:
                    pass
        self.started = now
        self.fallback_used = False
        self.busy = 0
        self.message = "Looking for cover..."
        self._begin_mb(now, False)

    def _begin_mb(self, now, fallback):
        if fetch is None:
            self.message = "Artwork needs internet"
            self.stage = ""
            return
        query = ('releasegroup:' + _quote(_normal(self.album, True))
                 + ' AND artist:' + _quote(self.artist))
        if fallback:
            query = _fallback_query(self.artist, self.album)
            if not query:
                self.message, self.stage = "No matching cover", ""
                return
        if (self.last_mb_at is not None
                and ((now - self.last_mb_at) & 0xffffffff) < HTTP_GAP_MS):
            self.stage = "mb-wait"
            self.wait_fallback = fallback
            return
        url = ("https://musicbrainz.org/ws/2/release-group/?fmt=json&limit=8&query="
               + _url_encode(query))
        self._request_url(url, "mb-fallback" if fallback else "mb", MAX_JSON, now)

    def _request_url(self, url, stage, limit, now, hops=0):
        if not _allowed_url(url):
            self.message, self.stage = "Artwork source rejected", ""
            return
        if fetch is None:
            self.message, self.stage = "Artwork needs internet", ""
            return
        if not callable(getattr(fetch, "AsyncFetch", None)):
            self.message, self.stage = "Artwork needs bounded fetch support", ""
            return
        # Release previous response buffers before allocating another response.
        gc.collect()
        self.temp = self._path(self.key, ".tmp")
        try:
            json_stage = stage in ("mb", "mb-fallback", "deezer-search")
            if stage.startswith("mb"):
                self.last_mb_at = now
            self.request = BoundedRequest(
                url, {"User-Agent": USER_AGENT,
                      "Accept": "application/json" if json_stage else "image/jpeg"},
                self.temp, limit)
        except Exception as error:
            self.request = None
            self._remove_temp(self.temp)
            self.temp = None
            self.message = "Artwork: " + str(error)[:48]
            self.stage = ""
            return
        self.stage = stage
        self.limit = limit
        self.hops = hops
        self.next_http = now

    def _follow_redirect(self, now):
        if not getattr(self.request, "error", None):
            return False
        url = _redirect_url(self.request)
        if url is None:
            return False
        if self.hops >= MAX_REDIRECTS or not _allowed_url(url):
            raise ValueError("Artwork redirect rejected")
        stage, limit, hops = self.stage, self.limit, self.hops + 1
        self._dispose_request()
        self._request_url(url, stage, limit, now, hops)
        return True

    def _retry_busy(self, now):
        stage = self.stage
        status = getattr(getattr(self.request, "_fetch", None), "http_status", None)
        if (stage not in ("mb", "mb-fallback") or self.busy >= MB_RETRIES
                or not getattr(self.request, "error", None)
                or status not in BUSY_STATUSES):
            return False
        self.busy += 1
        print("BM83 artwork: MusicBrainz busy (%d), retry %d" % (status, self.busy))
        self._dispose_request()
        self.last_mb_at = now
        self._begin_mb(now, stage == "mb-fallback")
        return True

    def cancel(self):
        self._dispose_request()
        self.stage = ""
        self.group = None
        self.image = None
        self.path = None

    def retry(self, now):
        if self.artist and self.album:
            self.key = None
            self.start(self.artist, self.album, now)

    def _decode(self, path):
        size = _jpeg_size(path)
        if not (4 <= size <= MAX_JPEG):
            raise ValueError("Invalid cached JPEG size")
        with open(path, "rb") as file:
            data = file.read(MAX_JPEG + 1)
        if len(data) != size or data[:2] != b"\xff\xd8" or data[-2:] != b"\xff\xd9":
            raise ValueError("Invalid JPEG")
        width, height, baseline = _jpeg_dimensions(data)
        if not baseline:
            raise ValueError("Progressive JPEG")
        return image.load(data, width, height)  # noqa: F821 - image is supplied by badge firmware

    def _complete_file(self, now):
        request = self.request
        if request is None:
            return
        error = getattr(request, "error", None)
        if error:
            raise ValueError(str(error)[:64])
        size = _jpeg_size(self.temp)
        if size < 0:
            return
        if size > self.limit:
            raise ValueError("Artwork response too large")
        self.request = None
        if self.stage in ("mb", "mb-fallback", "deezer-search"):
            with open(self.temp, "rb") as file:
                body = file.read(self.limit + 1)
            os.remove(self.temp)
            if len(body) > self.limit:
                raise ValueError("Artwork JSON too large")
            return json.loads(body.decode("utf-8"))
        if self.stage == "caa":
            try:
                decoded = self._decode(self.temp)
            except Exception:
                self._remove_temp(self.temp)
                raise
            path = self._path(self.key, ".jpg")
            try:
                os.rename(self.temp, path)
            except OSError:
                with open(self.temp, "rb") as source:
                    data = source.read(self.limit + 1)
                with open(path, "wb") as target:
                    target.write(data)
                os.remove(self.temp)
            self.path = path
            self.image = decoded
            self.message = ""
            self.stage = ""
            self._trim_cache()
            return None
        if self.stage in ("deezer-image", "deezer-canonical"):
            try:
                self.image = self._decode(self.temp)
                self.path = self._path(self.key, ".jpg")
                os.rename(self.temp, self.path)
                self.message = ""
                self.stage = ""
                self._trim_cache()
                return None
            except Exception:
                if self.deezer_id and self.stage == "deezer-image":
                    self._request_url("https://api.deezer.com/album/%d/image" % self.deezer_id,
                                      "deezer-canonical", MAX_JPEG, now)
                    return None
                raise
        raise ValueError("Unknown artwork stage")

    def _start_deezer(self, now):
        # Deezer's fielded artist:/album: album search returns nothing; plain text
        # works and _use_deezer then requires an exact artist and title match.
        query = self.artist + " " + _source_album(self.album)[0]
        url = "https://api.deezer.com/search/album?limit=8&q=" + _url_encode(query)
        self._request_url(url, "deezer-search", MAX_JSON, now)

    def _trim_cache(self):
        try:
            files = [name for name in os.listdir(self.directory) if name.endswith(".jpg")]
            if len(files) <= CACHE_COUNT:
                return
            files.sort()
            while len(files) > CACHE_COUNT:
                os.remove(self.directory + "/" + files.pop(0))
        except OSError:
            return

    def step(self, now, connected):
        if not self.stage:
            return
        if not connected:
            self.message = "Artwork needs internet"
            self.cancel()
            return
        if ((now - self.started) & 0xffffffff) > 45000:
            self.message = "Artwork lookup timed out"
            self.cancel()
            return
        if self.stage == "mb-wait":
            if (self.last_mb_at is None
                    or ((now - self.last_mb_at) & 0xffffffff) >= HTTP_GAP_MS):
                self.stage = ""
                self._begin_mb(now, self.wait_fallback)
            return
        if self.request is not None:
            if _jpeg_size(self.temp) > self.limit:
                self.message = "Artwork response too large"
                self.cancel()
                return
            # The adapter pumps one cooperative step and latches success/error.
            if self.request or getattr(self.request, "error", None):
                try:
                    stage = self.stage
                    if self._follow_redirect(now) or self._retry_busy(now):
                        return
                    result = self._complete_file(now)
                    if stage in ("mb", "mb-fallback"):
                        if not isinstance(result, dict):
                            raise ValueError("Invalid MusicBrainz response")
                        count = result.get("count")
                        if type(count) is not int or count < 0 or count > 8:
                            raise ValueError("Incomplete MusicBrainz search")
                        self.group = _match_group(result, self.artist, self.album)
                        if not self.group:
                            if count == 0 and stage == "mb" and not self.fallback_used:
                                self.fallback_used = True
                                self._begin_mb(now, True)
                            else:
                                self.message, self.stage = "No matching cover", ""
                            return
                        self._request_url("https://coverartarchive.org/release-group/"
                                          + self.group + "/front-250", "caa", MAX_JPEG, now)
                    elif stage in ("caa", "deezer-image", "deezer-canonical"):
                        if self.image is None and not self.stage:
                            self._start_deezer(now)
                    elif stage == "deezer-search":
                        self._use_deezer(result, now)
                    return
                except Exception as error:
                    print("BM83 artwork:", str(error)[:80])
                    if self.stage == "caa" and self.group:
                        self._dispose_request()
                        self._remove_temp(self.path)
                        self.path = None
                        self._start_deezer(now)
                    else:
                        self.message = "Artwork unavailable"
                        self.cancel()
                    return
            # The cooperative fetch advances again on the next frame.
            return

    def _use_deezer(self, data, now):
        if not isinstance(data, dict) or type(data.get("total")) is not int:
            raise ValueError("Invalid Deezer response")
        entries = data.get("data")
        if not isinstance(entries, list) or data["total"] != len(entries) or len(entries) > 8:
            raise ValueError("Incomplete Deezer response")
        found = []
        artist_key, album_key = _normal(self.artist), _identity(self.album, True)
        for item in entries:
            if not isinstance(item, dict) or item.get("type") != "album":
                continue
            title, artist = item.get("title"), item.get("artist")
            if not isinstance(title, str) or not isinstance(artist, dict) or not isinstance(artist.get("name"), str):
                continue
            base, kind = _source_album(self.album)
            album_match = _identity(title, True) == album_key
            if kind:
                album_match = album_match or (
                    _identity(title, True) == _identity(base, True)
                    and item.get("record_type") == kind.lower())
            cover = item.get("cover_medium")
            if (_normal(artist["name"]) == artist_key and album_match
                    and type(item.get("id")) is int and item["id"] > 0
                    and isinstance(cover, str)
                    and cover.startswith("https://cdn-images.dzcdn.net/images/cover/")):
                found.append((item["id"], cover))
        if len(found) != 1:
            self.message, self.stage = "No matching cover", ""
            return
        self.deezer_id, url = found[0]
        self._request_url(url, "deezer-image", MAX_JPEG, now)

    def set_result(self, value):
        """Test seam for deterministic simulator sample-state injection."""
        self.cancel()
        self.artist = value.get("artist", "")
        self.album = value.get("album", "")
        self.message = "No cover"

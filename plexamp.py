"""Local Caldera/Plex Companion adapter; status reads never wait on the network."""
import itertools
import hashlib
import json
import math
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict
from pathlib import Path

BASE = 'http://127.0.0.1:32500'
PREFERENCES = Path.home() / '.config/caldera-music/preferences.json'
_commands = itertools.count(1)
_lock = threading.Lock()
_state = {'connected': False, 'state': 'stopped'}
_metadata = OrderedDict()
_wanted = None
_wake = threading.Event()
_servers = {}


def identity(raw):
    key = str(raw.get('ratingKey', ''))
    machine = raw.get('machineIdentifier', '')
    return (machine, key) if machine and key.isdecimal() else None


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        before, after = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if (before.scheme, before.netloc) != (after.scheme, after.netloc):
            raise RuntimeError('Plex omleiding naar een andere server geweigerd.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def remote(url, token, image=False):
    req = urllib.request.Request(url, headers={'X-Plex-Token': token,
        'X-Plex-Client-Identifier': 'cdspeler-web',
        'Accept': 'image/*' if image else 'application/xml'})
    with urllib.request.build_opener(SameOriginRedirect()).open(req, timeout=6) as response:
        limit = 4 * 1024 * 1024 if image else 1024 * 1024
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Plex antwoord te groot.')
        if image:
            kind = response.headers.get_content_type()
            if kind not in ('image/jpeg', 'image/png', 'image/webp'):
                raise ValueError('Onbekend hoesformaat.')
            return data, kind
        return ET.fromstring(data)


def server_urls(machine, token):
    now = time.monotonic()
    cached = _servers.get(machine)
    if cached and now - cached[0] < 3600:
        return cached[1]
    resources = remote('https://plex.tv/api/resources?includeHttps=1&includeRelay=1', token)
    device = next(d for d in resources.findall('Device')
                  if d.get('clientIdentifier') == machine and 'server' in d.get('provides', '').split(','))
    connections = sorted(device.findall('Connection'), key=lambda c: (
        c.get('relay') == '1', c.get('local') == '1'))
    urls = []
    for connection in connections:
        uri = connection.get('uri', '')
        parsed = urllib.parse.urlsplit(uri)
        if (parsed.scheme == 'https' and parsed.hostname and not parsed.username
                and not parsed.password and parsed.path in ('', '/')
                and not parsed.query and not parsed.fragment):
            urls.append(uri.rstrip('/'))
    if not urls:
        raise RuntimeError('Geen beveiligde Plex-verbinding beschikbaar.')
    _servers[machine] = now, urls
    return urls


def load_metadata(key):
    machine, rating_key = key
    token = json.loads(PREFERENCES.read_text())['plex']['token']
    track = None
    for base in server_urls(machine, token):
        try:
            track = remote(base + '/library/metadata/' + rating_key, token).find('Track')
            if track is not None:
                break
        except Exception:
            continue
    if track is None:
        raise RuntimeError('Nummerinformatie tijdelijk niet beschikbaar.')
    meta = {'title': track.get('title', ''),
            'artist': track.get('originalTitle') or track.get('grandparentTitle', ''),
            'album': track.get('parentTitle', ''), 'cover': None}
    # Publish names before fetching the artwork. A slow cover must not hide titles.
    with _lock:
        _metadata[key] = meta
        _metadata.move_to_end(key)
        while len(_metadata) > 16:
            _metadata.popitem(last=False)
    thumb = track.get('thumb') or track.get('parentThumb')
    if thumb and thumb.startswith('/library/metadata/') and not urllib.parse.urlsplit(thumb).netloc:
        try:
            query = urllib.parse.urlencode({'width': 400, 'height': 400, 'minSize': 1, 'url': thumb})
            data, kind = remote(base + '/photo/:/transcode?' + query, token, image=True)
            digest = hashlib.sha256((machine + ':' + rating_key).encode()).hexdigest()
            with _lock:
                if key in _metadata:
                    _metadata[key] = dict(meta, cover='/api/plexamp/cover/' + digest,
                                          image=data, image_type=kind, digest=digest)
        except Exception:
            pass


def observe_metadata():
    retry_at = {}
    while True:
        _wake.wait(1)
        _wake.clear()
        with _lock:
            key = _wanted
            known = key in _metadata
        if not key or known or time.monotonic() < retry_at.get(key, 0):
            continue
        try:
            load_metadata(key)
            retry_at.pop(key, None)
        except Exception:
            # Only the current track is retried; old failures cannot accumulate.
            retry_at = {key: time.monotonic() + 15}


def cover(digest):
    with _lock:
        return next(((m['image'], m['image_type']) for m in _metadata.values()
                     if m.get('digest') == digest), None)


def configured():
    try:
        return bool(json.loads(PREFERENCES.read_text()).get('plex', {}).get('token'))
    except (OSError, ValueError):
        return False


def request(path, **params):
    params['commandID'] = next(_commands)
    req = urllib.request.Request(BASE + path + '?' + urllib.parse.urlencode(params), headers={
        'X-Plex-Client-Identifier': 'cdspeler-web', 'X-Plex-Product': 'CDspeler',
        'Accept': 'application/xml'})
    with urllib.request.urlopen(req, timeout=2) as response:
        return ET.fromstring(response.read())


def observe(enabled):
    global _state, _wanted
    while True:
        try:
            if enabled():
                root = request('/player/timeline/poll', wait=0)
                timeline = next(t for t in root.findall('Timeline') if t.get('type') == 'music')
                with _lock:
                    _state = dict(timeline.attrib, connected=True, observed_at=time.monotonic())
                    _wanted = identity(_state)
                _wake.set()
                if timeline.get('volume') and float(timeline.get('volume')) != 100:
                    request('/player/playback/setParameters', volume=100)
            else:
                with _lock:
                    _state = {'connected': False, 'state': 'stopped'}
                    _wanted = None
        except Exception:
            with _lock:
                _state = {'connected': False, 'state': 'stopped'}
        time.sleep(1)


def snapshot():
    with _lock:
        raw = dict(_state)
        meta = dict(_metadata.get(identity(raw), {}))
    seconds = float(raw.get('duration', 0)) / 1000
    elapsed = float(raw.get('time', 0)) / 1000
    if raw.get('state') == 'playing':
        elapsed += max(0, time.monotonic() - raw.get('observed_at', time.monotonic()))
    controls = raw.get('controllable', '').split(',')
    return {'configured': configured(), 'connected': raw.get('connected', False),
            'state': raw.get('state', 'stopped'), 'title': meta.get('title', raw.get('title', '')),
            'artist': meta.get('artist', raw.get('grandparentTitle', raw.get('artist', ''))),
            'album': meta.get('album', raw.get('parentTitle', raw.get('album', ''))),
            'cover': meta.get('cover'),
            'metadata_loading': bool(identity(raw)) and not bool(meta),
            'has_track': bool(raw.get('ratingKey') or raw.get('key')),
            'seconds': seconds, 'elapsed': min(elapsed, seconds) if seconds else elapsed,
            'volume': 100, 'available_actions': {k: v in controls for k, v in {
                'skip_prev': 'skipPrevious', 'skip_next': 'skipNext', 'seek': 'seekTo'}.items()}}


def command(name, seconds=None):
    paths = {'play': 'play', 'pause': 'pause', 'stop': 'stop',
             'next': 'skipNext', 'previous': 'skipPrevious', 'seek': 'seekTo'}
    if name not in paths:
        raise ValueError('Onbekende Plexamp-opdracht.')
    params = {}
    if name == 'seek':
        seconds = float(seconds)
        if not math.isfinite(seconds) or not 0 <= seconds <= 86400:
            raise ValueError('Ongeldige positie.')
        params['offset'] = round(seconds * 1000)
    try:
        request('/player/playback/' + paths[name], **params)
    except Exception as exc:
        raise RuntimeError('Plexamp reageert nog niet. Kies CDspeler in Plexamp en start een nummer.') from exc

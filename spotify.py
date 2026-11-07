import json
import threading
import time
from contextlib import closing

import websocket

URL = 'ws://127.0.0.1:9090'
_lock = threading.Lock()
_state = {'connected': False, 'logged_in': False, 'status': 'idle'}


def observe():
    while True:
        try:
            with closing(websocket.create_connection(URL, timeout=30, suppress_origin=True)) as ws:
                with _lock:
                    _state['connected'] = True
                while True:
                    try:
                        message = json.loads(ws.recv())
                    except websocket.WebSocketTimeoutException:
                        ws.ping()
                        continue
                    kind = message.get('type')
                    with _lock:
                        if kind == 'playback_state':
                            _state.update(message)
                        elif kind == 'auth_state':
                            _state.update(message)
                        elif kind == 'track_changed':
                            _state['item'] = message.get('item', {})
                        elif kind == 'playback_changed':
                            _state['status'] = message.get('status', 'idle')
                        elif kind == 'volume_changed':
                            _state['volume'] = message.get('volume', 50)
                        elif kind == 'position_sync':
                            _state['position'] = message.get('position', {})
                        elif kind == 'device_changed':
                            _state.update(message)
                    if kind == 'auth_state' and message.get('logged_in'):
                        ws.send(json.dumps({'type': 'command', 'command': 'get_state'}))
                    if kind in ('playback_state', 'volume_changed') and message.get('volume', 100) != 100:
                        ws.send(json.dumps({'type': 'command', 'command': 'set_volume', 'volume': 100}))
        except Exception:
            with _lock:
                _state['connected'] = False
            time.sleep(3)


def snapshot():
    with _lock:
        raw = dict(_state)
    if not raw.get('connected'):
        return {'state': 'unavailable', 'connected': False, 'title': '', 'artist': ''}
    decorations = raw.get('item', {}).get('decorations', {})
    title = decorations.get('identity', {}).get('name', '')
    creators = decorations.get('creators', [])
    artist = ', '.join(c.get('entity', {}).get('decorations', {}).get('identity', {}).get('name', '')
                       for c in creators)
    covers = decorations.get('visual_identity', {}).get('cover', [])
    album = decorations.get('parent', {}).get('entity', {}).get('decorations', {}).get('identity', {}).get('name', '')
    sizes = {'small': 1, 'default': 2, 'large': 3, 'xlarge': 4}
    covers = sorted(covers, key=lambda c: sizes.get(c.get('size'), 0), reverse=True)
    cover = next((c['url'] for c in covers if c.get('url', '').startswith('https://i.scdn.co/image/')), None)
    position = raw.get('position', {})
    elapsed = position.get('position_ms', 0) / 1000
    if raw.get('status') == 'playing' and position.get('timestamp_ms'):
        elapsed += max(0, time.time() - position['timestamp_ms'] / 1000) * position.get('speed', 1)
    total = decorations.get('playback', {}).get('duration_ms', 0) / 1000
    return {'state': raw.get('status', 'idle'), 'connected': True,
            'logged_in': raw.get('logged_in', False), 'title': title, 'artist': artist, 'album': album,
            'cover': cover, 'seconds': total, 'elapsed': min(elapsed, total) if total else elapsed,
            'volume': raw.get('volume', 50), 'available_actions': raw.get('available_actions', {})}


def command(name, **fields):
    with closing(websocket.create_connection(URL, timeout=4, suppress_origin=True)) as ws:
        ws.send(json.dumps(dict(type='command', command=name, **fields)))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            message = json.loads(ws.recv())
            if message.get('type') == 'error':
                raise RuntimeError('Kies eerst CDspeler in je Spotify-app en start een nummer.')
            if message.get('type') == 'command_result' and message.get('command') == name:
                return
    raise RuntimeError('Spotify reageert nog niet. Probeer opnieuw.')

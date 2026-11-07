#!/usr/bin/python3
import json
import os
from pathlib import Path

folder = Path(__file__).resolve().parent / 'data'
folder.mkdir(exist_ok=True)
path = folder / 'spotify.json'
try:
    state = json.loads(path.read_text())
except Exception:
    state = {}
event = os.environ.get('PLAYER_EVENT', '')
if event == 'track_changed':
    covers = os.environ.get('COVERS', '').splitlines()
    cover = next((url for url in covers if url.startswith('https://i.scdn.co/image/')), None)
    state.update(title=os.environ.get('NAME', ''), artist=', '.join(os.environ.get('ARTISTS', '').splitlines()),
                 album=os.environ.get('ALBUM', ''), cover=cover, state='playing')
elif event in ('playing', 'paused', 'stopped'):
    state['state'] = event
elif event == 'session_disconnected':
    state = {'state': 'ready'}
tmp = path.with_suffix('.tmp')
tmp.write_text(json.dumps(state))
tmp.replace(path)

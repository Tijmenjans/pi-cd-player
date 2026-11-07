#!/usr/bin/python3
import getpass
import json
import os
from pathlib import Path

key = getpass.getpass('Plak je Spotify Soloist API-sleutel (onzichtbaar): ').strip()
if not key or any(c.isspace() for c in key):
    raise SystemExit('Geen geldige sleutel ingevuld; niets opgeslagen.')
folder = Path(__file__).resolve().parent / 'data'
folder.mkdir(mode=0o700, exist_ok=True)
path = folder / 'soloist.env'
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write('SOLOIST_API_KEY=' + json.dumps(key) + '\n')
os.chmod(path, 0o600)
print('Sleutel privé opgeslagen op de Pi. Je kunt terug naar de chat.')

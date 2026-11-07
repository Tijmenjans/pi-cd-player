"""Retain a playable album independently of physical optical media."""
import json
import re
from pathlib import Path


def completely_stored(disc, saved):
    numbers = [t.get('number') for t in disc.get('tracks', [])]
    states = saved.get('states', {})
    return bool(numbers and len(set(numbers)) == len(numbers)
                and saved.get('disc_id') == disc.get('id')
                and saved.get('stored') == saved.get('total') == len(numbers)
                and not any(saved.get(k) for k in ('error', 'drive_blocked', 'buffer_full', 'blocked', 'skipped'))
                and set(states) == set(numbers)
                and all(states[n].get('ready') is True and states[n].get('storage') == 'ready'
                        and not states[n].get('archive_error') for n in numbers))


def load_ejected(path):
    """Only restore bounded, previously detached playback metadata, never paths/credentials."""
    try:
        path = Path(path)
        if path.is_symlink() or path.stat().st_size > 250_000:return None
        disc = json.loads(path.read_text())
        tracks = disc.get('tracks', [])
        if not (disc.get('ejected') is True and disc.get('inserted') is False
                and re.fullmatch(r'[A-Za-z0-9_.-]{8,100}', disc.get('id', ''))
                and 1 <= len(tracks) <= 99):return None
        numbers = [t['number'] for t in tracks]
        if len(set(numbers)) != len(numbers) or any(type(n) is not int or not 1 <= n <= 99 for n in numbers):return None
        if any(type(t.get('sectors')) is not int or not 1 <= t['sectors'] <= 450000 for t in tracks):return None
        disc.update(present=True, loading=False)
        return disc
    except (OSError, ValueError, TypeError, KeyError, AttributeError):return None

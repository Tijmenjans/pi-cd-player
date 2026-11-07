"""CD queue operations. The MPD playlist is the authoritative playback order."""
import json
import random


class CDQueue:
    def __init__(self, execute, path):
        self.execute, self.path = execute, path
        try:
            self.data = json.loads(path.read_text())
        except (OSError, ValueError):
            self.data = {}
        self.last = None

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.data))
        temporary.replace(self.path)

    def attach(self, disc, reset=False):
        if reset or self.data.get('disc') != disc['id']:
            self.data = dict(disc=disc['id'], shuffle=self.data.get('shuffle', False),
                             round=1, handled=[])
            self.last = None
            self.save()

    def read(self):
        status, rows = self.execute('status', 'playlistinfo')
        status = dict(x.split(': ', 1) for x in status if ': ' in x)
        entries = []
        for row in rows:
            if row.startswith('file: cdda:///'):
                entries.append(int(row.rsplit('/', 1)[1]))
        return status, entries

    def ensure(self, disc):
        self.attach(disc)
        status, entries = self.read()
        numbers = [t['number'] for t in disc['tracks']]
        if not entries or any(n not in numbers for n in entries):
            self.execute('clear', 'random 0', 'repeat 0', 'single 0', 'consume 0',
                         *[f'add "cdda:///{n}"' for n in numbers])
            self.last = None
        return self.read()

    def reorder(self, status, entries, wanted):
        start = int(status['song']) + 1 if 'song' in status else 0
        if sorted(wanted) != sorted(entries[start:]):
            raise ValueError('De wachtrij is veranderd. Probeer opnieuw.')
        for destination, number in enumerate(wanted, start):
            origin = entries.index(number)
            if origin != destination:
                self.execute(f'move {origin} {destination}')
                entries.insert(destination, entries.pop(origin))

    def toggle(self, disc, enabled):
        status, entries = self.ensure(disc)
        start = int(status['song']) + 1 if 'song' in status else 0
        wanted = entries[start:]
        if enabled:
            random.shuffle(wanted)
        else:
            wanted.sort()
        self.reorder(status, entries, wanted)
        self.data['shuffle'] = enabled
        self.save()

    def new_round(self, disc, avoid=None):
        numbers = [t['number'] for t in disc['tracks']]
        random.shuffle(numbers)
        if len(numbers) > 1 and numbers[0] == avoid:
            numbers[0], numbers[1] = numbers[1], numbers[0]
        self.execute('clear', *[f'add "cdda:///{n}"' for n in numbers], 'play 0')
        self.data.update(round=self.data.get('round', 1) + 1, handled=[])
        self.last = None
        self.save()

    def observe(self, disc):
        self.attach(disc)
        status, entries = self.read()
        position = int(status.get('song', -1))
        current = entries[position] if 0 <= position < len(entries) else None
        if (self.data.get('shuffle') and self.last and self.last['state'] == 'play'
                and self.last['position'] == len(entries) - 1 and entries
                and status.get('state') == 'stop' and not status.get('error')):
            self.new_round(disc, self.last['current'])
            status, entries = self.read()
            position = int(status.get('song', -1))
            current = entries[position] if 0 <= position < len(entries) else None
        handled = set(self.data.get('handled', []))
        handled.update(entries[:max(0, position)])
        if handled != set(self.data.get('handled', [])):
            self.data['handled'] = sorted(handled)
            self.save()
        self.last = dict(state=status.get('state'), position=position, current=current)
        return status, dict(shuffle=bool(self.data.get('shuffle')), round=self.data.get('round', 1),
                            current=current, upcoming=entries[position + 1:] if current else entries,
                            handled=sorted(handled), previous=position > 0)

    def action(self, disc, cmd, payload):
        status, entries = self.ensure(disc)
        position = int(status.get('song', -1))
        if cmd == 'shuffle':
            if not isinstance(payload.get('enabled'), bool):
                raise ValueError('Ongeldige shuffle-instelling.')
            self.toggle(disc, payload['enabled'])
        elif cmd == 'queue-order':
            wanted = payload.get('tracks')
            if not isinstance(wanted, list) or any(type(n) is not int for n in wanted):
                raise ValueError('Ongeldige wachtrij.')
            self.reorder(status, entries, wanted)
        elif cmd == 'queue-skip':
            number = int(payload['track'])
            if number not in entries[position + 1:]:
                raise ValueError('Dit nummer staat niet meer in de wachtrij.')
            self.execute(f'delete {entries.index(number)}')
            self.data['handled'] = sorted(set(self.data.get('handled', [])) | {number})
            self.save()
        elif cmd == 'track':
            number = int(payload['track'])
            if number not in [t['number'] for t in disc['tracks']]:
                raise ValueError('Onbekende track.')
            if number not in entries:
                self.execute(f'add "cdda:///{number}"')
                entries.append(number)
            self.execute(f'play {entries.index(number)}')
        elif cmd == 'next' and position == len(entries) - 1 and self.data.get('shuffle'):
            self.new_round(disc, entries[position])
        else:
            if cmd == 'stop':
                self.last = None
            self.execute({'pause': 'pause 1'}.get(cmd, cmd))
        # Record transitions immediately, including pauses at the end of a round.
        self.observe(disc)

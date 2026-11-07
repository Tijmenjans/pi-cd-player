from state_store import write_json
"""USB vinyl capture and background recognition; never blocks the player lock."""
import array
import copy
import json
import math
import os
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path
from urllib.parse import urlsplit
from vinyl_transitions import TransitionDetector, LevelMeter

# Turntable speed variation must not discard otherwise valid Shazam matches.
MAX_VINYL_SKEW = 0.05

SOURCE = 'alsa_input.usb-Burr-Brown_from_TI_USB_Audio_CODEC-00.analog-stereo-input'


def https_url(value):
    if not isinstance(value, str):
        return ''
    try:
        parts = urlsplit(value)
        return value if parts.scheme == 'https' and parts.hostname and not parts.username else ''
    except ValueError:
        return ''


def track_metadata(result):
    track = result.get('track') or {}
    if not track.get('title') or not result.get('matches'):
        return None
    # Vinyl has small speed variations. Reject gross pitch/time disagreement
    # without using the very strict threshold intended for digital recordings.
    try:
        match = result['matches'][0]
        skew = [float(match[key]) for key in ('timeskew', 'frequencyskew')]
        if any(not math.isfinite(value) or abs(value) > MAX_VINYL_SKEW for value in skew):
            return None
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    details = {item.get('title'): item.get('text', '')
               for section in track.get('sections', [])
               for item in section.get('metadata', [])}
    return {'key': str(track.get('key', '')), 'title': str(track['title']),
            'artist': str(track.get('subtitle', '')), 'album': details.get('Album', ''),
            'cover': https_url((track.get('images') or {}).get('coverarthq') or
                               (track.get('images') or {}).get('coverart')),
            'url': https_url(track.get('url')), 'recognized_at': time.time()}


def signal_levels(path):
    with wave.open(str(path), 'rb') as wav:
        if wav.getsampwidth() != 2 or wav.getnchannels() != 2:
            raise RuntimeError('De UFO202 leverde een ongeldig audioformaat.')
        samples = array.array('h', wav.readframes(wav.getnframes()))
    if not samples:
        raise RuntimeError('De UFO202 leverde geen audio.')
    rms = math.sqrt(sum(int(s) ** 2 for s in samples) / len(samples))
    return round(20 * math.log10(max(rms, 1) / 32768), 1), round(
        100 * sum(abs(s) >= 32700 for s in samples) / len(samples), 2)


class Vinyl:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.active = False
        self.generation = 0
        self.working = False
        self.last_started = 0
        self.detector = TransitionDetector()
        self.meter = LevelMeter(SOURCE)
        self.interval_file = self.root / 'data/vinyl-settings.json'
        try:
            interval = json.loads(self.interval_file.read_text()).get('interval_seconds', 60)
            if type(interval) is not int or not 20 <= interval <= 600:
                raise ValueError('invalid interval')
            self.interval = interval
        except (OSError, ValueError, AttributeError):
            self.interval = 60
        self.state = dict(state='idle', automatic=False, track=None, history=[],
                          message='Zet een plaat op en kies Herken nummer.',
                          level_db=None, clipping=False, checked_at=None, live_level_db=None)

    def connected(self):
        try:
            return any((p / 'idVendor').read_text().strip() == '08bb' and
                       (p / 'idProduct').read_text().strip() == '2902'
                       for p in Path('/sys/bus/usb/devices').iterdir()
                       if (p / 'idVendor').exists() and (p / 'idProduct').exists())
        except OSError:
            return False

    def available(self):
        return (self.root / '.venv-vinyl/ready').exists()

    def snapshot(self):
        with self.lock:
            state = copy.deepcopy(self.state)
            state['auto_interval'] = self.interval
            state['transition_pending'] = bool(state['automatic'] and self.detector.pending)
            state['auto_message'] = (('Nummer wordt herkend…' if self.working else
                self.detector.message(time.monotonic(), self.interval)) if state['automatic'] else '')
        state.update(connected=self.connected(), available=self.available())
        try:
            monitor = json.loads((self.root / 'data/vinyl-output.json').read_text())
            if time.time() - monitor.get('updated_at', 0) > 10:
                raise ValueError('stale')
        except (OSError, ValueError):
            monitor = {'name': 'IKEA VAPPEBY', 'type': 'bluetooth', 'playing': False,
                       'message': 'Audioverbinding opbouwen…'}
        state['monitor'] = monitor
        if not state['connected']:
            state['track'] = None
        if state['track']:
            state['track']['stale'] = state['transition_pending']
        return state

    def set_active(self, active):
        with self.lock:
            if self.active != active:
                self.generation += 1
                self.active = active
                self.detector.reset()
                self.state.update(automatic=False, state='idle', track=None,
                                  level_db=None, live_level_db=None, clipping=False,
                                  message='Zet een plaat op en kies Herken nummer.')

    def set_automatic(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Ongeldige instelling voor automatische herkenning.')
        with self.lock:
            if not self.active:
                raise ValueError('Kies eerst Vinyl als bron.')
            if enabled != self.state['automatic']:
                self.state['automatic'] = enabled
                if enabled:
                    self.detector.reset(pending=not bool(self.state['track']))

    def set_interval(self, seconds):
        if type(seconds) is not int or not 20 <= seconds <= 600:
            raise ValueError('Kies een interval tussen 20 en 600 seconden.')
        with self.lock:
            self.interval_file.parent.mkdir(parents=True, exist_ok=True)
            write_json(self.interval_file,{'interval_seconds':seconds})
            self.interval = seconds

    def start(self, automatic=False):
        with self.lock:
            if not self.active:
                raise ValueError('Kies eerst Vinyl als bron.')
            if automatic and not self.state['automatic']:
                return False
            if self.working:
                return False
            if not self.connected():
                raise RuntimeError('Sluit de UFO202 aan op een USB-poort van de Pi.')
            if not self.available():
                raise RuntimeError('Muziekherkenning is nog niet geïnstalleerd.')
            self.working = True
            self.last_started = time.monotonic()
            if not automatic:
                self.detector.pending = True
                self.detector.attempts = 0
            self.detector.attempted(self.last_started)
            transition = self.detector.transition
            generation = self.generation
            self.state.update(state='listening', level_db=None, clipping=False,
                              message='12 seconden luisteren naar je plaat…')
            threading.Thread(target=self.run, args=(generation, transition), daemon=True).start()
            return True

    def update(self, generation, **changes):
        with self.lock:
            if generation == self.generation and self.active:
                self.state.update(changes)

    def run(self, generation, transition=None):
        try:
            with tempfile.TemporaryDirectory(prefix='cdspeler-vinyl-') as directory:
                path = Path(directory) / 'sample.wav'
                capture = subprocess.run([
                    'timeout', '--signal=INT', '--kill-after=2', '13', 'pw-record',
                    '--target', SOURCE, '--rate', '44100', '--channels', '2',
                    '--format', 's16', str(path)],
                    capture_output=True, timeout=18)
                if capture.returncode not in (0, 124):
                    raise RuntimeError('De UFO202-ingang is niet beschikbaar. Controleer de USB-aansluiting en probeer opnieuw.')
                with self.lock:
                    if generation != self.generation or not self.active:
                        return
                level, clipped = signal_levels(path)
                self.update(generation, level_db=level, clipping=clipped > 0.5)
                if level < -45:
                    self.update(generation, state='silent', track=None,
                                message='Geen of te zacht muzieksignaal. Laat de plaat spelen en controleer de kabels en PHONO/LINE.',
                                checked_at=time.time())
                    return
                self.update(generation, state='recognizing', message='Nummer opzoeken bij Shazam…')
                env = os.environ.copy()
                native = self.root / '.venv-vinyl/native/usr/lib/arm-linux-gnueabihf'
                env['LD_LIBRARY_PATH'] = ':'.join([str(native / 'openblas-pthread'),
                                                 str(native), env.get('LD_LIBRARY_PATH', '')])
                env['OPENBLAS_NUM_THREADS'] = '1'
                result = subprocess.run([
                    str(self.root / '.venv-vinyl/bin/python'),
                    str(self.root / 'vinyl_recognize.py'), str(path)],
                    capture_output=True, text=True, timeout=55, env=env)
                if result.returncode:
                    raise RuntimeError('Shazam is niet bereikbaar of kon het fragment niet verwerken. Probeer opnieuw.')
                track = track_metadata(json.loads(result.stdout))
                with self.lock:
                    if generation != self.generation or not self.active:
                        return
                    if track:
                        if transition is None or transition == self.detector.transition:
                            self.detector.matched()
                        history = self.state['history']
                        identity = (track['title'], track['artist'])
                        history = [t for t in history if (t['title'], t['artist']) != identity]
                        self.state.update(track=track, history=([track] + history)[:15],
                                          state='matched', message='Nummer herkend.', checked_at=time.time())
                    else:
                        self.state.update(track=None, state='no_match', checked_at=time.time(),
                                          message='Geen match gevonden. Probeer een ander stukje van het nummer.')
        except subprocess.TimeoutExpired:
            self.update(generation, state='error', track=None,
                        message='Herkennen duurde te lang. Probeer opnieuw.', checked_at=time.time())
        except Exception as exc:
            message = str(exc) if isinstance(exc, RuntimeError) else 'Herkennen is niet gelukt. Probeer opnieuw.'
            self.update(generation, state='error', track=None, message=message, checked_at=time.time())
        finally:
            with self.lock:
                self.working = False

    def tick(self, level, now):
        """One meter observation; deterministic input also supports timing tests."""
        with self.lock:
            if not self.active or not self.state['automatic']:
                return
            self.state['live_level_db'] = level
            self.detector.feed(level, now)
            due = not self.working and self.detector.due(now, self.interval)
        if due:
            try:
                self.start(automatic=True)
            except (ValueError, RuntimeError) as exc:
                with self.lock:
                    self.detector.attempted(now)
                    self.state.update(state='error', track=None, message=str(exc))

    def observe(self,stop=None):
        stop=stop or threading.Event()
        while not stop.is_set():
            with self.lock:
                active = self.active and self.state['automatic']
            if active:
                try:
                    level = self.meter.read()
                    self.tick(level, time.monotonic())
                except Exception:
                    self.meter.close()
                    with self.lock:
                        self.detector.feed(None, time.monotonic())
                        self.state['live_level_db'] = None
            else:
                self.meter.close()
            stop.wait(0.25)

"""Local level metering and transition detection; no recognition requests here."""
import array
from collections import deque
import math
import os
import statistics
import subprocess
import time


class TransitionDetector:
    def __init__(self):
        self.levels = deque(maxlen=40)
        self.last_attempt = None
        self.transition = 0
        self.reset()

    def reset(self, pending=True):
        self.pending = pending
        self.attempts = 0
        self.quiet_since = None
        self.music_since = None
        self.armed = False
        self.levels.clear()

    @property
    def threshold(self):
        baseline = statistics.median(self.levels) if self.levels else -30
        return max(-50, min(-38, baseline - 12))

    def feed(self, level, now):
        if level is None or not math.isfinite(level):
            # Missing samples are not evidence of a quiet song transition.
            self.quiet_since = self.music_since = None
            return
        threshold = self.threshold
        if level <= threshold:
            self.music_since = None
            if self.quiet_since is None:
                self.quiet_since = now
            if now - self.quiet_since >= 1.25:
                self.armed = True
        elif level >= threshold + 5:
            self.quiet_since = None
            if self.music_since is None:
                self.music_since = now
            if self.armed and now - self.music_since >= 1:
                self.pending = True
                self.transition += 1
                self.attempts = 0
                self.armed = False
            self.levels.append(level)
        else:
            self.quiet_since = self.music_since = None

    def delay(self, now, interval):
        return max(0, (self.last_attempt + interval - now)) if self.last_attempt is not None else 0

    def due(self, now, interval):
        return (self.pending and not self.armed and self.attempts < 3 and
                self.music_since is not None and now - self.music_since >= 1 and
                self.delay(now, interval) == 0)

    def attempted(self, now):
        self.last_attempt = now
        self.attempts += 1

    def matched(self):
        self.pending = False
        self.attempts = 0

    def message(self, now, interval):
        if self.armed:
            return 'Overgang gehoord · wacht tot de muziek terugkomt.'
        if not self.pending:
            return 'Wacht op een stille overgang tussen nummers.'
        if self.attempts >= 3:
            return 'Geen match na 3 pogingen · wacht op de volgende overgang.'
        if self.music_since is None:
            return 'Wacht op muziek.'
        delay = math.ceil(self.delay(now, interval))
        if delay:
            return f'Volgende herkenning over minimaal {delay} seconden.'
        return 'Muziek gehoord · herkenning starten…'


class LevelMeter:
    def __init__(self, source):
        self.source = source
        self.process = None
        self.last_samples = 0
        self.started = 0

    def close(self):
        process, self.process = self.process, None
        if process:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            process.stdout.close()

    def read(self):
        now = time.monotonic()
        if self.process and (self.process.poll() is not None or
                             now - max(self.last_samples, self.started) > 6):
            self.close()
        if self.process is None:
            self.process = subprocess.Popen([
                'pw-record', '--target', self.source, '--rate', '8000',
                '--channels', '1', '--format', 's16', '--raw', '-'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            os.set_blocking(self.process.stdout.fileno(), False)
            self.started = now
        data = bytearray()
        while len(data) < 64000:
            try:
                block = os.read(self.process.stdout.fileno(), 16000)
            except BlockingIOError:
                break
            if not block:
                break
            data.extend(block)
        if len(data) < 800:
            return None
        self.last_samples = now
        # Only the latest half-second matters for short gaps between songs.
        data = data[-8000:]
        samples = array.array('h', data[:len(data) // 2 * 2])
        mean = sum(samples) / len(samples)
        rms = math.sqrt(sum((sample - mean) ** 2 for sample in samples) / len(samples))
        return round(20 * math.log10(max(1, rms) / 32768), 1)

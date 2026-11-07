"""Read one growing cdparanoia WAV without confusing a temporary EOF with track end."""
import array
import os
import re
import struct
import sys
import threading
import time
import uuid

RATE = 44100
FRAME_BYTES = 4
BUFFER_FRAMES = RATE * 3


def wav_header(frames):
    size = frames * FRAME_BYTES
    return struct.pack('<4sI4s4sIHHIIHH4sI', b'RIFF', size+36, b'WAVE', b'fmt ',
                       16, 1, 2, RATE, RATE*FRAME_BYTES, FRAME_BYTES, 16, b'data', size)


class GrowingWav:
    def __init__(self, path, frames):
        self.path, self.frames = path, frames
        self.token = uuid.uuid4().hex
        self.lock = threading.RLock()
        self.fd = None
        self.complete = False
        self.error = None
        self.start_frame = None
        self.end_frame = frames
        self.scanned = 0
        self.first_sound = None

    def refresh(self, complete=False):
        with self.lock:
            if self.error: return
            if self.fd is None:
                try: fd = os.open(self.path, os.O_RDONLY)
                except FileNotFoundError: return
                if os.pread(fd, 44, 0) != wav_header(self.frames):
                    os.close(fd)
                    return  # Wait for the writer to finish its header.
                self.fd = fd
            available = min(self.frames, max(0, os.fstat(self.fd).st_size-44)//FRAME_BYTES)
            if complete:
                if available != self.frames: raise ValueError('Lokale WAV is onvolledig')
                self.complete = True
            # Detect only the initial silence, using the server's -60 dB/0.3 s policy.
            # Incremental scanning also handles a long silent intro without re-reading it.
            if self.start_frame is None:
                if self.first_sound is None and available > self.scanned:
                    offset = self.scanned
                    while offset < available:
                        count = min(16384, available-offset)
                        samples = array.array('h', os.pread(self.fd, count*4, 44+offset*4))
                        if sys.byteorder != 'little': samples.byteswap()
                        found = next((i//2 for i, value in enumerate(samples) if abs(value)>32), None)
                        if found is not None:
                            self.first_sound = offset+found
                            break
                        offset += count
                    self.scanned = available
                if self.first_sound is not None:
                    skip = max(0, self.first_sound-round(.1*RATE)) if self.first_sound>=round(.3*RATE) else 0
                    if available-skip >= min(BUFFER_FRAMES, self.frames-skip) or self.complete:
                        self.start_frame = skip
                elif self.complete:
                    self.start_frame = 0  # A wholly silent track remains a valid track.

    def playable(self):
        with self.lock: return self.fd is not None and self.start_frame is not None and not self.error

    def edges(self, removed_end):
        with self.lock:
            # Once the server has analysed the completed upload, omit its trailing silence
            # from the first local listen too. Start position is fixed before streaming.
            end = self.frames-max(0, int(removed_end))
            if end > (self.start_frame or 0): self.end_frame = end

    def fail(self, message='Het uitlezen is onderbroken'):
        with self.lock: self.error = message
        self.close()

    def close(self):
        with self.lock:
            if self.fd is not None: os.close(self.fd); self.fd = None

    def open(self):
        with self.lock:
            if not self.playable(): raise FileNotFoundError('Audio wordt nog gebufferd')
            # Each HTTP request owns a descriptor. Rename/unlink after upload is safe.
            return LiveReader(self, os.dup(self.fd), self.start_frame)


class LiveReader:
    def __init__(self, source, fd, start_frame):
        self.source, self.fd, self.start_frame = source, fd, start_frame
        self.header = wav_header(source.frames-start_frame)
        self.size = len(self.header)+(source.frames-start_frame)*FRAME_BYTES

    def close(self):
        if self.fd is not None: os.close(self.fd); self.fd = None

    def response_range(self, value):
        start, end = 0, self.size-1
        if value:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
            if not match or not any(match.groups()): raise ValueError('Ongeldig bytebereik')
            a,b = match.groups()
            if not a: start = max(0,self.size-int(b))
            else: start,end = int(a),min(end,int(b)) if b else end
            if start > end or start >= self.size: raise ValueError('Ongeldig bytebereik')
        return start,end

    def chunks(self, start, end):
        position = start
        deadline = time.monotonic()+120
        try:
            while position <= end:
                with self.source.lock:
                    error = self.source.error
                    complete = self.source.complete
                if error: raise OSError(error)
                if position < 44:
                    block = self.header[position:min(44,end+1)]
                else:
                    count = min(32768,end-position+1)
                    block = os.pread(self.fd, count, position+self.start_frame*4)
                if block:
                    yield block
                    position += len(block)
                    deadline = time.monotonic()+120
                elif complete:
                    raise OSError('Lokale audio is onvolledig')
                elif time.monotonic()>deadline:
                    raise TimeoutError('Het uitlezen van de cd reageert niet')
                else: time.sleep(.05)
        finally: self.close()

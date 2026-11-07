"""Private, resumable CD archive. Only complete, validated tracks become playable."""
import itertools
import hashlib
import hmac
import json
import logging
import os
import queue
import re
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import wave
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import silence

ROOT = Path(os.environ.get('ARCHIVE_DATA', '/data'))
MUSIC = Path(os.environ.get('ARCHIVE_MUSIC', '/music'))
TOKEN = os.environ.get('ARCHIVE_TOKEN', '')
PREFS = Path(os.environ.get('PLEX_PREFS', '/plex/Preferences.xml'))
PLEX = os.environ.get('PLEX_URL', 'http://plex:32400')
LOCK = threading.RLock()
JOBS = queue.Queue()
PENDING = set()
ID = re.compile(r'[A-Za-z0-9_.-]{8,100}\Z')


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try: return super().__exit__(*args)
        finally: self.close()


def connect():
    db = sqlite3.connect(ROOT / 'archive.sqlite', timeout=30, factory=ClosingConnection)
    db.row_factory = sqlite3.Row
    return db


def initialize():
    ROOT.mkdir(parents=True, exist_ok=True)
    MUSIC.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS plex_refresh(id INTEGER PRIMARY KEY CHECK(id=1),
          generation INTEGER NOT NULL DEFAULT 0, pending INTEGER NOT NULL DEFAULT 0,
          attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0, error TEXT);
        INSERT OR IGNORE INTO plex_refresh(id) VALUES(1);
        CREATE TABLE IF NOT EXISTS discs(id TEXT PRIMARY KEY, manifest TEXT NOT NULL, updated REAL);
        CREATE TABLE IF NOT EXISTS tracks(disc TEXT, number INTEGER, raw TEXT, path TEXT,
          sha256 TEXT, version TEXT, error TEXT, PRIMARY KEY(disc,number));
        ''')
        columns={r[1] for r in db.execute('PRAGMA table_info(tracks)')}
        for name,kind in [('trim_version','TEXT'),('trim_start_samples','INTEGER DEFAULT 0'),
                          ('trim_end_samples','INTEGER DEFAULT 0'),('sample_rate','INTEGER'),
                          ('duration_seconds','REAL')]:
            if name not in columns:db.execute(f'ALTER TABLE tracks ADD COLUMN {name} {kind}')


def enqueue(disc, number):
    with LOCK:
        if (disc, number) not in PENDING:
            PENDING.add((disc, number))
            JOBS.put((disc, number))


def validate_manifest(disc, data):
    if not ID.fullmatch(disc) or data.get('id') != disc:
        raise ValueError('Ongeldige cd-identificatie')
    tracks = data.get('tracks', [])
    if not isinstance(tracks, list) or not 1 <= len(tracks) <= 99:
        raise ValueError('Ongeldige tracklijst')
    nums = [t.get('number') for t in tracks]
    if any(type(n) is not int or not 1 <= n <= 99 for n in nums) or len(set(nums)) != len(nums):
        raise ValueError('Ongeldige tracknummers')
    for t in tracks:
        if type(t.get('sectors')) is not int or not 1 <= t['sectors'] <= 450000:
            raise ValueError('Tracklengte ontbreekt')
    for field in ['disc_number', 'disc_total']:
        if type(data.get(field, 1)) is not int or not 1 <= data.get(field, 1) <= 99:
            raise ValueError('Ongeldig schijfnummer')
    # Only persist metadata, never client paths, URLs or executable settings.
    return {k: data[k] for k in ['id', 'toc', 'title', 'artist', 'release', 'date',
            'disc_number', 'disc_total', 'tracks', 'metadata_status', 'ambiguous'] if k in data}


def metadata_version(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def register(disc, payload):
    data = validate_manifest(disc, payload)
    with LOCK, connect() as db:
        # Prefer an edition already represented by another disc in this archive.
        # Explicit user edition selection always wins.
        if not payload.get('release_selected'):
            known = {json.loads(r[0]).get('release') for r in db.execute('SELECT manifest FROM discs')}
            candidates = payload.get('releases', [])
            matched = next((r for r in candidates if r.get('id') in known), None)
            if matched and len(matched.get('tracks',[])) == len(data['tracks']):
                data.update(release=matched['id'],title=matched['title'],artist=matched['artist'],
                            date=matched.get('date',''),disc_number=matched.get('disc_number',1),
                            disc_total=matched.get('disc_total',1))
                for i,t in enumerate(data['tracks']):
                    t['title']=matched['tracks'][i]
                    t['artist']=(matched.get('track_artists') or [matched['artist']]*len(data['tracks']))[i]
        old = db.execute('SELECT manifest FROM discs WHERE id=?', (disc,)).fetchone()
        if old:
            previous = json.loads(old[0])
            if [(t['number'], t['sectors']) for t in previous['tracks']] != [
                    (t['number'], t['sectors']) for t in data['tracks']]:
                raise ValueError('Deze cd-identificatie hoort bij een andere schijfindeling')
            # On reinsertion, cached server metadata wins over the initial TOC-only snapshot.
            if not data.get('release') and (previous.get('release') or
                    (any(publishable(previous,t['number']) for t in previous['tracks']) and
                     not any(publishable(data,t['number']) for t in data['tracks']))):
                data = previous
        db.execute('INSERT INTO discs VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET '
                   'manifest=excluded.manifest,updated=excluded.updated',
                   (disc, json.dumps(data), time.time()))
        rows = db.execute('SELECT * FROM tracks WHERE disc=?', (disc,)).fetchall()
    for row in rows:
        if (row['version'] != metadata_version(data) or row['raw'] or row['trim_version']!=silence.POLICY
                or (row['path'] and Path(row['path'])!=destination(data,row['number']))):
            enqueue(disc, row['number'])
    return snapshot(disc)


def snapshot(disc):
    with LOCK, connect() as db:
        row = db.execute('SELECT manifest FROM discs WHERE id=?', (disc,)).fetchone()
        if not row:
            raise FileNotFoundError(disc)
        data = json.loads(row[0])
        stored = {r['number']: dict(r) for r in db.execute('SELECT * FROM tracks WHERE disc=?', (disc,))}
    for t in data['tracks']:
        r = stored.get(t['number'], {})
        ready = bool(r.get('path') and Path(r['path']).is_file())
        uploaded = ready or bool(r.get('raw') and Path(r['raw']).is_file())
        t.update(ready=ready, uploaded=uploaded, storage='ready' if ready else 'processing' if uploaded else 'pending',
                 archive_error=r.get('error'),awaiting_metadata=uploaded and not publishable(data,t['number']))
        if r.get('duration_seconds') is not None:
            t['original_seconds']=t['sectors']/75
            t['seconds']=r['duration_seconds']
            t['trim_start_seconds']=(r.get('trim_start_samples') or 0)/(r.get('sample_rate') or 44100)
            t['trim_end_seconds']=(r.get('trim_end_samples') or 0)/(r.get('sample_rate') or 44100)
    data['complete'] = all(t['ready'] for t in data['tracks'])
    data['stored'] = sum(t['ready'] for t in data['tracks'])
    return data


def audio_path(disc, number, raw=False):
    with connect() as db:
        r = db.execute('SELECT path,raw FROM tracks WHERE disc=? AND number=?', (disc, number)).fetchone()
    if r:
        for path in r if raw else [r['path']]:
            if path and Path(path).is_file():
                return Path(path)
    raise FileNotFoundError('Track is nog niet opgeslagen')


def safe_name(value):
    name = re.sub(r'[\x00-\x1f/\\:*?"<>|]', '_', str(value)).strip(' .')[:110]
    return name or 'Onbekend'


def publishable(manifest,number):
    """A saved recording is playable even when its metadata is not fit for Plex."""
    track=next(t for t in manifest['tracks'] if t['number']==number)
    album=str(manifest.get('title') or '').strip().casefold()
    title=str(track.get('title') or '').strip()
    artist=str(track.get('artist') or manifest.get('artist') or '').strip().casefold()
    return (artist not in ('','onbekende artiest','unknown artist','album wordt opgezocht…') and album not in ('','audio-cd','audio cd','onbekend album') and bool(title)
            and not re.fullmatch(r'(?:track|nummer)\s*\d+',title,re.I))


def destination(manifest, number):
    track = next(t for t in manifest['tracks'] if t['number'] == number)
    if not publishable(manifest,number):
        # This mount is outside Plex's /music library. Keep the sole permanent
        # file here until metadata arrives; the authenticated relay still works.
        return ROOT/'unmatched'/safe_name(manifest['id'])/f'{number:02d}.flac'
    release = manifest.get('release') or ('cd-' + manifest['id'])
    album = safe_name(manifest.get('title') or 'Onbekend album') + ' [' + safe_name(release) + ']'
    folder = MUSIC / safe_name(manifest.get('artist') or 'Onbekende artiest') / album
    return folder / f"{manifest.get('disc_number',1):02d}{number:02d} - {safe_name(track.get('title') or 'Track '+str(number))}.flac"


def plex_request(route, params=None, method='GET'):
    token = ET.parse(PREFS).getroot().get('PlexOnlineToken')
    req = urllib.request.Request(PLEX + route + ('?' + urllib.parse.urlencode(params) if params else ''),
        method=method, headers={'X-Plex-Token': token, 'Accept': 'application/xml'})
    with urllib.request.urlopen(req, timeout=20) as r:
        content = r.read()
    return ET.fromstring(content) if content else None


def refresh_plex():
    sections = plex_request('/library/sections')
    for section in sections:
        if section.get('type') == 'artist' and any(loc.get('path') == '/music' for loc in section):
            plex_request('/library/sections/' + section.get('key') + '/refresh')
            return
    raise RuntimeError('De Plex-muziekbibliotheek ontbreekt')


def schedule_plex_refresh():
    # One durable, coalesced job. New requests cannot be cleared by an older refresh.
    with connect() as db:
        db.execute('UPDATE plex_refresh SET pending=1,generation=generation+1 WHERE id=1')


def refresh_plex_once(now=None):
    now=time.time() if now is None else now
    with connect() as db:job=dict(db.execute('SELECT * FROM plex_refresh WHERE id=1').fetchone())
    if not job['pending'] or job['retry_at']>now:return False
    try:
        refresh_plex()
    except Exception as exc:
        attempts=job['attempts']+1
        with connect() as db:
            db.execute('UPDATE plex_refresh SET attempts=?,retry_at=?,error=? WHERE id=1',
                       (attempts,now+min(600,2**min(attempts,9)),type(exc).__name__))
    else:
        with connect() as db:
            db.execute('UPDATE plex_refresh SET pending=0,attempts=0,retry_at=0,error=NULL WHERE id=1 AND generation=?',
                       (job['generation'],))
    return True


def plex_refresh_loop():
    while True:
        try:refresh_plex_once()
        except Exception:logging.exception('Plex-verversing tijdelijk niet beschikbaar')
        time.sleep(1)


def reconcile_raw(limit=1000,seconds=10):
    """Recover validated owned WAVs after rename-before-commit crashes; never delete."""
    raw=ROOT/'raw'
    if not raw.is_dir() or raw.is_symlink():return 0
    recovered=0;deadline=time.monotonic()+seconds
    # Bounded scan; only exact own-layout paths, never symlinks or client paths.
    for folder in itertools.islice(raw.iterdir(),limit):
        if time.monotonic()>=deadline:break
        if folder.is_symlink() or not folder.is_dir() or not ID.fullmatch(folder.name):continue
        with connect() as db:
            row=db.execute('SELECT manifest FROM discs WHERE id=?',(folder.name,)).fetchone()
        if not row:continue
        manifest=json.loads(row[0])
        for track in manifest['tracks']:
            if time.monotonic()>=deadline:return recovered
            number=track['number'];path=folder/f'{number}.wav'
            if path.is_symlink() or not path.is_file():continue
            with LOCK,connect() as db:
                existing=db.execute('SELECT raw,path FROM tracks WHERE disc=? AND number=?',(folder.name,number)).fetchone()
                if existing and any(p and Path(p).is_file() for p in existing):continue
                try:
                    with wave.open(str(path),'rb') as wav:
                        frames=track['sectors']*588
                        if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate(),wav.getnframes())!=(2,2,44100,frames):continue
                        count=0
                        while True:
                            block=wav.readframes(65536)
                            if not block:break
                            count+=len(block)
                        if count!=frames*4:continue
                    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
                except (OSError,EOFError,wave.Error):continue
                db.execute('INSERT OR REPLACE INTO tracks(disc,number,raw,sha256) VALUES(?,?,?,?)',
                           (folder.name,number,str(path),digest))
            enqueue(folder.name,number);recovered+=1
    return recovered


def encode(disc, number):
    with LOCK, connect() as db:
        manifest = json.loads(db.execute('SELECT manifest FROM discs WHERE id=?', (disc,)).fetchone()[0])
        row = dict(db.execute('SELECT * FROM tracks WHERE disc=? AND number=?', (disc, number)).fetchone())
    src = audio_path(disc, number,raw=True)
    version = metadata_version(manifest)
    needs_trim=bool(row.get('raw')) or row.get('trim_version')!=silence.POLICY
    target = destination(manifest, number)
    if (row.get('version') == version and row.get('path') and Path(row['path'])==target
            and target.exists() and not needs_trim):
        if target.is_relative_to(MUSIC):schedule_plex_refresh()
        with connect() as db:
            db.execute('UPDATE tracks SET error=NULL WHERE disc=? AND number=?',(disc,number))
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name('.' + target.name + '.partial.flac')
    track = next(t for t in manifest['tracks'] if t['number'] == number)
    plan=silence.analyze(src) if needs_trim else None
    trimming=silence.audio_filter(plan) if plan else None
    removed_start=(row.get('trim_start_samples') or 0)+(plan['removed_start_samples'] if plan else 0)
    removed_end=(row.get('trim_end_samples') or 0)+(plan['removed_end_samples'] if plan else 0)
    duration=plan['duration_seconds'] if plan else row.get('duration_seconds')
    rate=plan['sample_rate'] if plan else row.get('sample_rate',44100)
    if (plan and not trimming and not row.get('raw') and row.get('version')==version
            and row.get('path')==str(target)):
        # Do not rewrite already correct FLACs just to mark a completed analysis.
        with LOCK,connect() as db:
            db.execute('UPDATE tracks SET trim_version=?,trim_start_samples=?,trim_end_samples=?, '
                       'sample_rate=?,duration_seconds=?,error=NULL WHERE disc=? AND number=?',
                       (silence.POLICY,removed_start,removed_end,rate,duration,disc,number))
        return True
    tags = {'title': track.get('title', f'Track {number}'), 'artist': track.get('artist') or manifest.get('artist',''),
            'album': manifest.get('title','Audio-cd'), 'album_artist': manifest.get('artist','Onbekende artiest'),
            'track': f'{number}/{len(manifest["tracks"])}',
            'disc': f'{manifest.get("disc_number",1)}/{manifest.get("disc_total",1)}',
            'date': manifest.get('date','')}
    release=manifest.get('release','')
    if re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',release):
        tags['MUSICBRAINZ_ALBUMID']=release
    elif re.fullmatch(r'discogs-[1-9][0-9]{0,11}',release):
        tags['DISCOGS_RELEASE_ID']=release.split('-')[1]
    cmd = ['ffmpeg','-nostdin','-v','error','-y','-i',str(src),'-map','0:a:0','-c:a','flac',
           '-sample_fmt','s16','-compression_level','5','-map_metadata','-1']
    if trimming:cmd += ['-af',trimming]
    for k, v in tags.items():
        cmd += ['-metadata', k + '=' + str(v)]
    cmd += [str(temporary)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        out_rate,out_frames=silence.probe(temporary)
        expected=round(duration*out_rate) if duration is not None else None
        if expected is not None and out_frames!=expected:
            raise RuntimeError('De ingekorte track heeft een onverwachte lengte')
        # Decode fully before replacing the sole permanent audio file.
        subprocess.run(['ffmpeg','-nostdin','-v','error','-xerror','-i',str(temporary),
                        '-map','0:a:0','-f','null','-'],check=True,capture_output=True,timeout=180)
        temporary.chmod(0o644)
        temporary.replace(target)
        version = metadata_version(manifest)
        with LOCK, connect() as db:
            db.execute('UPDATE tracks SET path=?,raw=NULL,version=?,error=NULL,trim_version=?, '
                       'trim_start_samples=?,trim_end_samples=?,sample_rate=?,duration_seconds=? '
                       'WHERE disc=? AND number=?',
                       (str(target),version,silence.POLICY,removed_start,removed_end,out_rate,
                        out_frames/out_rate,disc,number))
            latest = json.loads(db.execute('SELECT manifest FROM discs WHERE id=?', (disc,)).fetchone()[0])
        for old in [row.get('raw'), row.get('path')]:
            if old and Path(old) != target:
                Path(old).unlink(missing_ok=True)
        # Empty old album directories are safe to remove after an edition correction.
        if src.parent != target.parent:
            try: src.parent.rmdir()
            except OSError: pass
        if metadata_version(latest) != version:
            return False
        if target.is_relative_to(MUSIC) or src.is_relative_to(MUSIC):schedule_plex_refresh()
        return True
    finally:
        temporary.unlink(missing_ok=True)


def conversion_loop():
    while True:
        disc, number = JOBS.get()
        again = False
        try:
            again = not encode(disc, number)
        except Exception as exc:
            logging.exception('Archive conversion/Plex import failed: %s/%s', disc, number)
            with connect() as db:
                db.execute('UPDATE tracks SET error=? WHERE disc=? AND number=?',
                           ('Audioverwerking mislukt; wordt opnieuw geprobeerd', disc, number))
            again = True
            time.sleep(5)
        finally:
            with LOCK: PENDING.discard((disc, number))
            JOBS.task_done()
        if again:
            enqueue(disc, number)


def health_payload():
    commit=os.environ.get('ARCHIVE_RELEASE','')
    if not re.fullmatch(r'[0-9a-f]{40}',commit):commit=None
    return {'ok':True,'component':'cd-archive','release':{'commit':commit}}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        # Do not log tokens, query strings or metadata.
        logging.info('%s %s', self.command, self.path.split('?')[0])

    def json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if not TOKEN or not hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer ' + TOKEN):
            self.close_connection = True
            self.json(401, {'error':'Niet geautoriseerd'})
            return False
        return True

    def dispatch(self):
        if self.path == '/health' and self.command == 'GET':
            self.json(200, health_payload())
            return
        if not self.authorized(): return
        path = urllib.parse.urlsplit(self.path).path
        match = re.fullmatch(r'/v1/discs/([A-Za-z0-9_.-]{8,100})(?:/tracks/([1-9][0-9]?))?', path)
        if not match:
            self.json(404, {'error':'Niet gevonden'}); return
        disc, number = match.groups()
        number = int(number) if number else None
        try:
            if self.command == 'GET' and number is None:
                self.json(200, snapshot(disc))
            elif self.command == 'POST' and number is None:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 250000: raise ValueError('Ongeldige metadata')
                self.json(200, register(disc, json.loads(self.rfile.read(length))))
            elif self.command == 'PUT' and number is not None:
                self.upload(disc, number)
            elif self.command in ['GET','HEAD'] and number is not None:
                self.stream(audio_path(disc, number))
            else:
                self.json(405, {'error':'Ongeldige methode'})
        except FileNotFoundError:
            self.json(404, {'error':'Nog niet opgeslagen'})
        except (ValueError, json.JSONDecodeError, wave.Error) as exc:
            self.close_connection = True
            self.json(400, {'error':str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            logging.exception('Archive request failed')
            self.close_connection = True
            self.json(500, {'error':'Archief tijdelijk niet beschikbaar'})

    def upload(self, disc, number):
        manifest = snapshot(disc)
        track = next((t for t in manifest['tracks'] if t['number'] == number), None)
        if not track: raise ValueError('Onbekende track')
        length = int(self.headers.get('Content-Length','0'))
        if not 44 < length <= 1_100_000_000: raise ValueError('Ongeldige bestandsgrootte')
        digest = self.headers.get('X-Audio-SHA256','')
        if not re.fullmatch('[a-f0-9]{64}', digest): raise ValueError('Controlegetal ontbreekt')
        folder = ROOT / 'raw' / disc
        folder.mkdir(parents=True, exist_ok=True)
        temp = folder / f'{number}.{threading.get_ident()}.partial'
        target = folder / f'{number}.wav'
        try:
            sha = hashlib.sha256()
            remaining = length
            with temp.open('wb') as out:
                while remaining:
                    block = self.rfile.read(min(262144, remaining))
                    if not block: raise ValueError('Upload is afgebroken')
                    out.write(block); sha.update(block); remaining -= len(block)
                out.flush(); os.fsync(out.fileno())
            if not hmac.compare_digest(sha.hexdigest(), digest): raise ValueError('Uploadcontrole mislukt')
            with wave.open(str(temp),'rb') as wav:
                if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate()) != (2,2,44100):
                    raise ValueError('Geen cd-kwaliteit WAV')
                if wav.getnframes() != track['sectors'] * 588:
                    raise ValueError('Track is niet volledig uitgelezen')
                # Also verify actual data length, not only the WAV header.
                frames = 0
                while True:
                    block = wav.readframes(65536)
                    if not block: break
                    frames += len(block) // 4
                if frames != wav.getnframes(): raise ValueError('WAV is onvolledig')
            with LOCK, connect() as db:
                existing = db.execute('SELECT * FROM tracks WHERE disc=? AND number=?', (disc, number)).fetchone()
                if existing and any(existing[k] and Path(existing[k]).exists() for k in ['path','raw']):
                    # Idempotent retry: never overwrite a complete recording.
                    pass
                else:
                    temp.replace(target)
                    db.execute('INSERT OR REPLACE INTO tracks(disc,number,raw,sha256) VALUES(?,?,?,?)',
                               (disc,number,str(target),digest))
            enqueue(disc, number)
            self.json(200, snapshot(disc))
        finally:
            temp.unlink(missing_ok=True)

    def stream(self, path):
        # Open before stat: a completed WAV may be unlinked after FLAC conversion.
        with path.open('rb') as f:
            size = os.fstat(f.fileno()).st_size
            start, end = 0, size - 1
            value = self.headers.get('Range')
            if value:
                m = re.fullmatch(r'bytes=(\d*)-(\d*)',value)
                if not m or not any(m.groups()): raise ValueError('Ongeldig bytebereik')
                a,b = m.groups()
                if not a: start = max(0,size-int(b))
                else: start, end = int(a), min(size-1,int(b)) if b else size-1
                if start > end or start >= size:
                    self.send_response(416); self.send_header('Content-Range',f'bytes */{size}')
                    self.send_header('Content-Length','0'); self.end_headers(); return
            self.send_response(206 if value else 200)
            self.send_header('Content-Type','audio/flac' if path.suffix=='.flac' else 'audio/wav')
            self.send_header('Accept-Ranges','bytes')
            self.send_header('Content-Length',str(end-start+1))
            if value: self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            if self.command == 'HEAD': return
            f.seek(start)
            remaining = end-start+1
            while remaining:
                block = f.read(min(262144,remaining))
                if not block: break
                self.wfile.write(block); remaining -= len(block)

    do_GET = do_HEAD = do_POST = do_PUT = dispatch


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if len(TOKEN) < 32: raise RuntimeError('Set a strong ARCHIVE_TOKEN')
    initialize()
    reconcile_raw()
    with connect() as db:
        for r in db.execute('SELECT disc,number FROM tracks'):
            enqueue(*r)
    threading.Thread(target=conversion_loop, daemon=True).start()
    threading.Thread(target=plex_refresh_loop, daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0',8766), Handler).serve_forever()

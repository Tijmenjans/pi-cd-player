from state_store import write_text, write_json, read_text
from optical_reader import DriveBusy
from optical_device import optical_device, OpticalDeviceError
import json
import copy
import fcntl
import os
import re
import socket
import subprocess
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

import optical_disc as libdiscid
from runtime_settings import Settings
from release_info import read_release
from runtime_owner import RuntimeOwner
from maintenance_guard import guarded_action
import spotify
import plexamp
from dvd import DVD
import dvd_streaming
import audio
from vinyl import Vinyl
import catalogue
import disc_media
import music_metadata
from archive import Archive
from archive_queue import ArchiveQueue
from flask import Flask, jsonify, request, send_from_directory, abort, Response, stream_with_context

CODE_ROOT = Path(__file__).resolve().parent
SETTINGS = Settings.load()
ROOT = SETTINGS.install_root
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True)
app = Flask(__name__, static_folder=str(CODE_ROOT/'static'))
vinyl = Vinyl(ROOT)
lock = threading.RLock()
disc = {'present': False, 'tracks': [], 'loading': True}
source_file = DATA / 'source'
source = read_text(source_file, 'cd')
source = source if source in ('cd', 'spotify', 'plexamp', 'vinyl', 'dvd') else 'cd'
streaming_source_file = DATA / 'streaming-source'
streaming_source = read_text(streaming_source_file, 'spotify')
streaming_source = streaming_source if streaming_source in ('spotify', 'plexamp') else 'spotify'


def service(action, name):
    subprocess.run(['systemctl', '--user', action, 'cdspeler-' + name + '.service'],
                   check=True, timeout=15, capture_output=True)


def mpd(*commands):
    with socket.create_connection((SETTINGS.mpd_host, SETTINGS.mpd_port), timeout=4) as sock:
        f = sock.makefile('rwb')
        if not f.readline().startswith(b'OK MPD'):
            raise RuntimeError('De cd-speler reageert niet.')
        result = []
        for command in commands:
            # Optical drives may need several seconds to seek or spin up.
            sock.settimeout(20 if command.split(' ', 1)[0] in
                            ('seekcur', 'play', 'next', 'previous', 'stop', 'clear') else 5)
            f.write((command + '\n').encode())
            f.flush()
            rows = []
            while True:
                line = f.readline().decode(errors='replace').strip()
                if line == 'OK':
                    break
                if not line or line.startswith('ACK'):
                    raise RuntimeError(line or 'Verbinding met de cd-speler verbroken.')
                rows.append(line)
            result.append(rows)
        return result


archive = Archive(ROOT)
dvd = DVD(ROOT, observe=False, optical=archive.optical)
queue = ArchiveQueue(mpd, DATA / "archive-queue.json", archive)

def values(rows):
    return dict(row.split(': ', 1) for row in rows if ': ' in row)


transition_lock = threading.RLock()
transition = {'active': False, 'target': None, 'error': None}
status_cache = {}

def choose_source(new):
    with transition_lock:
        return _choose_source(new)

def _choose_source(new):
    global source, streaming_source
    if dvd.is_streaming() and new != source:
        raise RuntimeError('Stop eerst de VLC-stream op de Apple TV.')
    if new == 'dvd':
        archive.cancel()
        if archive.reading():raise RuntimeError('De optische drive is nog bezig. Wacht tot de opdracht klaar is.')
    if new == 'spotify' and not (DATA / 'soloist.env').exists():
        raise RuntimeError('Spotify moet nog eenmalig worden ingesteld met je persoonlijke Soloist-sleutel.')
    if new == 'plexamp' and not plexamp.configured():
        raise RuntimeError('Plexamp moet nog eenmalig aan je Plex-account worden gekoppeld.')
    if new == 'vinyl' and not vinyl.connected():
        raise RuntimeError('Sluit eerst de UFO202 aan op de Pi.')
    previous, previous_streaming = source, streaming_source
    engines = {'cd': 'mpd', 'spotify': 'spotify', 'plexamp': 'plexamp', 'vinyl': 'vinyl'}
    old_files = {path: read_text(path, None) for path in (source_file, streaming_source_file)}
    transition.update(active=True, target=new, error=None)
    started = False
    try:
        for name, engine in engines.items():
            if name != new:service('stop', engine)
        if new == 'spotify' and previous != new:
            write_json(DATA / 'spotify.json', {'state':'ready'})
        if new in engines:
            started=True
            service('start', engines[new])
        if new == 'cd':
            deadline=time.monotonic()+30
            while True:
                try:mpd('ping');break
                except (OSError, RuntimeError):
                    if time.monotonic()>=deadline:raise RuntimeError('De cd-speler kon niet opstarten.')
                    time.sleep(.2)
            queue.reset_engine()
        write_text(source_file,new)
        if new in ('spotify','plexamp'):write_text(streaming_source_file,new)
        vinyl.set_active(new=='vinyl')
        dvd.set_active(new=='dvd')
        with lock:
            queue.last=None
            source=new
            if new in ('spotify','plexamp'):streaming_source=new
    except Exception as exc:
        errors=[]
        if started and new!=previous and new in engines:
            try:service('stop',engines[new])
            except Exception:errors.append('doeldienst stoppen')
        if previous in engines:
            try:service('start',engines[previous])
            except Exception:errors.append('vorige dienst starten')
        for path,value in old_files.items():
            try:
                if value is None:path.unlink(missing_ok=True)
                else:write_text(path,value)
            except OSError:errors.append('instellingen herstellen')
        for adapter,active in ((vinyl,previous=='vinyl'),(dvd,previous=='dvd')):
            try:adapter.set_active(active)
            except Exception:errors.append('bronstatus herstellen')
        with lock:source,streaming_source=previous,previous_streaming
        transition['error']='Bronwissel mislukt.' + (' Herstel onvolledig: '+', '.join(errors)+'.' if errors else ' Vorige bron hersteld.')
        raise RuntimeError(transition['error']) from exc
    finally:
        transition['active']=False


def get_json(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'CDSpeler/1.0 (personal Raspberry Pi player)',
        'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=12) as response:
        return json.load(response)


# Preserve the parser entry point used by the API tests.
release_metadata=music_metadata.release_metadata
metadata_jobs={}
musicbrainz_lock=threading.Lock()
musicbrainz_last_request=0.0


def get_musicbrainz_json(url):
    global musicbrainz_last_request
    # MusicBrainz permits one request per second. Keep this lock completely
    # separate from the player lock and optical drive.
    with musicbrainz_lock:
        time.sleep(max(0,1.1-(time.monotonic()-musicbrainz_last_request)))
        musicbrainz_last_request=time.monotonic()
        return get_json(url)


def metadata_wait(snapshot,job,seconds):
    deadline=time.monotonic()+seconds
    while not runtime_stop.is_set():
        with lock:
            if disc.get('id')!=snapshot['id'] or metadata_jobs.get(snapshot['id']) is not job:
                return False
        remaining=deadline-time.monotonic()
        if remaining<=0:return True
        time.sleep(min(1,remaining))


def enrich(snapshot):
    job=object()
    with lock:metadata_jobs[snapshot['id']]=job
    delays=(5,15,30,60,120,300)
    attempt=0
    try:
        while not runtime_stop.is_set():
            with lock:
                if disc.get('id')!=snapshot['id'] or metadata_jobs.get(snapshot['id']) is not job:return
            retry=enrich_once(snapshot,job)
            if not retry:return
            delay=delays[min(attempt,len(delays)-1)];attempt+=1
            with lock:
                if disc.get('id')==snapshot['id']:
                    disc['metadata_retry_at']=time.time()+delay
            if not metadata_wait(snapshot,job,delay):return
    finally:
        with lock:
            if metadata_jobs.get(snapshot['id']) is job:metadata_jobs.pop(snapshot['id'],None)


def publish_metadata(snapshot,updates,job=None):
    with lock:
        if (disc.get('id')!=snapshot['id'] or
                (job is not None and metadata_jobs.get(snapshot['id']) is not job)):
            return
        effective=disc_media.apply_text({**disc,**updates},disc.get('disc_media',{}))
        if effective!=disc:
            disc.update(effective)
            archive.metadata(disc)


def enrich_once(snapshot,job=None):
    cache = DATA / (snapshot['id'] + '.json')
    try:
        try:metadata=json.loads(cache.read_text()) if cache.exists() else {}
        except (OSError,ValueError):metadata={}
        if not isinstance(metadata,dict):metadata={}
        if not metadata.get('releases'):
            alternate=catalogue.lookup(snapshot,CODE_ROOT/'catalogue')
            if alternate:metadata=alternate
        # Existing good metadata/explicit choices survive network outages. An old
        # negative result must not suppress the new broader lookup.
        fresh_negative=(metadata.get('lookup_version')==music_metadata.LOOKUP_VERSION
                        and metadata.get('toc')==snapshot.get('toc')
                        and time.time()-metadata.get('looked_up_at',0)<86400)
        if not metadata.get('releases') and not fresh_negative:
            metadata=music_metadata.lookup(snapshot,get_musicbrainz_json)
            metadata.update(toc=snapshot.get('toc'),looked_up_at=time.time())
        # Atomic writes keep a restart or failed write from corrupting the cache.
        with lock:
            if job is not None and metadata_jobs.get(snapshot['id']) is not job:return False
            try:chosen=json.loads(cache.read_text()).get('selected')
            except (OSError,ValueError,AttributeError):chosen=None
            if chosen and any(r['id']==chosen for r in metadata.get('releases',[])):
                metadata['selected']=chosen
            write_json(cache,metadata)
        releases = metadata.get('releases', [])
        preferred = metadata.get('selected')
        automatic=releases[0] if releases and (metadata.get('match_kind')!='toc' or len(releases)==1) else None
        release=next((r for r in releases if r['id']==preferred),automatic)
        updates = {'releases': releases, 'metadata_status': 'found' if release else ('choose' if releases else 'unknown'),
                   'metadata_error':None,'metadata_retry_at':None,
                   'metadata_match':metadata.get('match_kind','catalogue'),
                   'release_selected':bool(metadata.get('selected'))}
        if not release:
            updates.update(title='Audio-cd',artist='Onbekende artiest')
        if release:
            updates.update(title=release['title'], artist=release['artist'], release=release['id'],
                           disc_number=release.get('disc_number',1),disc_total=release.get('disc_total',1),
                           date=release.get('date',''),ambiguous=len(releases)>1)
            updates['tracks'] = [dict(t, title=release['tracks'][i] or t['title'],
                                     artist=(release.get('track_artists') or [
                                         release['artist'] if release['artist'] != 'Various Artists'
                                         else 'Onbekende artiest'] * len(snapshot['tracks']))[i])
                                 for i, t in enumerate(snapshot['tracks'])]
            cover = DATA / (release['id'] + '-1200.jpg')
            if not cover.exists():
                small_cover=DATA/(release['id']+'.jpg')
                updates['cover']='/cover/'+small_cover.name if small_cover.exists() else None
                # Names are useful immediately; an image timeout must not delay
                # titles or their registration with the storage server.
                publish_metadata(snapshot,updates,job)
                try:
                    url='https://coverartarchive.org/release/'+release['id']+'/front-1200'
                    if re.fullmatch(r'discogs-[1-9][0-9]{0,11}',release['id']):
                        entry=get_json('https://api.discogs.com/releases/'+release['id'].split('-')[1])
                        url=next(i['uri'] for i in entry.get('images',[]) if i.get('type')=='primary')
                        if not url.startswith('https://i.discogs.com/'):raise ValueError('Ongeldige coverbron')
                    req = urllib.request.Request(url,headers={'User-Agent': 'CDSpeler/1.0'})
                    with urllib.request.urlopen(req, timeout=12) as response:
                        image = response.read(3_000_001)
                        if len(image) <= 3_000_000:
                            cover.write_bytes(image)
                except Exception:
                    pass
            small_cover = DATA / (release['id'] + '.jpg')
            updates['cover'] = '/cover/' + cover.name if cover.exists() else (
                '/cover/' + small_cover.name if small_cover.exists() else None)
        publish_metadata(snapshot,updates,job)
        return False
    except Exception as exc:
        retry=isinstance(exc,(urllib.error.URLError,TimeoutError,ConnectionError,json.JSONDecodeError))
        if isinstance(exc,urllib.error.HTTPError):retry=exc.code in (408,429) or exc.code>=500
        # Do not label programming/cache/server errors as a lost connection.
        kind=('HTTP '+str(exc.code)) if isinstance(exc,urllib.error.HTTPError) else type(exc).__name__
        app.logger.warning('Metadata lookup %s: %s; retry=%s',snapshot['id'],kind,retry)
        with lock:
            if (disc.get('id') == snapshot['id'] and
                    (job is None or metadata_jobs.get(snapshot['id']) is job)):
                known=bool(disc.get('release') or disc.get('metadata_source')=='cdtext')
                disc['metadata_status']='found' if known else ('retrying' if retry else 'error')
                disc['metadata_error']=('Albuminformatie tijdelijk niet bereikbaar. Opnieuw proberen…' if retry
                                        else 'Albuminformatie kon niet worden verwerkt.')
                if not known and disc.get('artist')=='Album wordt opgezocht…':
                    disc['artist']='Onbekende artiest'
        return retry


def media_changed():
    """Detect reinsertion of the same disc, even between two scans."""
    try:
        fd = os.open(optical_device(), os.O_RDONLY | os.O_NONBLOCK)
        try:
            return bool(fcntl.ioctl(fd, 0x5325, 0x7fffffff))  # CDROM_MEDIA_CHANGED
        finally:
            os.close(fd)
    except OSError:
        return True


def accept_disc(snapshot, autoplay):
    global disc
    with transition_lock:
        with lock:disc=snapshot
        queue.attach(snapshot,reset=autoplay)
        if autoplay:
            try:
                choose_source('cd')
                mpd('stop','clear')
                load_queue()
                queue.action(snapshot,'play',{})
                if queue.data.get('shuffle'):queue.action(snapshot,'shuffle',{'enabled':True})
            except Exception:
                app.logger.exception('Automatic CD playback failed')
                with lock:disc['autoplay_error']='Automatisch starten is niet gelukt. Druk op afspelen om opnieuw te proberen.'


def verified_disc_media(snapshot):
    with archive.optical.acquire() as lease:
        return _verified_disc_media(snapshot, lease)

def _verified_disc_media(snapshot, lease):
    media=disc_media.cached_probe(snapshot,DATA,lease_fd=lease.fileno())
    # A user may have swapped the CD while its slow lead-in was being read.
    # Do not apply or retain that result under the previous disc's identity.
    try: current=libdiscid.read(optical_device(),features=libdiscid.FEATURE_READ)
    except libdiscid.DiscError: current=None
    if current is None or current.id!=snapshot['id'] or str(current.toc)!=snapshot['toc']:
        (DATA/(snapshot['id']+'-disc-media.json')).unlink(missing_ok=True)
        return None
    return media


def prepare_disc(snapshot):
    """Read CD-Text before attaching either the player queue or optical ripper."""
    media=verified_disc_media(snapshot)
    if media is None:return None
    return disc_media.apply_text({**snapshot,'disc_media':media},media)


def scan_loop():
    global disc
    last = None
    initialized = False
    while not runtime_stop.is_set():
        try:
            # Only one process reads the drive. TOC/metadata polling must not seek
            # over a track currently being extracted.
            if transition['active'] or source == 'dvd' or dvd.busy() or archive.reading():
                time.sleep(1)
                continue
            try:
                with archive.optical.acquire():
                    changed = media_changed()
                    cd = None if initialized and last is not None and not changed else libdiscid.read(optical_device(), features=libdiscid.FEATURE_READ)
                if cd is None:
                    time.sleep(1)
                    continue
            except DriveBusy:
                time.sleep(1)
                continue
            # A drive may leave MEDIA_CHANGED set until the rip finishes.
            # The TOC identity, not that flag, decides whether to reset playback.
            # A real removal already clears last in the DiscError handler.
            if cd.id != last:
                snapshot = {'present': True, 'loading': False, 'id': cd.id,
                            'toc': str(cd.toc),
                            'disc_number':1,'disc_total':1,
                            'title': 'Audio-cd', 'artist': 'Album wordt opgezocht…',
                            'metadata_status': 'loading', 'releases': [], 'cover': None,
                            'tracks': [{'number': i + cd.first_track, 'title': 'Track ' + str(i + cd.first_track),
                                        'seconds': round(sectors / 75), 'sectors':int(sectors)}
                                       for i, sectors in enumerate(cd.track_lengths)]}
                # Stop the previous generation before reading the lead-in: an
                # old reader must not start another track during the CD-Text query.
                archive.cancel()
                with lock:
                    disc={'present':False,'loading':True,'tracks':[],
                          'metadata_status':'reading_cdtext'}
                snapshot=prepare_disc(snapshot)
                if snapshot is None:
                    last=None
                    time.sleep(1)
                    continue
                # Establish a baseline at startup without restarting an already
                # inserted disc or interrupting Spotify on a webapp restart.
                accept_disc(snapshot, autoplay=initialized)
                last = cd.id
                threading.Thread(target=enrich, args=(dict(snapshot),), daemon=True).start()
        except OpticalDeviceError as exc:
            with lock:disc={'present':False,'loading':False,'tracks':[],'scan_error':str(exc)}
            last=None
        except libdiscid.DiscError:
            with transition_lock:
                archive.cancel()
                if last is not None and source == 'cd':
                    try:mpd('stop', 'clear')
                    except Exception:pass
                with lock:disc = {'present': False, 'loading': False, 'tracks': []}
            last = None
        except Exception:
            with lock:
                disc['loading'] = False
                disc['scan_error'] = 'De cd kan momenteel niet worden gelezen.'
        initialized = True
        time.sleep(1)


def load_queue():
    if not disc.get('present'):
        raise RuntimeError('Plaats eerst een audio-cd.')
    queue.ensure(disc)


def queue_loop():
    while not runtime_stop.is_set():
        try:
            with transition_lock:
                if not transition['active'] and source == 'cd' and disc.get('present'):
                    queue.observe(disc)
        except Exception:
            app.logger.warning('Queue monitor temporarily unavailable')
        time.sleep(0.5)


@app.before_request
def protect_changes():
    if request.method == 'POST':
        # Same-origin requests only; no cross-site form posts or permissive CORS.
        if not request.is_json or request.headers.get('X-CDSpeler') != '1':
            abort(403)
        origin = request.headers.get('Origin')
        if origin and origin != request.host_url.rstrip('/'):
            abort(403)


@app.get('/')
def index():
    return send_from_directory(CODE_ROOT / 'static', 'index.html')


@app.get('/cover/<name>')
def cover(name):
    if not re.fullmatch(r'(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|discogs-[1-9][0-9]{0,11})(?:-1200)?\.jpg', name):
        abort(404)
    return send_from_directory(DATA, name, max_age=86400)


@app.route('/audio/<disc_id>/<int:number>',methods=['GET','HEAD'])
def audio_stream(disc_id,number):
    # This relay is local to MPD. A LAN browser cannot extract the archive key
    # or use the player as a general-purpose proxy into the private archive.
    if request.remote_addr not in ('127.0.0.1','::1'):
        abort(403)
    if not re.fullmatch(r'[A-Za-z0-9_.-]{8,100}',disc_id) or not 1<=number<=99:
        abort(404)
    local_token=request.args.get('local')
    if local_token is not None:
        try: reader=archive.local_audio(disc_id,number,local_token)
        except FileNotFoundError: abort(404)
        try: start,end=reader.response_range(request.headers.get('Range'))
        except ValueError:
            size=reader.size;reader.close()
            return Response(status=416,headers={'Content-Range':f'bytes */{size}'})
        headers={'Content-Type':'audio/wav','Content-Length':str(end-start+1),
                 'Accept-Ranges':'bytes','Cache-Control':'no-store'}
        ranged=bool(request.headers.get('Range'))
        if ranged: headers['Content-Range']=f'bytes {start}-{end}/{reader.size}'
        if request.method=='HEAD':
            reader.close()
            return Response(status=206 if ranged else 200,headers=headers)
        response=Response(stream_with_context(reader.chunks(start,end)),
                          status=206 if ranged else 200,headers=headers)
        response.call_on_close(reader.close)
        return response
    try:
        upstream=archive.cloud.audio(disc_id,number,request.headers.get('Range'),request.method=='HEAD')
    except urllib.error.HTTPError as exc:
        abort(exc.code if exc.code in (404,416) else 502)
    except OSError:
        abort(502)
    def chunks():
        try:
            while True:
                block=upstream.read(65536)
                if not block: break
                yield block
        finally:
            upstream.close()
    headers={k:v for k,v in upstream.headers.items() if k.lower() in
             ('content-type','content-length','content-range','accept-ranges')}
    if request.method=='HEAD':
        upstream.close()
        return Response(status=upstream.status,headers=headers)
    return Response(stream_with_context(chunks()),status=upstream.status,headers=headers)


@app.get('/api/plexamp/cover/<digest>')
def plexamp_cover(digest):
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        abort(404)
    cached = plexamp.cover(digest)
    if not cached:
        abort(404)
    data, kind = cached
    return Response(data, mimetype=kind, headers={'Cache-Control': 'private, max-age=3600'})


@app.get('/dvd/art/<filename>')
def dvd_cover(filename):
    if not re.fullmatch(r'[a-f0-9]{32}\.jpg',filename):abort(404)
    return send_from_directory(ROOT/'data/dvd-metadata',filename,max_age=86400)


@app.get('/dvd/live.mkv')
@app.get('/dvd/live.mpg')
def dvd_live_stream():
    with transition_lock:
        if source != 'dvd':return jsonify(error='Kies eerst DVD.'),409
        try:token=dvd.reserve_stream()
        except RuntimeError as exc:return jsonify(error=str(exc)),409
    child=None
    try:
        with dvd.io_lock:
            with dvd.lock:
                if dvd.session!=token:raise RuntimeError('Stream geannuleerd')
            media=dvd.probe()
            if not media:raise RuntimeError('Geen leesbare video-dvd')
            streams=dvd_streaming.inspect(ROOT/'vendor/dvd/usr/bin/ffprobe',optical_device(),media['main_title'],dvd.env(),pass_fds=dvd.lease_fds())
            command=dvd_streaming.remux_command(ROOT/'vendor/dvd/usr/bin/ffmpeg',optical_device(),media['main_title'],streams)
            child=subprocess.Popen(command,env=dvd.env(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,pass_fds=dvd.lease_fds())
            dvd.attach_stream(token,child,media)
    except Exception:
        if child:dvd._stop(child)
        dvd.finish_stream(token)
        return jsonify(error='De dvd-stream kon niet starten.'),503
    def frames():
        try:
            while True:
                data=child.stdout.read(32768)
                if not data:break
                yield data
        finally:
            child.stdout.close()
            dvd.finish_stream(token)
    return Response(frames(),mimetype='video/x-matroska',headers={'Cache-Control':'no-store','Accept-Ranges':'none'})


@app.get('/health')
def health():
    return jsonify(ok=True,component='pi-player',release=read_release(ROOT))

@app.get('/ready')
def ready():
    active=bool(runtime_threads) and not runtime_stop.is_set() and all(t.is_alive() for t in runtime_threads)
    return jsonify(ok=active,component='pi-player',release=read_release(ROOT)),200 if active else 503

@app.get('/api/version')
def version():
    return jsonify(read_release(ROOT))

@app.get('/api/status')
def status():
    if not transition_lock.acquire(blocking=False):
        with lock:
            cached=copy.deepcopy(status_cache) if status_cache.get('source')==source else {'source':source,'streaming_source':streaming_source,'disc':copy.deepcopy(disc),'player':{'state':'stop','buffering':True},'output':audio.snapshot()}
            cached['transition']=dict(transition)
            cached['release']=read_release(ROOT)
        return jsonify(cached)
    try:
        with lock:
            current_source=source
            current_streaming=streaming_source
            current_disc=copy.deepcopy(disc)
        return _status_snapshot(current_source,current_streaming,current_disc)
    finally:transition_lock.release()

def _status_snapshot(source,streaming_source,disc):
    result = {'source': source, 'streaming_source': streaming_source, 'disc': copy.deepcopy(disc), 'player': {}, 'device': 'CDspeler', 'output': audio.snapshot(), 'transition':dict(transition), 'release':read_release(ROOT)}
    saved=archive.snapshot()
    result['archive']=saved
    if source == 'cd' and saved.get('drive_blocked'):result['error']=saved.get('error')
    if saved.get('metadata') and saved['metadata'].get('release'):
        result['disc'].update(saved['metadata'])
    for track in result['disc'].get('tracks',[]):
        remote=dict(saved.get('track_metadata',{}).get(track['number'],{}))
        # The server may still describe the pre-lookup snapshot until a
        # conversion/upload completes. Keep new names; use server durations
        # and trim offsets independently of metadata readiness.
        if track.get('title') and not re.fullmatch(r'(?:Track|Nummer)\s*\d+',track['title'],re.I):
            remote.pop('title',None)
        if track.get('artist') and track['artist'] not in ('Onbekende artiest','Album wordt opgezocht…'):
            remote.pop('artist',None)
        track.update(remote)
        track.update(saved['states'].get(track['number'],{'ready':False,'storage':'pending'}))
    result['disc']=disc_media.apply_text(result['disc'],disc.get('disc_media',{}))
    if source == 'cd' and disc.get('scan_error'):result['error']=disc['scan_error']
    if source == 'cd' and disc.get('autoplay_error'):
        result['error'] = disc['autoplay_error']
    if source == 'cd':
        try:
            if disc.get('present'):
                result['player'], result['queue'] = queue.observe(disc)
            else:
                result['player'] = values(mpd('status')[0])
            p = result['player']
            # MPD enters play before the drive has delivered its first audio.
            p['buffering'] = p.get('buffering') or p.get('state') == 'play' and (
                not p.get('audio') or float(p.get('elapsed', 0)) <= 0)
            if result['player'].get('error'):
                result['error'] = 'De cd kon niet worden afgespeeld. Controleer de cd en probeer opnieuw.'
        except Exception:
            result['error'] = 'De cd-speler start nog op.'
    elif source == 'dvd':
        result['dvd'] = dvd.snapshot()
        result['player'] = {'state': 'stop'}
    elif source == 'vinyl':
        result['vinyl'] = vinyl.snapshot()
        result['output'] = result['vinyl']['monitor']
        result['player'] = {'state': 'stop', 'volume': 100}
    else:
        result[source] = plexamp.snapshot() if source == 'plexamp' else spotify.snapshot()
        sp = result[source]
        result['player'] = {
            'state': {'playing': 'play', 'paused': 'pause'}.get(sp['state'], 'stop'),
            'volume': sp.get('volume', 50), 'elapsed': sp.get('elapsed', 0),
            'buffering': sp['state'] == 'buffering',
            'duration': sp.get('seconds', 0)}
    with lock:
        status_cache.clear();status_cache.update(copy.deepcopy(result))
    return jsonify(result)

@app.post('/api/action')
@guarded_action(ROOT/'.deployment.lock')
def action():
    try:
        payload = request.get_json()
        cmd = payload.get('action')
        if cmd == 'volume':
            raise ValueError('Het uitgangsvolume staat vast op 100%. Gebruik de versterker om het volume te regelen.')
        if cmd == 'source':
            new=payload.get('source')
            if new not in ('cd','spotify','plexamp','vinyl','dvd'):raise ValueError('Onbekende bron.')
            choose_source(new)
            return jsonify(ok=True)
        with transition_lock:
            if transition['active']:raise RuntimeError('Wacht tot de bronwissel klaar is.')
            if cmd == 'dvd-stop':
                if source != 'dvd':raise ValueError('Kies eerst DVD.')
                dvd.stop_stream()
                return jsonify(ok=True)
            if cmd == 'archive-retry':
                if source != 'cd':raise ValueError('Kies eerst CD.')
                archive.retry_failed()
                return jsonify(ok=True)
            if cmd == 'eject':
                if source == 'dvd':
                    dvd.eject()
                    return jsonify(ok=True)
                archive.cancel()
                if source == 'cd':
                    queue.last = None
                    mpd('stop', 'clear')
                with archive.optical.acquire() as lease:
                    subprocess.run(['eject', optical_device()], check=True, timeout=12, capture_output=True,pass_fds=(lease.fileno(),))
                return jsonify(ok=True)
            if cmd == 'release':
                selected = payload.get('release')
                if not any(r['id'] == selected for r in disc.get('releases', [])):
                    raise ValueError('Onbekende albumuitgave.')
                cache = DATA / (disc['id'] + '.json')
                data = json.loads(cache.read_text())
                data['selected'] = selected
                write_json(cache,data)
                threading.Thread(target=enrich, args=(dict(disc),), daemon=True).start()
                return jsonify(ok=True)
            if cmd in ('vinyl-recognize', 'vinyl-auto', 'vinyl-interval'):
                if source != 'vinyl':
                    raise ValueError('Kies eerst Vinyl als bron.')
                if cmd == 'vinyl-recognize':
                    vinyl.start()
                elif cmd == 'vinyl-auto':
                    vinyl.set_automatic(payload.get('enabled'))
                else:
                    vinyl.set_interval(payload.get('seconds'))
                return jsonify(ok=True)
            if source == 'vinyl':
                raise ValueError('Bedien het afspelen op je platenspeler.')
            if source == 'plexamp':
                plexamp.command(cmd, seconds=payload.get('seconds'))
                return jsonify(ok=True)
            if source == 'spotify':
                simple = {'play': 'play', 'pause': 'pause', 'stop': 'pause',
                          'next': 'skip_next', 'previous': 'skip_prev'}
                if cmd in simple:
                    spotify.command(simple[cmd])
                elif cmd == 'seek':
                    seconds = float(payload['seconds'])
                    if not 0 <= seconds <= 86400:
                        raise ValueError('Ongeldige positie.')
                    spotify.command('seek', position_ms=round(seconds * 1000))
                elif cmd == 'volume':
                    level = int(payload['volume'])
                    if not 0 <= level <= 100:
                        raise ValueError('Ongeldig volume.')
                    spotify.command('set_volume', volume=level)
                else:
                    raise ValueError('Onbekende Spotify-opdracht.')
                return jsonify(ok=True)
            if cmd in ('play', 'pause', 'stop', 'track', 'next', 'previous',
                       'shuffle', 'queue-order', 'queue-skip'):
                if not disc.get('present'):
                    raise ValueError('Plaats eerst een audio-cd.')
                queue.action(disc, cmd, payload)
                disc.pop('autoplay_error', None)
            elif cmd == 'seek':
                seconds = float(payload['seconds'])
                if not 0 <= seconds <= 7200:
                    raise ValueError('Ongeldige positie.')
                mpd('seekcur ' + str(seconds))
            else:
                raise ValueError('Onbekende opdracht.')
        return jsonify(ok=True)
    except Exception as exc:
        app.logger.warning('Action failed: %s', exc)
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else 'De opdracht is niet gelukt. Probeer opnieuw.'
        return jsonify(error=message), 400


runtime_stop = threading.Event()
runtime_threads = []
runtime_lock = threading.Lock()
runtime_owner = RuntimeOwner(DATA/'runtime.lock')

def start_runtime():
    global source
    with runtime_lock:
        if runtime_threads:return
        runtime_owner.acquire()
        try:
            runtime_stop.clear();archive.stopping.clear()
            if source=='vinyl' and not vinyl.connected():source='cd'
            choose_source(source)
            workers=[archive.run,archive.upload_loop,archive.monitor,scan_loop,queue_loop,
                     lambda: audio.observe(runtime_stop),lambda: vinyl.observe(runtime_stop),
                     lambda: spotify.observe(runtime_stop),
                     lambda: plexamp.observe(lambda:source=='plexamp',runtime_stop),
                     lambda: plexamp.observe_metadata(runtime_stop),lambda: dvd.observe(runtime_stop)]
            for worker in workers:
                thread=threading.Thread(target=worker,daemon=True)
                runtime_threads.append(thread);thread.start()
        except BaseException:
            if not runtime_threads:runtime_owner.release()
            raise

def stop_runtime(timeout=8):
    with runtime_lock:
        runtime_stop.set();archive.stopping.set();archive.wake.set();archive.upload_wake.set();dvd.wake.set()
        def cleanup():
            try:archive.cancel()
            finally:
                try:dvd.stop_stream()
                finally:vinyl.meter.close()
        if runtime_threads:
            cleanup_thread=threading.Thread(target=cleanup,daemon=True)
            runtime_threads.append(cleanup_thread);cleanup_thread.start()
        deadline=time.monotonic()+timeout
        for thread in runtime_threads:thread.join(max(0,deadline-time.monotonic()))
        runtime_threads[:]=[thread for thread in runtime_threads if thread.is_alive()]
        if not runtime_threads:runtime_owner.release()
        return not runtime_threads

if __name__ == '__main__':
    import signal
    def terminate(signum,frame):raise SystemExit(0)
    signal.signal(signal.SIGTERM,terminate)
    try:
        start_runtime()
        app.run(host=SETTINGS.web_host, port=SETTINGS.web_port, threaded=True, debug=False)
    finally:stop_runtime()

from optical_device import optical_device, OpticalDeviceError
"""One optical reader; bounded WAV staging; authenticated, idempotent cloud uploads."""
import copy
import hashlib
import http.client
import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from state_store import write_json
from runtime_settings import Settings
from live_audio import GrowingWav, RATE
from optical_reader import OpticalLease, ProgressWatchdog, ReadFailure, ReaderStalled, DriveBusy, stop_process


class Cloud:
    def __init__(self, path):
        data = json.loads(Path(path).read_text())
        self.base = data['url'].rstrip('/')
        self.token = data['token']
        if not self.base.startswith('https://'):
            raise ValueError('Het archief vereist HTTPS')

    def headers(self):
        return {'Authorization': 'Bearer ' + self.token}

    def request(self, route, data=None):
        headers = self.headers()
        if data is not None: headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.base+route, data=json.dumps(data).encode() if data is not None else None,
                                     headers=headers)
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.load(response)

    def upload(self, disc, number, path, digest=None, progress=None):
        parsed = urllib.parse.urlsplit(self.base)
        if digest is None:
            with path.open('rb') as f:
                digest = hashlib.file_digest(f, 'sha256').hexdigest()
        size = path.stat().st_size
        conn = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=20)
        started=time.monotonic()
        deadline=started+min(900,max(120,size/65536+60))
        try:
            conn.putrequest('PUT', parsed.path + f'/v1/discs/{disc}/tracks/{number}')
            for k,v in {**self.headers(), 'Content-Type':'audio/wav',
                        'Content-Length':str(size),'X-Audio-SHA256':digest}.items():
                conn.putheader(k,v)
            conn.endheaders()
            sent = 0
            with path.open('rb') as f:
                for block in iter(lambda:f.read(262144),b''):
                    if time.monotonic()>deadline:raise TimeoutError('Upload duurt te lang')
                    conn.send(block)
                    sent += len(block)
                    if progress: progress(round(100 * sent / size))
            response = conn.getresponse()
            data = json.loads(response.read())
            if response.status != 200: raise RuntimeError(data.get('error','Upload mislukt'))
            return data
        finally:
            conn.close()

    def audio(self, disc, number, byte_range=None, head=False):
        headers = self.headers()
        if byte_range: headers['Range'] = byte_range
        return urllib.request.urlopen(urllib.request.Request(
            self.base+f'/v1/discs/{disc}/tracks/{number}',headers=headers,
            method='HEAD' if head else 'GET'), timeout=30)


class Archive:
    def __init__(self, root):
        self.root = Path(root)
        self.audio_base_url = Settings.load(code_root=self.root,environ={k:v for k,v in os.environ.items() if k!='CDSPELER_ROOT'}).audio_base_url
        self.stage = self.root/'data'/'rip-staging'
        self.stage.mkdir(parents=True,exist_ok=True)
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.disc = None
        self.order = []
        self.states = {}
        self.remote = None
        self.error = None
        self.process = None
        self.generation = 0
        self.registered = None
        self.cloud = Cloud(self.root/'data'/'archive.json')
        self.upload_wake = threading.Event()
        self.uploads = queue.Queue()
        self.slots = threading.BoundedSemaphore(2)
        self.inflight = set()
        self.stopping = threading.Event()
        self.retry_after = {}
        self.reader_error = None
        self.upload_error = None
        self.server_error = None
        self.buffer_full = False
        self.registration_lock = threading.Lock()
        self.initial_status = threading.Event()
        self.drive_blocked = False
        self.recovery_path = self.root/'data'/'archive-recovery.json'
        try:self.recovery=json.loads(self.recovery_path.read_text())
        except (OSError,ValueError):self.recovery={}
        if not isinstance(self.recovery,dict):self.recovery={}
        self.failures=self.recovery.get('failures',{})
        if not isinstance(self.failures,dict):self.failures={}
        self.failures={key:value for key,value in self.failures.items() if isinstance(key,str) and type(value) is int and 0<=value<=3}
        self.drive_halted=self.recovery.get('drive_halted') is True
        self.drive_stalls=set(x for x in self.recovery.get('drive_stalls',[]) if isinstance(x,str)) if isinstance(self.recovery.get('drive_stalls',[]),list) else set()
        self.drive_blocked=self.drive_halted
        self.speed_limit=self.recovery.get('speed_limit',4)
        if type(self.speed_limit) is not int or not 1<=self.speed_limit<=48:self.speed_limit=4
        self.optical=OpticalLease(self.stage/'optical.lock',self.root/'vendor/ripping/usr/bin/cdparanoia')
        try: self.skipped = json.loads((self.root/'data'/'archive-skipped.json').read_text())
        except (OSError, ValueError): self.skipped = {}
        self.local = {}
        self.selected_local = None
        self.metrics_path = self.root/'data'/'archive-metrics.json'
        try: self.metrics = json.loads(self.metrics_path.read_text())[-80:]
        except (OSError, ValueError): self.metrics = []
        # Optional explicit setting; safe SuperDrive fallback is 4x.
        config = json.loads((self.root/'data'/'archive.json').read_text())
        self.rip_speed = config.get('rip_speed')
        if self.rip_speed is not None and (type(self.rip_speed) is not int or not 1 <= self.rip_speed <= 48):
            raise ValueError('Ongeldige uitleessnelheid')

    def attach(self, disc):
        with self.lock:
            if not self.disc or self.disc['id'] != disc['id']:
                self.cancel()
                self.disc = copy.deepcopy(disc)
                self.order = [t['number'] for t in disc['tracks']]
                self.states = {n:{'storage':'pending','ready':False} for n in self.order}
                for n in self.skipped.get(disc['id'], []):
                    if n in self.states:
                        self.states[n] = {'storage':'skipped','ready':False}
                self.remote = None
                self.registered = None
                self.initial_status = threading.Event()
                self.reader_error=None;self.upload_error=None;self.server_error=None
                for n in self.order:
                    count=self.failures.get(self._failure_key(disc['id'],n),0)
                    if count>=3 and self.states[n]['storage']!='skipped':
                        self.states[n]={'storage':'blocked','ready':False,'attempts':count,'message':'Automatisch herstel gestopt na drie leespogingen; overige nummers gaan door.'}
                self.error = None
                self.wake.set()

    def metadata(self, disc):
        with self.lock:
            if self.disc and self.disc['id'] == disc.get('id'):
                self.disc = copy.deepcopy(disc)
                self.registered = None
                self.wake.set()

    def cancel(self):
        with self.lock:
            self.generation += 1
            for live in self.local.values():live.fail()
            self.local.clear();self.selected_local=None
            proc=self.process;self.disc=None;self.buffer_full=False
            self.wake.set();self.upload_wake.set()
        stopped=stop_process(proc)
        with self.lock:
            if self.process is proc and stopped:self.process=None
            if not stopped:
                self._halt_drive()
                self.reader_error='De USB-cd-drive reageert niet op stoppen. Sluit de drive opnieuw aan; opgeslagen nummers blijven bewaard.'

    @staticmethod
    def _failure_key(identity,number):return identity+':'+str(number)

    def _save_recovery(self):
        self.recovery.update(failures=self.failures,speed_limit=self.speed_limit,drive_halted=self.drive_halted,drive_stalls=sorted(self.drive_stalls)[-30:])
        write_json(self.recovery_path, self.recovery, durable=True)

    def _halt_drive(self):
        self.drive_halted=True;self.drive_blocked=True
        try:self._save_recovery()
        except OSError:logging.warning('Driveblokkade kon niet worden bewaard')

    def _read_failed(self,identity,number,message):
        key=self._failure_key(identity,number)
        count=self.failures.get(key,0)+1;self.failures[key]=count
        speed=min(self.rip_speed or 4,self.speed_limit)
        self.speed_limit=next((n for n in (8,4,2,1) if n<speed),1)
        try:self._save_recovery()
        except OSError:logging.warning('Leesherstelstatus kon niet worden opgeslagen')
        self.retry_after[(identity,number)]=time.monotonic()+min(300,30*count)
        self.reader_error=f'Nummer {number}: {message}. Andere nummers worden eerst opgeslagen.'
        self.states[number]={'storage':'blocked' if count>=3 else 'error','ready':False,'attempts':count,'message':self.reader_error,'retry_speed':self.speed_limit}

    def retry_failed(self):
        with self.lock:
            if self.reading():raise RuntimeError('Wacht tot de huidige leesopdracht klaar is of sluit een vastgelopen USB-drive opnieuw aan.')
            if not self.disc:raise RuntimeError('Plaats eerst een cd.')
            optical_device()  # Sysfs/access check only; never a media ioctl.
            failures=dict(self.failures);retry_after=dict(self.retry_after);states=copy.deepcopy(self.states)
            for number,state in states.items():
                if state.get('storage') in ('blocked','error') and not state.get('uploaded'):
                    failures.pop(self._failure_key(self.disc['id'],number),None)
                    retry_after.pop((self.disc['id'],number),None)
                    states[number]={'storage':'pending','ready':False}
            recovery={**self.recovery,'failures':failures,'speed_limit':self.speed_limit,
                      'drive_halted':False,'drive_stalls':[]}
            # A failed disk write must never re-enable the optical reader in memory.
            write_json(self.recovery_path,recovery,durable=True)
            self.recovery=recovery;self.failures=failures;self.retry_after=retry_after;self.states=states
            self.drive_halted=False;self.drive_stalls.clear();self.reader_error=None;self.drive_blocked=False
            self.wake.set()

    def can_detach(self):
        """A manual eject may keep a complete local pin, never truncate a growing one."""
        with self.lock:
            pinned=next((live for live in self.local.values() if live.token==self.selected_local),None)
            return pinned is None or pinned.complete

    def unavailable(self,number):
        with self.lock:
            return (self.states.get(number,{}).get('storage')=='blocked'
                    or bool(self.disc and self.disc.get('ejected')
                            and self.initial_status.is_set() and self.remote
                            and self.remote.get('id')==self.disc['id'] and not self.server_error
                            and not self.playable(number)
                            and not self.states.get(number,{}).get('uploaded')
                            and (self.disc['id'],number) not in self.inflight))

    def prioritize(self, numbers):
        with self.lock:
            all_numbers = [t['number'] for t in self.disc['tracks']] if self.disc else []
            order = list(dict.fromkeys([n for n in numbers if n in all_numbers]+all_numbers))
            if order != self.order:
                self.order = order
                self.wake.set()

    def ready(self, number):
        with self.lock: return bool(self.states.get(number,{}).get('ready'))

    def playable(self, number):
        with self.lock:
            live = self.local.get(number)
            return self.ready(number) or bool(live and live.playable())

    def _cleanup_local(self):
        for number,live in list(self.local.items()):
            if self.ready(number) and live.token != self.selected_local:
                live.close()
                del self.local[number]

    def playback_uri(self, number):
        with self.lock:
            uri=self.server_uri(number)
            live=self.local.get(number)
            # Keep the active local source pinned for the whole track, even
            # when its uploaded copy becomes ready on the server.
            pinned=bool(live and live.token==self.selected_local and live.playable())
            if self.ready(number) and not pinned:
                self.selected_local=None
            else:
                live=self.local.get(number)
                if not live or not live.playable(): raise RuntimeError('Audio wordt nog gebufferd')
                self.selected_local=live.token
                uri+='?local='+live.token
            self._cleanup_local()
            return uri

    def server_uri(self, number):
        with self.lock:return f'{self.audio_base_url}/audio/{self.disc["id"]}/{number}'

    def release_playback(self):
        with self.lock:
            self.selected_local=None
            self._cleanup_local()

    def local_audio(self, identity, number, token):
        with self.lock:
            live=self.local.get(number)
            if not self.disc or self.disc['id']!=identity or not live or live.token!=token:
                raise FileNotFoundError('Deze lokale audio is niet meer beschikbaar')
            return live.open()

    def local_end_seconds(self, number):
        with self.lock:
            live=self.local.get(number)
            if live and live.token==self.selected_local and live.complete and live.start_frame is not None:
                return (live.end_frame-live.start_frame)/RATE
            return None

    def snapshot(self):
        with self.lock:
            read_messages=[v.get('message') for v in self.states.values() if v.get('storage') in ('error','blocked') and v.get('message')]
            upload_messages=[v.get('message') for v in self.states.values() if v.get('storage')=='retrying_upload' and v.get('message')]
            self.error=('De USB-cd-drive reageert niet. Sluit de drive opnieuw aan; alle opgeslagen nummers blijven bewaard.' if self.drive_blocked else next(iter(read_messages),None) or next(iter(upload_messages),None) or self.server_error)
            result = {'disc_id':self.disc.get('id') if self.disc else None,
                      'states':copy.deepcopy(self.states),'error':self.error,
                      'buffer_full':self.buffer_full,'buffer_message':'Lokale buffer vol; wacht op de muziekserver.' if self.buffer_full else None,
                      'drive_blocked':self.drive_blocked,'reader_active':bool(self.process is not None and self.process.poll() is None),'speed':min(self.rip_speed or 4,self.speed_limit),
                      'blocked':sum(s.get('storage')=='blocked' for s in self.states.values()),
                      'stored':sum(bool(s.get('ready')) for s in self.states.values()),
                      'total':len(self.states)}
            result['skipped'] = sum(s.get('storage') == 'skipped' for s in self.states.values())
            result['timings'] = copy.deepcopy(self.metrics[-3:])
            for number,state in result['states'].items():
                state['playable']=self.playable(number)
                if self.disc and self.disc.get('ejected') and self.unavailable(number):
                    state['storage']='unavailable'
                    state['message']='Niet bewaard; plaats de cd opnieuw om dit nummer te beluisteren.'
            if self.remote:
                result['awaiting_metadata']=sum(bool(t.get('awaiting_metadata')) for t in self.remote.get('tracks',[]))
                result['metadata'] = {k:self.remote[k] for k in ['release','title','artist','date','disc_number','disc_total'] if k in self.remote}
                result['track_metadata'] = {t['number']:{k:t[k] for k in
                                            ['title','artist','seconds','trim_start_seconds','trim_end_seconds'] if k in t}
                                            for t in self.remote.get('tracks',[])}
            return result

    def reading(self):
        with self.lock:
            if self.process is not None and self.process.poll() is None:return True
        return self.optical.busy()

    def monitor(self):
        # Check immediately on attach, independently of the optical reader.
        while not self.stopping.is_set():
            with self.lock:
                manifest=copy.deepcopy(self.disc);generation=self.generation
            if not manifest:
                self.stopping.wait(.1)
                continue
            try:
                if self._register(manifest,generation):
                    self._receive(self.cloud.request('/v1/discs/'+manifest['id']),generation)
            except Exception:
                with self.lock:self.server_error='Muziekserver tijdelijk onbereikbaar; lokale bestanden blijven bewaard.'
            self.stopping.wait(1.5)

    def _receive(self, payload, generation):
        with self.lock:
            if generation != self.generation: return
            self.remote = payload
            for t in payload['tracks']:
                if t.get('uploaded') or t.get('ready'):
                    self.failures.pop(self._failure_key(payload['id'],t['number']),None)
                    self.states[t['number']] = {'ready':bool(t.get('ready')),'uploaded':True,
                                               'storage':'ready' if t.get('ready') else 'processing','progress':100,
                                               'archive_error':t.get('archive_error')}
                    # A previous shutdown may have left a confirmed uploaded WAV.
                    # Never unlink a file while the upload worker still needs it.
                    if (payload['id'],t['number']) not in self.inflight:
                        (self.stage/(payload['id']+'-'+str(t['number'])+'.wav')).unlink(missing_ok=True)
                live=self.local.get(t['number'])
                if live and t.get('ready'):
                    live.edges(round(t.get('trim_end_seconds',0)*RATE))
            self._cleanup_local()
            self.server_error = None
            if not any(v.get('storage') in ('error','blocked') for v in self.states.values()) and not self.drive_blocked:self.reader_error=None

    def _metric(self, disc, number, phase, seconds, size):
        with self.lock:
            self.metrics.append({'disc':disc,'track':number,'phase':phase,
                                 'seconds':round(seconds,3),'bytes':size,'at':time.time()})
            self.metrics=self.metrics[-80:]
            try:write_json(self.metrics_path, self.metrics)
            except OSError:logging.warning('Timinggegevens konden niet worden opgeslagen')

    def _rip(self, disc, number, generation, target):
        sectors=next(t['sectors'] for t in disc['tracks'] if t['number']==number)
        expected=sectors*2352+44
        if shutil.disk_usage(self.stage).free<expected+128_000_000:raise RuntimeError('Te weinig ruimte op de Pi om een nummer uit te lezen')
        device=optical_device()
        binary=self.root/'vendor/ripping/usr/bin/cdparanoia'
        if not binary.exists():raise RuntimeError('De cd-ripper is nog niet geïnstalleerd')
        lease=self.optical.acquire()
        with self.lock:
            if not self.drive_halted:self.drive_blocked=False
        partial=target.with_suffix('.partial.wav');partial.unlink(missing_ok=True)
        live=GrowingWav(partial,sectors*588);proc=None;finished=False;buffered=False
        started=time.monotonic()
        try:
            env=dict(os.environ,LD_LIBRARY_PATH=str(self.root/'vendor/ripping/usr/lib/arm-linux-gnueabihf'))
            with (self.stage/'last-rip.log').open('wb') as stderr:
                with self.lock:
                    if generation!=self.generation or not self.disc or self.disc.get('ejected') or self.drive_halted:return False
                    old=self.local.get(number)
                    if old:old.fail()
                    self.local[number]=live
                    config=json.loads((self.root/'data/archive.json').read_text())
                    requested=config.get('rip_speed',self.rip_speed) or 4
                    if type(requested) is not int or not 1<=requested<=48:raise ValueError('Ongeldige uitleessnelheid')
                    speed=min(requested,self.speed_limit);self.rip_speed=requested
                    self.states[number]={'storage':'ripping','ready':False,'progress':0,'speed':speed,'attempts':self.failures.get(self._failure_key(disc['id'],number),0)+1}
                    command=[str(binary),'-d',device,'-X','-w','-n','8','-S',str(speed),str(number),str(partial)]
                    # The reader inherits the flock. Even an uninterruptible child
                    # keeps the optical lease after the web process is restarted.
                    proc=subprocess.Popen(command,env=env,stdout=subprocess.DEVNULL,stderr=stderr,pass_fds=(lease.fileno(),))
                    self.process=proc
                watch=ProgressWatchdog(sectors/75,speed)
                while proc.poll() is None:
                    with self.lock:
                        if generation!=self.generation:return False
                        size=partial.stat().st_size if partial.exists() else 0
                        idle=watch.check(size)
                        state=self.states.get(number,{})
                        if not state.get('uploaded'):state.update(progress=min(99,round(100*size/expected)),idle_seconds=idle)
                        live.refresh()
                        if live.playable() and not buffered:
                            self._metric(disc['id'],number,'buffer',time.monotonic()-started,size);buffered=True
                    self.stopping.wait(.3)
                    if self.stopping.is_set():return False
                if proc.returncode:raise ReadFailure('De cd-drive heeft een leesfout gemeld')
                if partial.stat().st_size!=expected:raise ReadFailure('Het nummer is onvolledig uitgelezen')
                with wave.open(str(partial),'rb') as wav:
                    if wav.getnframes()!=sectors*588 or wav.getnchannels()!=2 or wav.getsampwidth()!=2 or wav.getframerate()!=44100:raise ReadFailure('Het nummer is onvolledig uitgelezen')
                live.refresh(complete=True);partial.replace(target);finished=True
                return True
        finally:
            stopped=stop_process(proc)
            with self.lock:
                if self.process is proc and stopped:self.process=None
                if not stopped:
                    self._halt_drive()
                    self.reader_error='De USB-cd-drive reageert niet op stoppen. Sluit de drive opnieuw aan; opgeslagen nummers blijven bewaard.'
                if not finished:
                    live.fail('Het uitlezen van dit nummer is onderbroken')
                    if self.local.get(number) is live:del self.local[number]
            # Do not unlock explicitly: an unkillable child still owns this lease.
            lease.close()
            if stopped:partial.unlink(missing_ok=True)

    def _register(self, disc, generation, strict=False):
        signature=json.dumps(disc,sort_keys=True)
        with self.registration_lock:
            with self.lock:
                if generation!=self.generation:return False
                if self.registered==signature:return True
            try:
                payload=self.cloud.request('/v1/discs/'+disc['id'],disc)
                self._receive(payload,generation)
                with self.lock:
                    if generation!=self.generation:return False
                    self.registered=signature
                return True
            except Exception:
                with self.lock:
                    if generation==self.generation:self.server_error='Muziekserver tijdelijk onbereikbaar; lokaal afspelen en veilig bewaren blijven mogelijk.'
                if strict:raise
                return False
            finally:
                with self.lock:
                    if generation==self.generation:self.initial_status.set()

    def _produce_once(self):
        """Reserve one of two staging slots, then read at most one optical track."""
        reserved = False
        queued = False
        number = None
        did_read = False
        with self.lock:
            if not self.disc or self.disc.get('ejected'): return False
            disc = copy.deepcopy(self.disc)
            generation = self.generation
        try:
            # Registration failure must not prevent local playback or WAV reuse.
            reserved = self.slots.acquire(timeout=.2)
            if not reserved:
                with self.lock:self.buffer_full=True
                return False
            with self.lock:self.buffer_full=False
            with self.lock:
                if generation != self.generation or not self.disc or self.disc.get('ejected'): return False
                pending=[n for n in self.order if not self.states.get(n,{}).get('uploaded')
                         and n not in self.skipped.get(disc['id'], [])
                         and not self.ready(n) and (disc['id'],n) not in self.inflight
                         and (not self.drive_halted or (self.stage/(disc['id']+'-'+str(n)+'.wav')).exists())
                         and (self.failures.get(self._failure_key(disc['id'],n),0)<3 or (self.stage/(disc['id']+'-'+str(n)+'.wav')).exists())
                         and self.retry_after.get((disc['id'],n),0)<time.monotonic()]
                if not pending: return False
                number=pending[0]
                self.inflight.add((disc['id'],number))
            target=self.stage/(disc['id']+'-'+str(number)+'.wav')
            if target.exists():
                try:
                    with wave.open(str(target),'rb') as wav:
                        if target.stat().st_size < 44+wav.getnframes()*4:raise ValueError('Onvolledig WAV-bestand')
                        if wav.getnframes()!=next(t['sectors']*588 for t in disc['tracks'] if t['number']==number) or wav.getnchannels()!=2 or wav.getsampwidth()!=2 or wav.getframerate()!=44100:raise ValueError('Onvolledig bestand')
                except (OSError,ValueError,EOFError,wave.Error):target.unlink(missing_ok=True)
            if not target.exists():
                if self.drive_halted:return False
                started=time.monotonic()
                if not self._rip(disc,number,generation,target): return False
                did_read=True
                self._metric(disc['id'],number,'rip',time.monotonic()-started,target.stat().st_size)
            elif number not in self.local:
                frames=next(t['sectors']*588 for t in disc['tracks'] if t['number']==number)
                live=GrowingWav(target,frames);live.refresh(complete=True)
                with self.lock:
                    if generation != self.generation:
                        live.close();return False
                    self.local[number]=live
            with self.lock:
                if did_read and self.drive_stalls and not self.drive_halted:
                    self.drive_stalls.clear()
                    try:self._save_recovery()
                    except OSError:logging.warning('Herstelvoortgang kon niet worden bewaard')
            # Hash once in the reader worker, independently of the network transfer.
            with target.open('rb') as f:
                digest=hashlib.file_digest(f,'sha256').hexdigest()
            with self.lock:
                if generation != self.generation: return False
                self.states[number]={'storage':'queued','ready':False,'progress':0}
            self.uploads.put({'disc':disc['id'],'number':number,'generation':generation,
                              'path':target,'digest':digest})
            queued=True
            self.upload_wake.set()
            return True
        except Exception as exc:
            logging.warning('CD reader: %s',exc)
            with self.lock:
                if generation==self.generation:
                    if isinstance(exc,DriveBusy):
                        self.reader_error=str(exc)
                        self.retry_after[(disc['id'],number)]=time.monotonic()+1
                    elif number is not None:
                        if isinstance(exc,ReadFailure):
                            if isinstance(exc,ReaderStalled):
                                self.drive_stalls.add(self._failure_key(disc['id'],number))
                                if len(self.drive_stalls)>=2:self._halt_drive()
                            self._read_failed(disc['id'],number,str(exc))
                        else:
                            self.reader_error=(str(exc) if isinstance(exc,(OpticalDeviceError,RuntimeError)) else 'Lokale opslag of configuratie niet beschikbaar; volledige bestanden blijven bewaard.')
                            self.states[number]={'storage':'error','ready':False,'message':self.reader_error}
                            self.retry_after[(disc['id'],number)]=time.monotonic()+30
                    else:self.server_error='Registratie bij de muziekserver mislukt; wordt opnieuw geprobeerd.'
            return False
        finally:
            if reserved and not queued:
                with self.lock:
                    if number is not None: self.inflight.discard((disc['id'],number))
                self.slots.release()

    def _upload_one(self, job):
        identity,number,generation=job['disc'],job['number'],job['generation']
        target=job['path'];retained=False
        try:
            with self.lock:
                if generation!=self.generation:return
                if not self.states.get(number,{}).get('uploaded'):
                    self.states[number]={'storage':'uploading','ready':False,'progress':0,'attempts':job.get('attempts',0)+1}
            with self.lock:manifest=copy.deepcopy(self.disc)
            if not self._register(manifest,generation,strict=True):return
            with self.lock:confirmed=bool(self.states.get(number,{}).get('uploaded'))
            if confirmed:
                target.unlink(missing_ok=True);return
            if job.get('retry'):
                payload=self.cloud.request('/v1/discs/'+identity)
                if any(t['number']==number and t.get('uploaded') for t in payload['tracks']):
                    self._receive(payload,generation);target.unlink(missing_ok=True);self.upload_error=None;return
            def progress(percent):
                with self.lock:
                    if generation==self.generation and self.states.get(number,{}).get('storage')=='uploading':self.states[number]['progress']=percent
            started=time.monotonic();size=target.stat().st_size
            payload=self.cloud.upload(identity,number,target,digest=job['digest'],progress=progress)
            if not any(t['number']==number and t.get('uploaded') for t in payload['tracks']):raise RuntimeError('De server heeft het bestand nog niet bevestigd')
            self._metric(identity,number,'upload',time.monotonic()-started,size)
            self._receive(payload,generation);target.unlink(missing_ok=True)
            with self.lock:self.upload_error=None
        except Exception as exc:
            logging.warning('CD upload: %s',exc)
            with self.lock:
                if generation==self.generation and target.exists():
                    job['retry']=True;job['attempts']=job.get('attempts',0)+1
                    delay=min(60,2**min(job['attempts'],6));job['not_before']=time.monotonic()+delay
                    self.upload_error='Upload tijdelijk onderbroken; volledige bestanden blijven lokaal bewaard. Nieuwe poging volgt automatisch.'
                    self.states[number]={'storage':'retrying_upload','ready':False,'message':self.upload_error,'attempts':job['attempts'],'retry_seconds':delay}
                    self.uploads.put(job);retained=True
                elif generation==self.generation:
                    self.states[number]={'storage':'pending','ready':False}
                    self.retry_after[(identity,number)]=time.monotonic()+15
        finally:
            if not retained:
                with self.lock:self.inflight.discard((identity,number))
                self.slots.release();self.buffer_full=False;self.wake.set()

    def upload_loop(self):
        while not self.stopping.is_set():
            try:job=self.uploads.get(timeout=.5)
            except queue.Empty:continue
            try:
                if job.get('not_before',0)>time.monotonic() and job['generation']==self.generation:
                    self.uploads.put(job);self.stopping.wait(.25)
                else:self._upload_one(job)
            finally:self.uploads.task_done()

    def _await_initial_status(self, timeout=2):
        # A healthy server can suppress redundant reads; an offline server may
        # delay the first local read by at most this small fixed grace period.
        with self.lock:event=self.initial_status if self.disc else None
        return event.wait(timeout) if event is not None else False

    def run(self):
        waited_generation=None
        while not self.stopping.is_set():
            self.wake.clear()
            with self.lock:generation=self.generation if self.disc else None
            if generation is not None and generation!=waited_generation:
                self._await_initial_status()
                waited_generation=generation
            if self.stopping.is_set():break
            if not self._produce_once():
                self.wake.wait(1)

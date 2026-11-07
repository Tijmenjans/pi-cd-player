from optical_reader import OpticalLease, DriveBusy, stop_process
from optical_device import optical_device, OpticalDeviceError
"""Local DVD information and a single VLC stream. No archive or staging files."""
import copy,os,subprocess,threading,uuid,xml.etree.ElementTree as ET
from pathlib import Path
from dvd_metadata import MovieMetadata
LANGUAGES={'nl':'Nederlands','en':'Engels','fr':'Frans','it':'Italiaans','de':'Duits','es':'Spaans','pt':'Portugees','ja':'Japans','und':'Onbekend'}

def parse_disc(xml):
 start=xml.find('<lsdvd>')
 if start<0:return None
 tree=ET.fromstring(xml[start:]);titles=tree.findall('track')
 if not titles:return None
 longest=tree.findtext('longest_track')
 main=next((t for t in titles if t.findtext('ix')==longest),max(titles,key=lambda t:float(t.findtext('length') or 0)))
 langs=lambda key:list(dict.fromkeys(s.findtext('langcode','und').lower() for s in main.findall(key)))
 subtitles=langs('subp');audio=langs('audio')
 return {'disc_id':tree.findtext('dvddiscid') or '', 'title':(tree.findtext('title') or 'DVD').replace('_',' ').strip(),'titles':len(titles),'main_title':int(main.findtext('ix') or 1),'seconds':float(main.findtext('length') or 0),'chapters':len(main.findall('chapter')),'width':int(main.findtext('width') or 0),'height':int(main.findtext('height') or 0),'aspect':main.findtext('aspect') or '', 'audio_languages':[LANGUAGES.get(v,v.upper()) for v in audio],'subtitle_languages':[LANGUAGES.get(v,v.upper()) for v in subtitles],'dutch_subtitles':any(v in ('nl','nld','dut') for v in subtitles)}

class DVD:
 def __init__(self,root,observe=False,optical=None):
  self.root=Path(root);self.lock=threading.RLock();self.io_lock=threading.RLock();self.wake=threading.Event()
  self.movies=MovieMetadata(root)
  self.active=False;self.media=None;self.session=None;self.proc=None;self.ejecting=False;self.error=None;self.checked=False
  stage=self.root/'data/rip-staging';stage.mkdir(parents=True,exist_ok=True)
  self.optical=optical or OpticalLease(stage/'optical.lock',self.root/'vendor/ripping/usr/bin/cdparanoia')
  self.lease=None
  if observe:threading.Thread(target=self.observe,daemon=True).start()
 def env(self):return dict(os.environ,LD_LIBRARY_PATH=str(self.root/'vendor/dvd/usr/lib')+':'+str(self.root/'vendor/dvd/usr/lib/arm-linux-gnueabihf'))
 def set_active(self,on):self.active=on;self.wake.set()
 def busy(self):return self.is_streaming() or self.ejecting
 def is_streaming(self):
  with self.lock:return self.session is not None
 def snapshot(self):
  with self.lock:
   return {**copy.deepcopy(self.media or {}),'movie':self.movies.get(self.media) if self.media else None,'title':(self.media or {}).get('title','DVD'),'state':'ejecting' if self.ejecting else 'streaming' if self.session else 'detected' if self.media else 'absent' if self.checked else 'checking','present':bool(self.media),'streaming':self.session is not None,'error':self.error,'available':(self.root/'vendor/dvd/usr/bin/ffmpeg').exists()}
 def lease_fds(self):return (self.lease.fileno(),) if self.lease else ()
 def probe(self):
  p=subprocess.run([str(self.root/'vendor/dvd/usr/bin/lsdvd'),'-x','-Ox',optical_device()],env=self.env(),capture_output=True,text=True,timeout=25,pass_fds=self.lease_fds())
  return parse_disc(p.stdout) if p.returncode==0 else None
 def observe(self,stop=None):
  stop=stop or threading.Event()
  while not stop.is_set():
   self.wake.wait(10);self.wake.clear()
   if stop.is_set():break
   if not self.active:continue
   try:
    with self.io_lock:
     with self.lock:
      if self.session or self.ejecting:continue
     with self.optical.acquire() as lease:
      self.lease=lease
      try:media=self.probe()
      finally:self.lease=None
     with self.lock:self.media=media;self.checked=True;self.error=None
   except DriveBusy:continue
   except Exception:
    with self.lock:self.error='De dvd-gegevens konden niet worden gelezen.';self.checked=True
 def reserve_stream(self):
  with self.io_lock,self.lock:
   if self.session or self.ejecting:raise RuntimeError('De dvd-drive is al in gebruik')
   self.lease=self.optical.acquire()
   self.session=uuid.uuid4().hex;return self.session
 def attach_stream(self,token,child,media):
  with self.lock:
   if self.session!=token:
    self._stop(child);raise RuntimeError('Stream geannuleerd')
   self.proc=child;self.media=media;self.error=None;self.checked=True
 @staticmethod
 def _stop(child):
  if not stop_process(child):raise RuntimeError('De dvd-reader reageert niet op stoppen; sluit de drive opnieuw aan.')
 def finish_stream(self,token):
  with self.io_lock,self.lock:
   if self.session!=token:return
   self._stop(self.proc)
   self.proc=None;self.session=None
   if self.lease:self.lease.close();self.lease=None
 def stop_stream(self):
  with self.io_lock,self.lock:
   self._stop(self.proc)
   self.proc=None;self.session=None
   if self.lease:self.lease.close();self.lease=None
 def eject(self):
  with self.lock:self.ejecting=True
  try:
   self.stop_stream()
   with self.io_lock,self.optical.acquire() as lease:
    subprocess.run(['eject',optical_device()],check=True,capture_output=True,timeout=12,pass_fds=(lease.fileno(),))
    with self.lock:self.media=None;self.checked=True;self.error=None
  finally:
   with self.lock:self.ejecting=False
   self.wake.set()

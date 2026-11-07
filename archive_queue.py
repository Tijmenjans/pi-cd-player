from state_store import write_json
"""Persistent logical CD queue, independent of which tracks have finished uploading."""
import json
import random
import urllib.parse

FADE_SECONDS=3


class ArchiveQueue:
    def __init__(self, execute, path, archive):
        self.execute,self.path,self.archive=execute,path,archive
        try: self.data=json.loads(path.read_text())
        except (OSError,ValueError): self.data={}
        self.loaded=None
        self.last_elapsed=0
        self.loaded_uri=None
        self.previous_state=None
        self.recovered=False
        self.queued=None
        self.fades_configured=False

    def save(self):
        write_json(self.path,self.data,durable=True)

    def reset_engine(self):
        # MPD assigns fresh song ids after a service restart or source switch.
        self.loaded=None;self.loaded_uri=None;self.previous_state=None;self.last_elapsed=0
        self.queued=None;self.recovered=False;self.fades_configured=False

    def attach(self, disc, reset=False):
        if reset or self.data.get('disc')!=disc['id']:
            self.data={'disc':disc['id'],'shuffle':self.data.get('shuffle',False),'round':1,
                       'order':[t['number'] for t in disc['tracks']],'position':0,
                       'handled':[],'intent':False,'pending':None}
            self.loaded=None;self.loaded_uri=None;self.previous_state=None;self.save()
            self.queued=None
            self.recovered=True
        if not self.recovered:
            self.recovered=True
            try:
                rows=self.execute('currentsong','status','playlistinfo')
                prefix='file: '+getattr(self.archive,'audio_base_url','http://127.0.0.1:8080')+f'/audio/{disc["id"]}/'
                saved_uri=next((r[6:] for r in rows[0] if r.startswith(prefix)),None)
                # A local stream token belongs to the previous web process; reload it
                # through the current buffer/server rather than recovering a stale URL.
                saved=int(urllib.parse.urlsplit(saved_uri).path.rsplit('/',1)[1]) if saved_uri and not urllib.parse.urlsplit(saved_uri).query else None
                if saved in self.data.get('order',[]):
                    self.loaded=saved
                    self.loaded_uri=saved_uri
                    self.data['position']=self.data['order'].index(saved)
                    self.previous_state=dict(r.split(': ',1) for r in rows[1] if ': ' in r).get('state')
                    current_id=dict(r.split(': ',1) for r in rows[1] if ': ' in r).get('songid')
                    entries=[];entry={}
                    for line in rows[2]:
                        key,_,value=line.partition(': ')
                        if key=='file':
                            if entry:entries.append(entry)
                            entry={'file':value}
                        else:entry[key]=value
                    if entry:entries.append(entry)
                    index=next((i for i,e in enumerate(entries) if e.get('Id')==current_id),-1)
                    if index>=0 and index+1<len(entries):
                        nxt=entries[index+1];uri=nxt.get('file','')
                        number=self._uri_number(uri,disc['id'])
                        if number and nxt.get('Id'):
                            self.queued={'number':number,'uri':uri,'id':nxt['Id']}
            except (ValueError,RuntimeError,OSError): pass
        skipped = set(getattr(self.archive, 'skipped', {}).get(disc['id'], []))
        if skipped:
            order = self.data['order']
            pos = self.data['position']
            current = order[pos] if pos < len(order) else None
            self.data['order'] = [n for n in order if n not in skipped]
            remaining = self.data['order']
            self.data['position'] = remaining.index(current) if current in remaining else min(pos, max(0, len(remaining)-1))
            self.data['all_tracks'] = [t['number'] for t in disc['tracks'] if t['number'] not in skipped]
            if self.data.get('pending') in skipped: self.data['pending'] = None
            if self.data.get('next_round_order'):
                self.data['next_round_order'] = [n for n in self.data['next_round_order'] if n not in skipped]
            self.save()
        self.archive.attach(disc)
        self.prioritize()

    def prioritize(self):
        order=self.data.get('order',[]);pos=self.data.get('position',0)
        pending=self.data.get('pending')
        self.archive.prioritize(list(dict.fromkeys(([pending] if pending else [])+
                               order[pos:]+order[:pos]+self.data.get('all_tracks',order))))

    def ensure(self, disc):
        self.attach(disc)

    def _load(self, number, resume=0):
        # No cloud token or public URL in MPD; Flask relays with the private credential.
        uri=self.archive.playback_uri(number)
        self.execute('stop','clear','random 0','repeat 0','single 0','consume 1',
                     f'crossfade {FADE_SECONDS}','mixrampdelay -1',f'add "{uri}"')
        self.fades_configured=True;self.queued=None
        self.last_elapsed=resume
        self.loaded=number;self.loaded_uri=uri;self.previous_state='play'
        # Queue an already available successor before decoding starts, so even a
        # short song cannot fill MPD's buffer before crossfading is prepared.
        self._preload({'state':'play'})
        self.execute('play 0')
        if resume>0:
            self.execute('seekcur '+str(resume))

    @staticmethod
    def _uri_number(uri, identity):
        parsed=urllib.parse.urlsplit(uri)
        prefix=f'/audio/{identity}/'
        try:return int(parsed.path[len(prefix):]) if parsed.path.startswith(prefix) else None
        except ValueError:return None

    def _adopt_preloaded(self,status):
        if not self.queued or status.get('songid')!=self.queued['id']:return False
        successor=self.queued;self.queued=None
        self.advance()
        order=self.data['order']
        if successor['number'] in order:self.data['position']=order.index(successor['number'])
        self.loaded=successor['number'];self.loaded_uri=successor['uri'];self.last_elapsed=0
        self.archive.release_playback()
        self.previous_state=status.get('state');self.save()
        return True

    def _successor(self):
        if self.data.get('pending'):return self.data['pending']
        order=self.data['order'];pos=self.data['position']
        if pos+1<len(order):return order[pos+1]
        if self.data['shuffle'] and order:
            if not self.data.get('next_round_order'):
                planned=self.data['all_tracks'][:];random.shuffle(planned)
                if len(planned)>1 and planned[0]==order[pos]:planned[0],planned[1]=planned[1],planned[0]
                self.data['next_round_order']=planned;self.save()
            return self.data['next_round_order'][0]
        return None

    def _preload(self,status):
        # Server-only preloads cannot steal the descriptor pinning the current WAV.
        active=self.data['intent'] or status.get('state')=='pause'
        wanted=self._successor() if active and self.loaded is not None and status.get('state') in ('play','pause') else None
        if wanted is not None and not self.archive.ready(wanted):wanted=None
        if self.queued and self.queued['number']!=wanted:
            now=dict(r.split(': ',1) for r in self.execute('status')[0] if ': ' in r)
            if self._adopt_preloaded(now):
                return self._preload(now)
            try:self.execute('deleteid '+self.queued['id'])
            except RuntimeError as exc:
                if 'No such song' not in str(exc):raise
            self.queued=None
        if wanted is not None and self.queued is None:
            uri=self.archive.server_uri(wanted)
            rows=self.execute(f'addid "{uri}"')[0]
            songid=next((r[4:] for r in rows if r.startswith('Id: ')),None)
            if songid is None:raise RuntimeError('Het volgende nummer kon niet worden klaargezet')
            self.queued={'number':wanted,'uri':uri,'id':songid}

    def new_round(self, avoid=None):
        # Include skipped tracks again. They remain in all_tracks even when removed this round.
        order=self.data.pop('next_round_order',None)
        if not order:
            order=self.data['all_tracks'][:]
            random.shuffle(order)
            if len(order)>1 and order[0]==avoid: order[0],order[1]=order[1],order[0]
        self.data.update(order=order,position=0,handled=[],pending=None,round=self.data['round']+1)

    def advance(self):
        order=self.data['order'];pos=self.data['position']
        if pos<len(order): self.data['handled']=list(dict.fromkeys(self.data['handled']+[order[pos]]))
        pending=self.data.get('pending')
        if pending:
            if pending not in order: order.append(pending)
            self.data['position']=order.index(pending);self.data['pending']=None
        elif pos+1<len(order): self.data['position']+=1
        elif self.data['shuffle']: self.new_round(order[pos] if order else None)
        else: self.data['intent']=False
        self.prioritize();self.save()

    def observe(self, disc):
        self.ensure(disc)
        self.data.setdefault('all_tracks',[t['number'] for t in disc['tracks']])
        if not self.fades_configured:
            self.execute(f'crossfade {FADE_SECONDS}','mixrampdelay -1','consume 1')
            self.fades_configured=True
        rows=self.execute('status')[0]
        status=dict(r.split(': ',1) for r in rows if ': ' in r)
        self._adopt_preloaded(status)
        if self.loaded is not None and status.get('state') in ('play','pause') and not status.get('error'):
            self.last_elapsed=float(status.get('elapsed',self.last_elapsed))
        local_end=self.archive.local_end_seconds(self.loaded) if self.loaded is not None else None
        if not self.queued and local_end is not None and status.get('state')=='play' and float(status.get('elapsed',0))>=local_end:
            self.execute('stop')
            status['state']='stop'
        # A clicked unavailable track replaces playback only after becoming ready.
        pending=self.data.get('pending')
        switched=False
        if pending and self.archive.playable(pending):
            if pending not in self.data['order']: self.data['order'].append(pending)
            self.data['position']=self.data['order'].index(pending)
            self.data['pending']=None;self.data['intent']=True;self.save()
            switched=True
        if (not switched and self.data['intent'] and self.loaded is not None and self.previous_state=='play'
                and status.get('state')=='stop' and not status.get('error')):
            self.loaded=None
            self.advance()
        pos=self.data['position'];order=self.data['order']
        current=order[pos] if pos<len(order) else None
        unavailable=getattr(self.archive,'unavailable',lambda number:False)
        # A track whose bounded recovery attempts are exhausted must not hold
        # the whole playback queue at 'buffering' indefinitely.
        for _ in range(len(order)):
            if not (self.data['intent'] and current and unavailable(current)):break
            if self.loaded==current:
                self.execute('stop');self.loaded=None;self.previous_state=None
            self.advance()
            pos=self.data['position'];order=self.data['order']
            current=order[pos] if pos<len(order) else None
        if self.data['intent'] and current and self.archive.playable(current):
            failed_current=self.loaded==current and bool(status.get('error'))
            if self.loaded!=current or failed_current:
                # A decoder retry must resume the same local source rather than
                # switching to the newly uploaded copy and starting at zero.
                resume=max(self.last_elapsed,float(status.get('elapsed',0))) if failed_current else 0
                self._load(current,resume=resume)
                status=dict(r.split(': ',1) for r in self.execute('status')[0] if ': ' in r)
        self.previous_state=status.get('state')
        waiting=self.data['intent'] and current and not self.archive.playable(current)
        status['track']=self.loaded if pending and self.loaded else current
        status['buffering']=bool(waiting)
        if waiting: status.update(state='play',elapsed='0',duration='0')
        status['pending_track']=self.data.get('pending')
        status['playback_source']='local' if self.loaded_uri and '?local=' in self.loaded_uri else 'server'
        local_end=self.archive.local_end_seconds(self.loaded) if self.loaded is not None else None
        self._preload(status)
        if not self.queued and local_end is not None and self.loaded==current:
            status['duration']=str(local_end)
        status['crossfade']=str(FADE_SECONDS)
        if not self.data['intent'] and status.get('state')=='stop': self.archive.release_playback()
        self.prioritize()
        return status,dict(shuffle=self.data['shuffle'],round=self.data['round'],current=current,
                           upcoming=order[pos+1:],handled=self.data['handled'],previous=pos>0,
                           pending=self.data.get('pending'))

    def action(self,disc,cmd,payload):
        self.ensure(disc)
        self.data.setdefault('all_tracks',[t['number'] for t in disc['tracks']])
        self._adopt_preloaded(dict(r.split(': ',1) for r in self.execute('status')[0] if ': ' in r))
        order=self.data['order'];pos=self.data['position']
        if cmd=='shuffle':
            enabled=payload.get('enabled')
            if type(enabled) is not bool: raise ValueError('Ongeldige shuffle-instelling')
            tail=order[pos+1:]
            if enabled: random.shuffle(tail)
            else: tail.sort()
            self.data['order']=order[:pos+1]+tail;self.data['shuffle']=enabled
            self.data.pop('next_round_order',None)
        elif cmd=='queue-order':
            wanted=payload.get('tracks')
            if not isinstance(wanted,list) or any(type(n)is not int for n in wanted) or sorted(wanted)!=sorted(order[pos+1:]):
                raise ValueError('De wachtrij is veranderd. Probeer opnieuw.')
            self.data['order']=order[:pos+1]+wanted
        elif cmd=='queue-skip':
            n=int(payload['track'])
            if n not in order[pos+1:]: raise ValueError('Dit nummer staat niet meer in de wachtrij')
            order.remove(n);self.data['handled']=list(dict.fromkeys(self.data['handled']+[n]))
            if self.data.get('pending')==n: self.data['pending']=None
        elif cmd=='track':
            n=int(payload['track'])
            if n not in self.data['all_tracks']: raise ValueError('Onbekende track')
            if self.loaded and self.archive.playable(self.loaded) and not self.archive.playable(n):
                self.data['pending']=n
            else:
                if n not in order: order.append(n)
                self.data['position']=order.index(n);self.data['pending']=None
                if self.loaded==n:
                    # Reload explicitly: MPD may have restored this URL while the
                    # web relay was still starting and retained a decoder error.
                    self.loaded=None;self.previous_state=None
                self.data['intent']=True
        elif cmd=='next':
            self.data['pending']=None
            self.execute('stop');self.loaded=None;self.previous_state=None
            self.data['intent']=True;self.advance()
        elif cmd=='previous':
            self.data['position']=max(0,pos-1);self.data['pending']=None;self.data['intent']=True
        elif cmd=='play':
            self.data['intent']=True
            if self.loaded==order[pos]: self.execute('play')
        elif cmd in ['pause','stop']:
            self.data['intent']=False;self.data['pending']=None
            self.execute('pause 1' if cmd=='pause' else 'stop')
            if cmd=='stop': self.loaded=None
        else: raise ValueError('Onbekende opdracht')
        self.prioritize();self.save()
        return self.observe(disc)

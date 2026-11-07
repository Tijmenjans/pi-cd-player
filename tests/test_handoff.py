import json,tempfile,unittest
from pathlib import Path
from archive import Archive
from archive_queue import ArchiveQueue
from live_audio import GrowingWav,RATE,wav_header

class MPD:
 def __init__(self):self.commands=[];self.state='stop';self.elapsed=0;self.error=None
 def __call__(self,*commands):
  result=[]
  for c in commands:
   self.commands.append(c)
   if c=='stop':self.state='stop'
   if c=='play 0':self.state='play';self.error=None
   rows=[]
   if c=='status':
    rows=['state: '+self.state,'elapsed: '+str(self.elapsed),'songid: 1']
    if self.error:rows.append('error: '+self.error)
   if c.startswith('addid'):rows=['Id: 2']
   result.append(rows)
  return result

class HandoffTests(unittest.TestCase):
 def setup_store(self,root):
  (root/'data').mkdir();(root/'data/archive.json').write_text(json.dumps({'url':'https://test.invalid','token':'test'}))
  store=Archive(root);disc={'id':'TESTDISC1','tracks':[{'number':1},{'number':2},{'number':3}]};store.attach(disc)
  for n in (1,2):
   path=root/f'{n}.wav';path.write_bytes(wav_header(RATE*6)+b'\xe8\x03\x18\xfc'*RATE*6)
   live=GrowingWav(path,RATE*6);live.refresh(complete=True);store.local[n]=live
  return store,disc
 def test_upload_ready_does_not_change_current_local_uri_or_restart(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);store,disc=self.setup_store(root);m=MPD();q=ArchiveQueue(m,root/'queue.json',store)
   q.action(disc,'play',{});uri=q.loaded_uri;self.assertIn('?local=',uri)
   m.elapsed=2;q.observe(disc);before=m.commands.count('play 0')
   store._receive({'id':disc['id'],'tracks':[{'number':1,'ready':True},{'number':2,'ready':True}]},store.generation)
   self.assertEqual(store.playback_uri(1),uri)
   q.observe(disc)
   self.assertEqual(q.loaded_uri,uri);self.assertEqual(m.commands.count('play 0'),before)
   self.assertEqual(q.queued['number'],2);self.assertNotIn('?local=',q.queued['uri'])
   self.assertIsNotNone(store.local[1].fd)
   store.cancel()
 def test_next_track_stays_local_if_server_not_ready_then_next_can_use_server(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);store,disc=self.setup_store(root);m=MPD();q=ArchiveQueue(m,root/'queue.json',store)
   q.action(disc,'play',{});q.action(disc,'next',{})
   self.assertEqual(q.loaded,2);self.assertIn('?local=',q.loaded_uri)
   uri=q.loaded_uri;store.states[2]={'ready':True};store.states[3]={'ready':True}
   q.observe(disc);self.assertEqual(q.loaded_uri,uri)
   self.assertEqual(q.queued['number'],3);self.assertNotIn('?local=',q.queued['uri'])
   store.cancel()
 def test_decoder_retry_resumes_current_pi_track_instead_of_restarting(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);store,disc=self.setup_store(root);m=MPD();q=ArchiveQueue(m,root/'queue.json',store)
   q.action(disc,'play',{});m.elapsed=2.5;q.observe(disc);uri=q.loaded_uri
   store.states[1]={'ready':True};m.state='stop';m.elapsed=0;m.error='temporary read failure'
   q.observe(disc);self.assertEqual(q.loaded_uri,uri);self.assertIn('seekcur 2.5',m.commands)
   store.cancel()
class BlockedQueueTests(HandoffTests):
 def test_blocked_current_track_does_not_buffer_forever(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);store,disc=self.setup_store(root);m=MPD();q=ArchiveQueue(m,root/'queue.json',store)
   store.states[1]={'storage':'blocked','ready':False}
   q.data={'disc':disc['id'],'order':[1,2,3],'all_tracks':[1,2,3],'position':0,'intent':True,'shuffle':False,'round':1,'handled':[],'pending':None}
   q.recovered=True
   state,_=q.observe(disc)
   self.assertEqual(state['track'],2);self.assertEqual(q.loaded,2);self.assertFalse(state['buffering'])
   store.cancel()

if __name__=='__main__':unittest.main()

"""Barcode selection and drive circuit breaker; simulated I/O only."""
import copy,json,tempfile,time,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import tests
import app as player
import catalogue,music_metadata
from archive import Archive
from optical_reader import ReaderStalled,ReadFailure

SECTORS=[11797,14308,13714,10339,12955,13129,11636,12104,13676,12645,12280,13012,13759,13497]
def disc():return {'id':'olA1yZXd23ieopV4fnqmhg7y.Uk-','present':True,'toc':'measured','title':'Audio-cd','artist':'Onbekende artiest','tracks':[{'number':i+1,'sectors':n,'seconds':round(n/75),'title':'Track '+str(i+1)} for i,n in enumerate(SECTORS)]}
class BarcodeTests(unittest.TestCase):
 def test_barcode_checks_and_verified_catalogue_never_replace_toc(self):
  self.assertEqual(music_metadata.normalise_barcode('5 032044 076128'),'5032044076128')
  for bad in ('5032044076127','https://x','0','12345678901234','0000000000000'):
   with self.assertRaises(ValueError):music_metadata.normalise_barcode(bad)
  snapshot=disc();before=copy.deepcopy(snapshot)
  result=catalogue.lookup(snapshot,Path(__file__).resolve().parents[1]/'catalogue',barcode='5032044076128')
  self.assertEqual(result['selected'],'discogs-1685005');self.assertEqual(len(result['releases'][0]['tracks']),14)
  self.assertEqual(snapshot,before)
  self.assertIsNone(catalogue.lookup(snapshot,Path(__file__).resolve().parents[1]/'catalogue',barcode='886971698824'))
 def test_same_barcode_wrong_track_count_and_lengths_are_rejected(self):
  identity='00000000-0000-0000-0000-000000000001'
  full={'id':identity,'title':'Candidate','barcode':'5032044076128','artist-credit':[{'name':'Singer'}],'media':[{'position':1,'tracks':[{'title':str(i),'length':n/75*1000} for i,n in enumerate(SECTORS)]}]}
  for mutation in ('none','extra','long'):
   release=copy.deepcopy(full)
   if mutation=='extra':release['media'][0]['tracks'].append({'title':'wrong','length':1000})
   if mutation=='long':release['media'][0]['tracks'][0]['length']+=4000
   fetch=Mock(side_effect=[{'releases':[{'id':identity}]},release])
   result=music_metadata.lookup_barcode(disc(),'5032044076128',fetch)
   self.assertEqual(bool(result['releases']),mutation=='none')
 def test_new_catalogue_match_bypasses_a_fresh_negative_lookup_cache(self):
  snapshot=disc()
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/(snapshot['id']+'.json')).write_text(json.dumps({'lookup_version':1,'toc':'measured','looked_up_at':time.time(),'releases':[]}))
   (root/'discogs-1685005-1200.jpg').write_bytes(b'cached image')
   with patch.object(player,'DATA',root),patch.object(player,'disc',snapshot),patch.object(player,'get_musicbrainz_json') as fetch,patch.object(player.archive,'metadata'):
    self.assertFalse(player.enrich_once(copy.deepcopy(snapshot)))
    self.assertEqual(player.disc['title'],'White Christmas');fetch.assert_not_called()
 def test_barcode_action_is_disc_bound_and_does_not_touch_audio(self):
  snapshot=disc()
  with tempfile.TemporaryDirectory() as tmp,patch.object(player,'DATA',Path(tmp)),patch.object(player,'disc',snapshot),patch.object(player,'source','cd'),patch.object(player.threading,'Thread') as thread,patch.object(player,'mpd') as mpd:
   client=player.app.test_client();headers={'X-CDSpeler':'1'}
   def post(identity,barcode):return client.post('/api/action',json={'action':'metadata-barcode','disc_id':identity,'barcode':barcode},headers=headers)
   self.assertEqual(post('STALE','5032044076128').status_code,400)
   self.assertEqual(post(snapshot['id'],'5032044076127').status_code,400);thread.assert_not_called()
   self.assertEqual(post(snapshot['id'],'5032044076128').status_code,200)
   saved=json.loads((Path(tmp)/(snapshot['id']+'-barcode.json')).read_text())
   self.assertEqual(saved['toc'],'measured');mpd.assert_not_called()

 def test_restored_ejected_album_also_reloads_metadata(self):
  snapshot={**disc(),'ejected':True,'inserted':False}
  with patch.object(player,'disc',snapshot),patch.object(player,'runtime_threads',[]),patch.object(player,'source','cd'),patch.object(player,'runtime_owner'),patch.object(player,'choose_source'),patch.object(player.queue,'attach') as attach,patch.object(player.threading,'Thread') as thread:
   player.start_runtime()
   attach.assert_called_once_with(snapshot)
   self.assertTrue(any(call.kwargs.get('target')==player.enrich for call in thread.call_args_list))

 def test_failed_barcode_correction_keeps_old_cache_and_identification_consistent(self):
  snapshot=disc();snapshot.update(title='Known album',artist='Singer',release='known-release',cover='/cover/known.jpg')
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);cache=root/(snapshot['id']+'.json');old={'releases':[{'id':'known-release','title':'Known album'}]};cache.write_text(json.dumps(old))
   (root/(snapshot['id']+'-barcode.json')).write_text(json.dumps({'barcode':'5032044076128','toc':'measured'}))
   with patch.object(player,'DATA',root),patch.object(player,'disc',snapshot),patch.object(player.catalogue,'lookup',return_value=None),patch.object(player.music_metadata,'lookup_barcode',return_value={'releases':[]}),patch.object(player.archive,'metadata') as publish:
    self.assertFalse(player.enrich_once(copy.deepcopy(snapshot)))
    self.assertEqual(player.disc['title'],'Known album');self.assertEqual(player.disc['release'],'known-release')
    self.assertEqual(player.disc['metadata_status'],'barcode_unknown');self.assertEqual(json.loads(cache.read_text()),old)
    publish.assert_not_called()
 def test_deleted_barcode_candidate_does_not_discard_valid_one(self):
  import urllib.error
  identity='00000000-0000-0000-0000-000000000001';other='00000000-0000-0000-0000-000000000002'
  release={'id':identity,'title':'Good','barcode':'5032044076128','media':[{'position':1,'tracks':[{'title':str(i),'length':n/75*1000} for i,n in enumerate(SECTORS)]}]}
  fetch=Mock(side_effect=[{'releases':[{'id':identity},{'id':other}]},release,urllib.error.HTTPError('url',404,'gone',{},None)])
  self.assertEqual(len(music_metadata.lookup_barcode(disc(),'5032044076128',fetch)['releases']),1)

class DeviceCircuitTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);(self.root/'data').mkdir()
  (self.root/'data/archive.json').write_text(json.dumps({'url':'https://example.invalid','token':'offline'}))
  self.archive=Archive(self.root);self.archive.attach(disc())
 def test_repeated_stalls_across_tracks_halt_device_and_survive_restart(self):
  a=self.archive;a._rip=Mock(side_effect=ReaderStalled('watchdog'))
  self.assertFalse(a._produce_once());self.assertFalse(a.drive_halted)
  self.assertFalse(a._produce_once());self.assertTrue(a.drive_halted);self.assertTrue(a.snapshot()['drive_blocked'])
  calls=a._rip.call_count;self.assertFalse(a._produce_once());self.assertEqual(a._rip.call_count,calls)
  fresh=Archive(self.root);fresh.attach(disc());self.assertTrue(fresh.drive_halted)
  fresh._rip=Mock();self.assertFalse(fresh._produce_once());fresh._rip.assert_not_called()
 def test_normal_bad_track_does_not_trip_device_breaker(self):
  a=self.archive;a._rip=Mock(side_effect=ReadFailure('bad sector'))
  for i in range(3):a.retry_after.clear();a.prioritize([1]);a._produce_once()
  self.assertFalse(a.drive_halted);self.assertEqual(a.failures[disc()['id']+':1'],3)
 def test_explicit_retry_requires_idle_accessible_drive_and_clears_persisted_breaker(self):
  a=self.archive;a.drive_stalls={'one:1','one:2'};a._halt_drive()
  with patch.object(a,'reading',return_value=True),patch('archive.optical_device') as device:
   with self.assertRaises(RuntimeError):a.retry_failed()
   device.assert_not_called();self.assertTrue(a.drive_halted)
  with patch.object(a,'reading',return_value=False),patch('archive.optical_device',side_effect=RuntimeError('disconnected')):
   with self.assertRaises(RuntimeError):a.retry_failed()
   self.assertTrue(a.drive_halted)
  with patch.object(a,'reading',return_value=False),patch('archive.optical_device',return_value='/dev/fake'):
   a.retry_failed()
  self.assertFalse(a.drive_halted);self.assertFalse(Archive(self.root).drive_halted)

 def test_complete_cached_wav_uploads_during_halt_without_clearing_stall_history(self):
  from live_audio import wav_header,RATE
  a=self.archive;snapshot=disc();snapshot['id']='TESTNEW1';snapshot['tracks']=[{'number':1,'sectors':75}];a.attach(snapshot)
  target=a.stage/(snapshot['id']+'-1.wav');target.write_bytes(wav_header(RATE)+b'\x01\x00\x01\x00'*RATE)
  a.drive_stalls={'one:1','two:2'};a._halt_drive();a._rip=Mock(side_effect=AssertionError('must not read'))
  self.assertTrue(a._produce_once());self.assertEqual(a.uploads.get_nowait()['number'],1)
  self.assertTrue(a.drive_halted);self.assertEqual(a.drive_stalls,{'one:1','two:2'});a._rip.assert_not_called()
  for live in a.local.values():live.close()
 def test_retry_disk_failure_keeps_halt_and_failures(self):
  a=self.archive;a._halt_drive();a.drive_stalls={'a:1','a:2'};before=dict(a.failures)
  with patch.object(a,'reading',return_value=False),patch('archive.optical_device',return_value='/dev/fake'),patch('archive.write_json',side_effect=OSError('disk full')):
   with self.assertRaises(OSError):a.retry_failed()
  self.assertTrue(a.drive_halted);self.assertTrue(a.drive_blocked);self.assertEqual(a.failures,before)
  self.assertEqual(a.drive_stalls,{'a:1','a:2'})
 def test_existing_upload_retry_is_not_stopped_by_device_halt(self):
  from test_reliability import Cloud
  from live_audio import wav_header,RATE
  a=self.archive;d=disc();d['id']='TESTNEW1';d['tracks']=[{'number':1,'sectors':75}];a.attach(d)
  target=a.stage/(d['id']+'-1.wav');target.write_bytes(wav_header(RATE)+b'\x01\x00\x01\x00'*RATE)
  a.cloud=Cloud(d);self.assertTrue(a._produce_once());a._halt_drive()
  a._upload_one(a.uploads.get_nowait());self.assertTrue(a.ready(1));self.assertTrue(a.drive_halted)
  for live in a.local.values():live.close()

 def test_reusing_cached_wav_does_not_count_as_a_successful_drive_read(self):
  from live_audio import wav_header,RATE
  a=self.archive;d=disc();d['id']='TESTNEW1';d['tracks']=[{'number':1,'sectors':75}];a.attach(d)
  target=a.stage/(d['id']+'-1.wav');target.write_bytes(wav_header(RATE)+b'\x01\x00\x01\x00'*RATE)
  a.drive_stalls={'earlier:1'};a._rip=Mock(side_effect=AssertionError('no drive read'))
  self.assertTrue(a._produce_once());self.assertEqual(a.drive_stalls,{'earlier:1'})
  for live in a.local.values():live.close()

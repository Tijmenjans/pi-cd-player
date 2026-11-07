"""Failure/concurrency regressions; no live services, drives or network."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import app
import catalogue
from archive import Archive
from dvd import DVD
from live_audio import RATE, wav_header
from optical_reader import DriveBusy, OpticalLease
from state_store import write_text
from tools.import_discogs import proposal

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'archive-server'))
import server
import artwork
import xml.etree.ElementTree as ET

class StateAndSourceTests(unittest.TestCase):
    def test_failed_atomic_write_preserves_old_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source';path.write_text('cd')
            with patch('state_store.os.replace',side_effect=OSError('disk')):
                with self.assertRaises(OSError):write_text(path,'vinyl')
            self.assertEqual(path.read_text(),'cd');self.assertEqual(list(path.parent.iterdir()),[path])

    def test_stop_failure_restores_previous_source(self):
        with patch.object(app,'source','cd'),patch.object(app.plexamp,'configured',return_value=True),patch.object(app,'service',side_effect=[OSError('stop'),None]) as service:
            with self.assertRaises(RuntimeError):app.choose_source('plexamp')
            self.assertEqual(service.call_args_list[-1].args,('start','mpd'))
            self.assertEqual(app.source,'cd');self.assertFalse(app.transition['active'])

    def test_timed_out_start_is_stopped_before_restoring_previous_engine(self):
        calls=[]
        def service(action,name):
            calls.append((action,name))
            if (action,name)==('start','plexamp'):raise subprocess.TimeoutExpired('systemctl',15)
        with patch.object(app,'source','cd'),patch.object(app.plexamp,'configured',return_value=True),patch.object(app,'service',side_effect=service):
            with self.assertRaises(RuntimeError):app.choose_source('plexamp')
        self.assertEqual(calls[-2:],[('stop','plexamp'),('start','mpd')])

    def test_persist_failure_stops_target_and_restores_source(self):
        with patch.object(app,'source','cd'),patch.object(app.plexamp,'configured',return_value=True),patch.object(app,'service') as service,patch.object(app,'write_text',side_effect=OSError('full')):
            with self.assertRaises(RuntimeError):app.choose_source('plexamp')
            self.assertIn(unittest.mock.call('stop','plexamp'),service.call_args_list)
            self.assertEqual(service.call_args_list[-1].args,('start','mpd'))
            self.assertEqual(app.source,'cd')

    def test_status_does_not_wait_for_blocked_source_transition(self):
        entered=threading.Event();release=threading.Event();errors=[]
        def service(*args):entered.set();release.wait(2)
        def change():
            try:app.choose_source('plexamp')
            except Exception as exc:errors.append(exc)
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'source','cd'),patch.object(app.plexamp,'configured',return_value=True),patch.object(app,'service',side_effect=service),patch.object(app,'source_file',Path(tmp)/'source'),patch.object(app,'streaming_source_file',Path(tmp)/'streaming-source'):
            thread=threading.Thread(target=change);thread.start()
            try:
                self.assertTrue(entered.wait(1))
                started=time.monotonic();response=app.app.test_client().get('/api/status')
                self.assertLess(time.monotonic()-started,.5)
                self.assertTrue(response.json['transition']['active'])
                self.assertEqual(response.json['source'],'cd')
            finally:release.set();thread.join(3)
            self.assertFalse(thread.is_alive());self.assertEqual(errors,[])

    def test_mpd_readiness_failure_rolls_back_after_target_start(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'source','spotify'),patch.object(app,'service') as service,patch.object(app,'mpd',side_effect=OSError('not ready')),patch.object(app.time,'monotonic',side_effect=[0,31]),patch.object(app,'source_file',Path(tmp)/'source'),patch.object(app,'streaming_source_file',Path(tmp)/'streaming-source'):
            with self.assertRaises(RuntimeError):app.choose_source('cd')
            self.assertEqual(app.source,'spotify')
            self.assertEqual(service.call_args_list[-1].args,('start','spotify'))
            self.assertIn(unittest.mock.call('stop','mpd'),service.call_args_list)

    def test_runtime_start_is_idempotent_and_stop_is_cooperative(self):
        stop=threading.Event()
        def worker(*args):stop.wait(2)
        with patch.object(app,'runtime_threads',[]),patch.object(app,'runtime_stop',stop),patch.object(app,'choose_source'),patch.object(app.archive,'stopping',threading.Event()),patch.object(app.archive,'cancel'),patch.object(app.dvd,'stop_stream'),patch.object(app.vinyl.meter,'close'):
            from contextlib import ExitStack
            with ExitStack() as stack:
                for obj,names in [(app.archive,['run','upload_loop','monitor']),(app,['scan_loop','queue_loop']),(app.audio,['observe']),(app.vinyl,['observe']),(app.spotify,['observe']),(app.plexamp,['observe','observe_metadata']),(app.dvd,['observe'])]:
                    for name in names:stack.enter_context(patch.object(obj,name,side_effect=worker))
                app.start_runtime();count=len(app.runtime_threads);app.start_runtime()
                self.assertEqual(len(app.runtime_threads),count)
                self.assertTrue(app.stop_runtime(timeout=2));self.assertEqual(app.runtime_threads,[])

    def test_import_does_not_start_background_workers(self):
        code="import sys,types,threading;sys.modules['libdiscid']=types.SimpleNamespace();threading.Thread.start=lambda self: (_ for _ in ()).throw(AssertionError('worker at import'));import app;assert not app.runtime_threads"
        subprocess.run([sys.executable,'-c',code],cwd=ROOT,check=True,capture_output=True,timeout=10)

class OpticalTests(unittest.TestCase):
    def test_cdtext_and_toc_share_one_lease(self):
        def probe(snapshot,directory,**kwargs):
            self.assertIsInstance(kwargs['lease_fd'],int)
            with self.assertRaises(DriveBusy):app.archive.optical.acquire()
            return {'cd_text':{'status':'absent'}}
        snapshot={'id':'TEST','toc':'TOC'}
        with patch.object(app.disc_media,'cached_probe',side_effect=probe),patch.object(app.libdiscid,'read',return_value=type('CD',(),{'id':'TEST','toc':'TOC'})()):
            self.assertEqual(app.verified_disc_media(snapshot)['cd_text']['status'],'absent')
        app.archive.optical.acquire().close()

    def test_scanner_holds_lease_during_media_flag_and_toc_read(self):
        class Done(BaseException):pass
        checks=[]
        def check(*args,**kwargs):
            with self.assertRaises(DriveBusy):app.archive.optical.acquire()
            checks.append('leased')
            return type('CD',(),{'id':'TEST','toc':'TOC','first_track':1,'track_lengths':[75]*4})()
        with patch.object(app,'source','cd'),patch.object(app.archive,'reading',return_value=False),patch.object(app.archive,'cancel'),patch.object(app,'media_changed',side_effect=check),patch.object(app.libdiscid,'read',side_effect=check),patch.object(app,'prepare_disc',side_effect=lambda s:s),patch.object(app,'accept_disc',side_effect=Done):
            with self.assertRaises(Done):app.scan_loop()
        self.assertEqual(checks,['leased','leased'])

    def test_idle_scan_releases_lease_before_waiting(self):
        class Done(BaseException):pass
        occupied=[]
        def wait(seconds):
            occupied.append(app.archive.optical.busy())
            if len(occupied)==2:raise Done()
        cd=type('CD',(),{'id':'TEST','toc':'TOC','first_track':1,'track_lengths':[75]*4})()
        with patch.object(app,'source','cd'),patch.object(app.archive,'reading',return_value=False),patch.object(app.archive,'cancel'),patch.object(app,'media_changed',side_effect=[True,False]),patch.object(app.libdiscid,'read',return_value=cd) as read,patch.object(app,'prepare_disc',side_effect=lambda s:s),patch.object(app,'accept_disc'),patch.object(app.threading,'Thread'),patch.object(app.time,'sleep',side_effect=wait):
            with self.assertRaises(Done):app.scan_loop()
        self.assertEqual(occupied,[False,False]);self.assertEqual(read.call_count,1)

    def test_dvd_stream_reserves_shared_drive_until_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=DVD(tmp);d.reserve_stream()
            competing=OpticalLease(d.optical.path,d.optical.binary)
            with self.assertRaises(DriveBusy):competing.acquire()
            d.stop_stream();competing.acquire().close()

class OfflineArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'data').mkdir()
        (self.root/'data/archive.json').write_text(json.dumps({'url':'https://archive.example.invalid','token':'test'}))
        self.a=Archive(self.root);self.a.cloud=Mock();self.a.cloud.request.side_effect=TimeoutError('offline')
        self.disc={'id':'TESTDISC1','tracks':[{'number':n,'sectors':75} for n in (1,2,3)]}
        self.a.attach(self.disc)
    def wav(self,path):path.write_bytes(wav_header(RATE)+b'\1\0\1\0'*RATE)
    def test_initial_server_check_is_bounded_and_failure_releases_wait(self):
        started=time.monotonic()
        self.assertFalse(self.a._await_initial_status(timeout=.02))
        self.assertLess(time.monotonic()-started,.3)
        self.assertFalse(self.a._register(self.disc,self.a.generation))
        self.assertTrue(self.a._await_initial_status(timeout=.02))

    def test_initial_server_result_skips_already_stored_tracks(self):
        payload=copy.deepcopy(self.disc)
        for track in payload['tracks']:track.update(uploaded=True,ready=True)
        self.a.cloud.request.side_effect=None;self.a.cloud.request.return_value=payload
        self.assertTrue(self.a._register(self.disc,self.a.generation))
        self.a._rip=Mock(side_effect=AssertionError('redundant reread'))
        self.assertFalse(self.a._produce_once());self.a._rip.assert_not_called()
        self.assertTrue(self.a._await_initial_status(timeout=.02))

    def test_complete_file_reused_without_network_and_default_is_4x(self):
        path=self.a.stage/'TESTDISC1-1.wav';self.wav(path)
        self.a._rip=Mock(side_effect=AssertionError('reread'))
        self.assertTrue(self.a._produce_once());self.a.cloud.request.assert_not_called()
        self.assertTrue(self.a.playable(1));self.assertEqual(self.a.snapshot()['speed'],4)
        self.assertEqual(self.a.uploads.get_nowait()['number'],1)
    def test_full_buffer_is_bounded_and_explicit(self):
        def rip(d,n,g,p):self.wav(p);return True
        self.a._rip=rip
        self.assertTrue(self.a._produce_once());self.assertTrue(self.a._produce_once());self.assertFalse(self.a._produce_once())
        self.assertTrue(self.a.snapshot()['buffer_full']);self.assertIn('buffer vol',self.a.snapshot()['buffer_message'])
    def test_storage_error_does_not_spend_optical_retry(self):
        self.a._rip=Mock(side_effect=OSError('disk full'))
        self.assertFalse(self.a._produce_once());self.assertEqual(self.a.failures,{})
        self.assertEqual(self.a.speed_limit,4);self.assertIn('opslag',self.a.snapshot()['error'])
    def test_metric_failure_does_not_lose_completed_audio(self):
        def rip(d,n,g,p):self.wav(p);return True
        self.a._rip=rip
        with patch('archive.write_json',side_effect=OSError('metrics disk')):self.assertTrue(self.a._produce_once())
        self.assertEqual(self.a.failures,{})

class CatalogueTests(unittest.TestCase):
    def entry(self,identity=None):
        medium={'number':1,'tracks':[{'title':'Song','artist':'Singer','seconds':1} for _ in range(4)]}
        if identity:medium['disc_ids']=[identity]
        return {'id':'discogs-1','title':'Album','artist':'Singer','media':[medium]}
    def test_bad_entry_cannot_poison_valid_entry_and_wrong_id_is_rejected(self):
        snapshot={'id':'TEST','tracks':[{'sectors':75} for _ in range(4)]}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'bad.json').write_text('{"media":[null]}')
            (path/'good.json').write_text(json.dumps(self.entry('OTHER')))
            self.assertIsNone(catalogue.lookup(snapshot,path))
            (path/'good.json').write_text(json.dumps(self.entry('TEST')))
            self.assertEqual(catalogue.lookup(snapshot,path)['selected'],'discogs-1')
    def test_discogs_proposal_keeps_measured_lengths_and_explicit_positions(self):
        entry={'id':123,'title':'Album','artists':[{'name':'Singer'}],'tracklist':[{'position':'1-1','title':'Song','duration':'8:00'}]}
        snapshot={'id':'TEST','tracks':[{'number':1,'sectors':750}]}
        result=proposal('https://www.discogs.com/release/123',entry,snapshot,['1-1'],1,3,True)
        self.assertEqual(result['media'][0]['tracks'][0]['seconds'],10)
        self.assertEqual(result['media'][0]['disc_ids'],['TEST'])
        self.assertEqual(result['disc_total'],3)

class ServerRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        for name,value in [('ROOT',root/'archive'),('MUSIC',root/'music'),('PENDING',set()),('JOBS',server.queue.Queue())]:
            patcher=patch.object(server,name,value);patcher.start();self.addCleanup(patcher.stop)
        server.initialize()
        self.disc={'id':'TESTDISC1','title':'Album','artist':'Singer','tracks':[{'number':1,'sectors':75,'title':'Song','artist':'Singer'}]}
        server.register(self.disc['id'],self.disc)
    def test_plex_failure_is_durable_backoff_and_does_not_queue_conversion(self):
        server.schedule_plex_refresh()
        with patch.object(server,'refresh_plex',side_effect=TimeoutError('offline')) as refresh:
            self.assertTrue(server.refresh_plex_once(now=100));self.assertFalse(server.refresh_plex_once(now=101))
            self.assertEqual(refresh.call_count,1)
        server.initialize()
        with server.connect() as db:row=db.execute('SELECT * FROM plex_refresh').fetchone();self.assertTrue(row['pending']);self.assertEqual(row['retry_at'],102)
        self.assertTrue(server.JOBS.empty())
        with patch.object(server,'refresh_plex'):self.assertTrue(server.refresh_plex_once(now=103))
    def test_new_refresh_request_is_not_cleared_by_older_request(self):
        server.schedule_plex_refresh()
        with patch.object(server,'refresh_plex',side_effect=server.schedule_plex_refresh):server.refresh_plex_once(now=100)
        with server.connect() as db:self.assertTrue(db.execute('SELECT pending FROM plex_refresh').fetchone()[0])
    def test_ready_flac_does_not_wait_for_plex(self):
        target=server.destination(self.disc,1);target.parent.mkdir(parents=True);target.write_bytes(b'existing flac')
        with server.connect() as db:db.execute('INSERT INTO tracks(disc,number,path,version,trim_version) VALUES(?,?,?,?,?)',('TESTDISC1',1,str(target),server.metadata_version(self.disc),server.silence.POLICY))
        with patch.object(server,'refresh_plex',side_effect=AssertionError('network in encode')):self.assertTrue(server.encode('TESTDISC1',1))
        with server.connect() as db:self.assertTrue(db.execute('SELECT pending FROM plex_refresh').fetchone()[0])
    def test_orphan_wav_recovers_once_and_truncated_file_is_retained(self):
        path=server.ROOT/'raw/TESTDISC1/1.wav';path.parent.mkdir(parents=True)
        path.write_bytes(wav_header(RATE)+b'partial')
        self.assertEqual(server.reconcile_raw(),0);self.assertTrue(path.exists())
        path.write_bytes(wav_header(RATE)+b'\1\0\1\0'*RATE)
        self.assertEqual(server.reconcile_raw(),1);self.assertEqual(server.reconcile_raw(),0)
        self.assertTrue(server.snapshot('TESTDISC1')['tracks'][0]['uploaded'])
    def test_cached_artwork_mapping_is_verified_without_library_scan(self):
        album=ET.fromstring('<MediaContainer><Album type="album" ratingKey="42"/></MediaContainer>')
        folder=server.destination(dict(self.disc,release='discogs-1'),1).parent
        expected='/music/'+str(folder.relative_to(server.MUSIC))
        tracks=ET.fromstring('<MediaContainer><Track><Media><Part file="'+expected+'/song.flac"/></Media></Track></MediaContainer>')
        with patch.object(server,'plex_request',side_effect=[album,tracks]) as request:
            result=artwork.matching_albums(dict(self.disc,release='discogs-1'),['42'])
            self.assertEqual(result[0].get('ratingKey'),'42');self.assertEqual(request.call_count,2)
            self.assertNotIn(unittest.mock.call('/library/sections'),request.call_args_list)

    def test_unknown_artist_stays_outside_plex(self):
        self.disc['artist']='Onbekende artiest';self.disc['tracks'][0]['artist']='Onbekende artiest'
        self.assertFalse(server.publishable(self.disc,1));self.assertTrue(server.destination(self.disc,1).is_relative_to(server.ROOT))

if __name__=='__main__':unittest.main()

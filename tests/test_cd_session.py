"""Simulated optical media only: no drive, MPD or remote service is contacted."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import tests
import app as player
from archive import Archive
from cd_session import completely_stored, load_ejected


def album():
    return {'id':'TESTDISC1','present':True,'inserted':True,'title':'Test album',
            'tracks':[{'number':n,'sectors':750,'seconds':10,'title':str(n)} for n in (1,2)]}


def stored():
    return {'disc_id':'TESTDISC1','stored':2,'total':2,'states':{
        n:{'ready':True,'storage':'ready'} for n in (1,2)}}


class SessionTests(unittest.TestCase):
    def test_only_complete_matching_server_confirmation_allows_eject(self):
        self.assertTrue(completely_stored(album(),stored()))
        for change in ({'disc_id':'OTHERDISC'},{'stored':1},{'error':'offline'},
                       {'blocked':1},{'skipped':1},{'states':{}},{'total':0},
                       {'states':{1:{'ready':True,'storage':'ready'},2:{'ready':False,'storage':'processing'}}}):
            with self.subTest(change=change):self.assertFalse(completely_stored(album(),{**stored(),**change}))

    def test_detached_metadata_restore_is_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'session.json'
            disc={**album(),'inserted':False,'ejected':True}
            path.write_text(json.dumps(disc));self.assertTrue(load_ejected(path)['present'])
            for changed in ({'ejected':False},{'inserted':True},{'id':'../private'}, {'tracks':[{'number':1,'sectors':-1}]}):
                path.write_text(json.dumps({**disc,**changed}));self.assertIsNone(load_ejected(path))

    def fixture(self,root):
        store=Mock();store.snapshot.return_value=stored();store.reading.return_value=False;store.can_detach.return_value=True
        store.optical.acquire.side_effect=lambda:(root/'optical.lock').open('a+b')
        return store

    def test_api_eject_preserves_mpd_local_pin_and_tracklist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=self.fixture(root);pin=object();store.selected_local=pin
            with patch.object(player,'DATA',root),patch.object(player,'disc',album()), \
                 patch.object(player,'archive',store),patch.object(player,'source','cd'), \
                 patch.object(player.libdiscid,'read',return_value=SimpleNamespace(id='TESTDISC1')), \
                 patch.object(player.subprocess,'run') as eject,patch.object(player,'mpd') as mpd:
                response=player.app.test_client().post('/api/action',json={'action':'eject'},headers={'X-CDSpeler':'1'})
                self.assertEqual(response.status_code,200)
                self.assertTrue(player.disc['present']);self.assertTrue(player.disc['ejected'])
                self.assertFalse(player.disc['inserted']);self.assertEqual(len(player.disc['tracks']),2)
                self.assertTrue(load_ejected(root/'cd-session.json')['ejected'])
                self.assertEqual(eject.call_args.args[0][0],'eject')
                self.assertTrue(eject.call_args.kwargs['pass_fds'])
                mpd.assert_not_called();store.cancel.assert_not_called()
                self.assertIs(store.selected_local,pin)
                store.metadata.assert_called_once()
                self.assertFalse(player.eject_cd(automatic=True));self.assertEqual(eject.call_count,1)

    def test_auto_eject_waits_for_processing_and_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=self.fixture(root)
            with patch.object(player,'DATA',root),patch.object(player,'disc',album()),patch.object(player,'archive',store), \
                 patch.object(player.subprocess,'run') as eject:
                store.snapshot.return_value={**stored(),'stored':1};store.can_detach.return_value=False
                self.assertFalse(player.eject_cd(automatic=True))
                with self.assertRaises(RuntimeError):player.eject_cd()
                store.snapshot.return_value=stored();store.reading.return_value=True
                self.assertFalse(player.eject_cd(automatic=True));eject.assert_not_called()

    def test_auto_eject_failure_does_not_loop_or_stop_playback_and_manual_can_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=self.fixture(root)
            with patch.object(player,'DATA',root),patch.object(player,'source','cd'),patch.object(player,'disc',album()), \
                 patch.object(player,'archive',store),patch.object(player,'mpd') as mpd, \
                 patch.object(player.libdiscid,'read',return_value=SimpleNamespace(id='TESTDISC1')), \
                 patch.object(player.subprocess,'run',side_effect=[OSError('drive failed'),None]) as eject:
                player.maybe_auto_eject();player.maybe_auto_eject()
                self.assertEqual(eject.call_count,1);self.assertIn('eject_error',player.disc)
                self.assertTrue(player.disc['ejected']);self.assertTrue(player.disc['eject_uncertain'])
                self.assertTrue(load_ejected(root/'cd-session.json')['ejected'])
                self.assertTrue(player.confirm_eject_scan('TESTDISC1'))
                self.assertTrue(player.disc['inserted']);self.assertFalse((root/'cd-session.json').exists())
                self.assertTrue(player.eject_cd());self.assertEqual(eject.call_count,2)
                mpd.assert_not_called();store.cancel.assert_not_called()

    def test_changed_disc_is_not_ejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=self.fixture(root)
            with patch.object(player,'DATA',root),patch.object(player,'disc',album()),patch.object(player,'archive',store), \
                 patch.object(player.libdiscid,'read',return_value=SimpleNamespace(id='OTHERDISC')), \
                 patch.object(player.subprocess,'run') as eject:
                with self.assertRaises(RuntimeError):player.eject_cd()
                eject.assert_not_called()

    def test_missing_physical_disc_does_not_cancel_detached_album(self):
        class End(BaseException):pass
        detached={**album(),'inserted':False,'ejected':True}
        with patch.object(player,'disc',detached),patch.object(player,'source','cd'), \
             patch.object(player.dvd,'busy',return_value=False),patch.object(player.archive,'reading',return_value=False), \
             patch.object(player.archive,'cancel') as cancel,patch.object(player,'mpd') as mpd, \
             patch.object(player.libdiscid,'read',side_effect=player.libdiscid.DiscError()), \
             patch.object(player.time,'sleep',side_effect=End):
            with self.assertRaises(End):player.scan_loop()
            self.assertIs(player.disc,detached);cancel.assert_not_called();mpd.assert_not_called()

    def test_detached_album_never_starts_a_reader(self):
        archive=Archive.__new__(Archive);archive.lock=threading.RLock();archive.disc={'ejected':True}
        self.assertFalse(archive._produce_once())

    def test_metadata_update_preserves_current_local_source(self):
        archive=Archive.__new__(Archive);archive.lock=threading.RLock();archive.disc=album()
        archive.wake=threading.Event();archive.local={1:object()};archive.selected_local='pinned'
        before=archive.local[1];archive.metadata({**album(),'ejected':True,'inserted':False})
        self.assertIs(archive.local[1],before);self.assertEqual(archive.selected_local,'pinned')
        self.assertTrue(archive.disc['ejected'])

    def test_lost_eject_ack_then_empty_drive_confirms_without_mpd_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=self.fixture(root)
            with patch.object(player,'DATA',root),patch.object(player,'disc',album()),patch.object(player,'archive',store), \
                 patch.object(player,'mpd') as mpd,patch.object(player.libdiscid,'read',return_value=SimpleNamespace(id='TESTDISC1')), \
                 patch.object(player.subprocess,'run',side_effect=TimeoutError):
                with self.assertRaises(RuntimeError):player.eject_cd()
                self.assertTrue(player.confirm_eject_scan())
                self.assertTrue(player.disc['ejected']);self.assertNotIn('eject_uncertain',player.disc)
                mpd.assert_not_called();store.cancel.assert_not_called()

    def test_manual_eject_can_release_partial_album_without_stopping_complete_local_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=self.fixture(root);store.snapshot.return_value={**stored(),'stored':1}
            with patch.object(player,'DATA',root),patch.object(player,'disc',album()),patch.object(player,'archive',store), \
                 patch.object(player,'mpd') as mpd,patch.object(player.libdiscid,'read',return_value=SimpleNamespace(id='TESTDISC1')), \
                 patch.object(player.subprocess,'run'):
                self.assertTrue(player.eject_cd());self.assertTrue(player.disc['ejected'])
                mpd.assert_not_called();store.cancel.assert_not_called()

    def test_only_complete_pinned_wav_can_survive_manual_detach(self):
        archive=Archive.__new__(Archive);archive.lock=threading.RLock();archive.selected_local='pin'
        pin=SimpleNamespace(token='pin',complete=False);archive.local={1:pin}
        self.assertFalse(archive.can_detach());pin.complete=True;self.assertTrue(archive.can_detach())

    def test_stale_scan_results_and_errors_cannot_reverse_eject(self):
        for raises in (False,True):
            detached={**album(),'ejected':True,'inserted':False}
            def read(*args,**kwargs):
                player.media_revision += 1;player.disc=detached
                if raises:raise player.libdiscid.DiscError()
                return SimpleNamespace(id='TESTDISC1')
            stop=SimpleNamespace(is_set=Mock(side_effect=[False,True]))
            with self.subTest(raises=raises),patch.object(player,'media_revision',0),patch.object(player,'disc',album()), \
                 patch.object(player,'runtime_stop',stop),patch.object(player,'source','cd'), \
                 patch.object(player.archive,'reading',return_value=False),patch.object(player.dvd,'busy',return_value=False), \
                 patch.object(player.libdiscid,'read',side_effect=read),patch.object(player.archive,'cancel') as cancel, \
                 patch.object(player,'accept_disc') as accept,patch.object(player,'mpd') as mpd:
                player.scan_loop();self.assertIs(player.disc,detached)
                cancel.assert_not_called();accept.assert_not_called();mpd.assert_not_called()

    def test_uncertain_manual_retry_is_an_explicit_error_not_false_success(self):
        with patch.object(player,'disc',{**album(),'ejected':True,'inserted':False,'eject_uncertain':True}):
            with self.assertRaisesRegex(RuntimeError,'gecontroleerd'):player.eject_cd()

    def test_restore_waits_for_confirmed_server_inventory_before_skipping_missing_tracks(self):
        archive=Archive.__new__(Archive);archive.lock=threading.RLock()
        archive.disc={**album(),'ejected':True};archive.states={1:{'storage':'pending'}}
        archive.local={};archive.inflight=set();archive.remote=None;archive.server_error=None
        archive.initial_status=threading.Event()
        self.assertFalse(archive.unavailable(1))
        archive.initial_status.set();self.assertFalse(archive.unavailable(1))
        archive.remote={'id':'OTHERDISC'};self.assertFalse(archive.unavailable(1))
        archive.remote={'id':'TESTDISC1'};self.assertTrue(archive.unavailable(1))
        archive.server_error='offline';self.assertFalse(archive.unavailable(1))
        archive.server_error=None;archive.states[1]={'uploaded':True};self.assertFalse(archive.unavailable(1))

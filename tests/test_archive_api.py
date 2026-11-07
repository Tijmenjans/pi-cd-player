"""Run on the Pi; isolated Flask client and fake audio, never touches live playback."""
import tempfile
import json
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
import tests as _isolated_test_state
import app as player
from archive_queue import ArchiveQueue
from live_audio import GrowingWav, RATE, wav_header


class Store:
    def attach(self,disc): pass
    def prioritize(self,order): self.order=order
    def ready(self,n): return n==1
    playable=ready
    def playback_uri(self,n):return f'http://127.0.0.1:8080/audio/TESTDISC1/{n}'
    server_uri=playback_uri
    def local_end_seconds(self,n):return None
    def release_playback(self):pass
    def snapshot(self):
        return {'stored':1,'total':3,'error':None,'states':{
            1:{'storage':'ready','ready':True},2:{'storage':'ripping','ready':False,'progress':30},
            3:{'storage':'pending','ready':False}}}


class MPD:
    def __init__(self): self.state='stop'
    def __call__(self,*commands):
        rows=[]
        for c in commands:
            if c.startswith('play'):self.state='play'
            if c.startswith('pause'):self.state='pause'
            if c=='stop':self.state='stop'
            rows.append(['state: '+self.state,'elapsed: 2','audio: 44100:16:2'] if c=='status' else [])
        return rows


class APITests(unittest.TestCase):
    def test_skipped_archive_track_is_removed_from_pending_and_shuffle_rounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store();store.skipped={'TESTDISC1':[2]}
            q=ArchiveQueue(MPD(),Path(tmp)/'queue.json',store)
            disc={'id':'TESTDISC1','present':True,'tracks':[{'number':n} for n in (1,2,3)]}
            q.attach(disc)
            q.data['pending']=2
            q.attach(disc)
            self.assertEqual(q.data['order'],[1,3])
            self.assertEqual(q.data['all_tracks'],[1,3])
            self.assertIsNone(q.data['pending'])

    def test_names_publish_before_slow_cover_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            disc={'id':'TEST','tracks':[{'number':1,'title':'Track 1'}]}
            release={'id':'edition','title':'Found album','artist':'Singer',
                     'tracks':['Found song'],'track_artists':['Singer']}
            Path(tmp,'TEST.json').write_text(json.dumps({'version':3,'releases':[release]}))
            def cover_request(*args,**kwargs):
                self.assertEqual(player.disc['tracks'][0]['title'],'Found song')
                self.assertEqual(player.disc['tracks'][0]['artist'],'Singer')
                self.assertEqual(player.disc['metadata_status'],'found')
                raise TimeoutError('cover server is slow')
            with patch.object(player,'DATA',Path(tmp)),patch.object(player,'disc',disc), \
                 patch.object(player.urllib.request,'urlopen',side_effect=cover_request), \
                 patch.object(player.archive,'metadata') as metadata:
                player.enrich(dict(disc))
                self.assertEqual(player.disc['tracks'][0]['title'],'Found song')
                metadata.assert_called_once()

    def test_known_titles_are_visible_before_first_import_despite_stale_archive(self):
        disc={'id':'TEST','present':True,'release':'new-edition','metadata_status':'found',
              'title':'Found album','artist':'Various Artists',
              'tracks':[{'number':n,'title':'Song '+str(n),'artist':'Singer '+str(n),'seconds':100}
                        for n in range(1,4)]}
        saved={'stored':0,'total':3,'states':{n:{'ready':False,'storage':'pending'} for n in range(1,4)},
               'metadata':{'title':'Audio-cd','artist':'Onbekende artiest'},
               'track_metadata':{n:{'title':'Track '+str(n),'artist':'Wrong artist','seconds':95}
                                 for n in range(1,4)}}
        with patch.object(player,'disc',disc),patch.object(player,'source','cd'), \
             patch.object(player.archive,'snapshot',return_value=saved), \
             patch.object(player.queue,'observe',return_value=({'state':'stop'},{})):
            result=player.app.test_client().get('/api/status').get_json()
        self.assertEqual(result['archive']['stored'],0)
        self.assertEqual(result['disc']['title'],'Found album')
        self.assertEqual(result['disc']['release'],'new-edition')
        for n,t in enumerate(result['disc']['tracks'],1):
            self.assertEqual(t['title'],'Song '+str(n))
            self.assertEqual(t['artist'],'Singer '+str(n))
            self.assertEqual(t['seconds'],95)
            self.assertFalse(t['ready'])

    def test_cdtext_is_read_and_applied_before_player_or_ripper_attach(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        class EndScan(BaseException):pass
        events=[]
        cd=SimpleNamespace(id='TESTDISC1',toc='TOC',first_track=1,track_lengths=[75]*4)
        media={'cd_text':{'status':'present','album':{'title':'CD album','artist':'CD artist'},
                         'tracks':{'1':{'title':'First song'}}}}
        def probe(snapshot,directory,**kwargs):events.append('cdtext');return media
        def attach(snapshot,autoplay):
            events.append('attach')
            self.assertEqual(snapshot['title'],'CD album')
            self.assertEqual(snapshot['tracks'][0]['title'],'First song')
            self.assertEqual(snapshot['tracks'][0]['artist'],'CD artist')
            raise EndScan()
        archive=Mock();archive.optical=player.archive.optical;archive.reading.return_value=False
        archive.cancel.side_effect=lambda:events.append('cancel')
        with patch.object(player,'archive',archive),patch.object(player,'disc',{}), \
             patch.object(player,'media_changed',return_value=True), \
             patch.object(player.libdiscid,'read',return_value=cd), \
             patch.object(player.disc_media,'cached_probe',side_effect=probe), \
             patch.object(player,'accept_disc',side_effect=attach):
            with self.assertRaises(EndScan):player.scan_loop()
        self.assertEqual(events,['cancel','cdtext','attach'])

    def test_temporary_failure_retries_and_recovers_without_reinserting_cd(self):
        with tempfile.TemporaryDirectory() as tmp:
            disc={'id':'TEST','toc':'TOC','artist':'Album wordt opgezocht…',
                  'tracks':[{'number':n,'title':'Track '+str(n),'sectors':7500} for n in range(1,5)]}
            payload={'releases':[{'id':'edition','title':'Recovered album','artist-credit':[{'name':'Singer'}],
                'media':[{'position':1,'discs':[],
                          'tracks':[{'title':'Song '+str(n),'length':100000} for n in range(1,5)]}]}]}
            missing=urllib.error.HTTPError('test',404,'missing',{},None)
            Path(tmp,'edition-1200.jpg').write_bytes(b'cover')
            def wait(snapshot,job,delay):
                self.assertEqual(player.disc['metadata_status'],'retrying')
                self.assertEqual(delay,5)
                self.assertFalse(Path(tmp,'TEST.json').exists())
                return True
            with patch.object(player,'DATA',Path(tmp)),patch.object(player,'disc',disc), \
                 patch.object(player,'get_musicbrainz_json',side_effect=[TimeoutError(),missing,payload]) as fetch, \
                 patch.object(player,'metadata_wait',side_effect=wait) as waiting, \
                 patch.object(player.archive,'metadata'):
                player.enrich(dict(disc))
                self.assertEqual(player.disc['metadata_status'],'found')
                self.assertEqual(player.disc['metadata_match'],'toc')
                self.assertEqual(player.disc['tracks'][0]['title'],'Song 1')
                self.assertIsNone(player.disc['metadata_error'])
                self.assertIsNone(player.disc['metadata_retry_at'])
                self.assertEqual(fetch.call_count,3);waiting.assert_called_once()

    def test_old_negative_cache_gets_broader_lookup_and_ambiguous_match_needs_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            disc={'id':'TEST','toc':'TOC','tracks':[{'number':1,'title':'Track 1'}]}
            Path(tmp,'TEST.json').write_text(json.dumps({'version':3,'releases':[]}))
            matches=[{'id':x,'title':'Album '+x,'artist':'Singer','tracks':['Song'],
                      'disc_number':1,'disc_total':1} for x in ['one','two']]
            with patch.object(player,'DATA',Path(tmp)),patch.object(player,'disc',disc), \
                 patch.object(player.music_metadata,'lookup',return_value={
                     'version':3,'match_kind':'toc','releases':matches}) as lookup, \
                 patch.object(player.archive,'metadata'):
                player.enrich(dict(disc))
                lookup.assert_called_once()
                self.assertEqual(player.disc['metadata_status'],'choose')
                self.assertNotIn('release',player.disc)
                self.assertEqual(len(player.disc['releases']),2)

    def test_non_network_error_is_not_reported_as_offline_or_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            disc={'id':'TEST','tracks':[]}
            with patch.object(player,'DATA',Path(tmp)),patch.object(player,'disc',disc), \
                 patch.object(player.music_metadata,'lookup',side_effect=ValueError('bad data')), \
                 patch.object(player,'metadata_wait') as wait:
                player.enrich(dict(disc))
                self.assertEqual(player.disc['metadata_status'],'error')
                wait.assert_not_called()

    def test_slow_metadata_request_does_not_block_player_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store();mpd=MPD();q=ArchiveQueue(mpd,Path(tmp)/'queue.json',store)
            disc={'id':'TEST','toc':'TOC','present':True,'tracks':[
                {'number':n,'title':'Track '+str(n),'sectors':7500} for n in range(1,4)]}
            entered=threading.Event();release=threading.Event()
            def slow(url):
                entered.set();release.wait(3);return {'releases':[]}
            with patch.object(player,'DATA',Path(tmp)),patch.object(player,'disc',disc), \
                 patch.object(player,'archive',store),patch.object(player,'queue',q), \
                 patch.object(player,'mpd',mpd),patch.object(player,'source','cd'), \
                 patch.object(player,'get_musicbrainz_json',side_effect=slow):
                store.metadata=lambda d:None
                worker=threading.Thread(target=player.enrich,args=(dict(disc),))
                worker.start()
                try:
                    self.assertTrue(entered.wait(1))
                    started=time.monotonic()
                    response=player.app.test_client().get('/api/status')
                    self.assertEqual(response.status_code,200)
                    self.assertLess(time.monotonic()-started,1)
                    self.assertFalse(release.is_set())
                finally:release.set();worker.join(4)
                self.assertFalse(worker.is_alive())

    def test_late_cdtext_survives_online_enrichment_and_keeps_disc_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            disc={'id':'TEST','toc':'TOC','tracks':[{'number':1,'title':'Track 1'}],
                  'disc_media':{'cd_text':{'status':'present','album':{'title':'CD title'},
                                         'tracks':{'1':{'title':'CD song','artist':'CD artist'}}}}}
            stale={**disc,'disc_media':{'cd_text':{'status':'pending'}}}
            metadata={'version':3,'releases':[{'id':'edition','title':'Online album',
                       'artist':'Various Artists','disc_number':2,'disc_total':4,
                       'tracks':['Online song'],'track_artists':['Online artist']}]}
            Path(tmp,'TEST.json').write_text(__import__('json').dumps(metadata))
            Path(tmp,'edition-1200.jpg').write_bytes(b'cached cover')
            with patch.object(player,'DATA',Path(tmp)),patch.object(player,'disc',disc), \
                 patch.object(player.archive,'metadata') as update:
                player.enrich(stale)
                self.assertEqual(player.disc['title'],'CD title')
                self.assertEqual(player.disc['tracks'][0]['artist'],'CD artist')
                self.assertEqual((player.disc['disc_number'],player.disc['disc_total']),(2,4))
                self.assertEqual(player.disc['cover'],'/cover/edition-1200.jpg')
                self.assertEqual(player.disc['disc_media']['cd_text']['status'],'present')
                update.assert_called_once()

    def test_cdtext_discarded_when_cd_swapped_during_probe(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            disc={'id':'OLD','toc':'TOC','title':'Original','tracks':[]}
            cache=Path(tmp,'OLD-disc-media.json');cache.write_text('{}')
            with patch.object(player,'DATA',Path(tmp)),patch.object(player,'disc',disc), \
                 patch.object(player.disc_media,'cached_probe',return_value={'cd_text':{'status':'present'}}), \
                 patch.object(player.libdiscid,'read',return_value=SimpleNamespace(id='NEW',toc='NEWTOC')), \
                 patch.object(player.archive,'metadata') as update:
                self.assertIsNone(player.prepare_disc(dict(disc)))
                self.assertEqual(player.disc['title'],'Original')
                self.assertFalse(cache.exists());update.assert_not_called()

    def test_missing_discid_is_unknown_rather_than_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            disc={'id':'MISSING_DISC','tracks':[{'number':1,'sectors':75,'title':'Track 1'}]}
            error=urllib.error.HTTPError('https://musicbrainz.org',404,'Not found',{},None)
            with patch.object(player,'DATA',Path(tmp)),patch.object(player,'disc',disc), \
                 patch.object(player,'get_json',side_effect=error),patch.object(player.archive,'metadata'):
                player.enrich(dict(disc))
                self.assertEqual(player.disc['metadata_status'],'unknown')
                self.assertEqual(player.disc['artist'],'Onbekende artiest')

    def test_autoplay_with_saved_shuffle_uses_archive_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store();mpd=MPD();q=ArchiveQueue(mpd,Path(tmp)/'queue.json',store)
            q.data={'shuffle':True}
            disc=dict(id='TESTDISC1',present=True,tracks=[dict(number=n,title=str(n),seconds=100,sectors=7500)
                                                      for n in range(1,4)])
            with patch.object(player,'archive',store),patch.object(player,'queue',q), \
                 patch.object(player,'mpd',mpd),patch.object(player,'disc',{}), \
                 patch.object(player,'choose_source'):
                player.accept_disc(disc,autoplay=True)
                self.assertNotIn('autoplay_error',player.disc)
                self.assertTrue(q.data['shuffle']);self.assertEqual(q.loaded,1)

    def test_local_audio_ranges_head_and_loopback_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'audio.wav';pcm=b'\xe8\x03\x18\xfc'*RATE*4
            path.write_bytes(wav_header(RATE*4)+pcm)
            live=GrowingWav(path,RATE*4);live.refresh(complete=True)
            self.addCleanup(live.close)
            store=Store()
            def local_audio(identity,number,token):
                if identity!='TESTDISC1' or number!=1 or token!=live.token:raise FileNotFoundError()
                return live.open()
            store.local_audio=local_audio
            with patch.object(player,'archive',store):
                c=player.app.test_client();uri='/audio/TESTDISC1/1?local='+live.token
                response=c.get(uri,headers={'Range':'bytes=40-53'})
                self.assertEqual(response.status_code,206)
                self.assertEqual(response.data,path.read_bytes()[40:54]);response.close()
                response=c.head(uri)
                self.assertEqual(response.status_code,200)
                self.assertEqual(int(response.headers['Content-Length']),44+len(pcm));response.close()
                self.assertEqual(c.get(uri,headers={'Range':'bytes=99999999-'}).status_code,416)
                self.assertEqual(c.get(uri+'bad').status_code,404)
                self.assertEqual(c.get(uri,environ_base={'REMOTE_ADDR':'192.168.1.99'}).status_code,403)

    def test_queue_storage_and_cross_site_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store();mpd=MPD();q=ArchiveQueue(mpd,Path(tmp)/'queue.json',store)
            disc=dict(id='TESTDISC1',present=True,tracks=[dict(number=n,title=str(n),seconds=100,sectors=7500)
                                                     for n in range(1,4)])
            with patch.object(player,'archive',store),patch.object(player,'queue',q), \
                 patch.object(player,'mpd',mpd),patch.object(player,'disc',disc),patch.object(player,'source','cd'):
                c=player.app.test_client()
                def action(name,**kw):
                    return c.post('/api/action',json={'action':name,**kw},headers={'X-CDSpeler':'1'})
                self.assertEqual(action('play').status_code,200)
                data=c.get('/api/status').get_json()
                self.assertEqual(data['player']['track'],1)
                self.assertTrue(data['disc']['tracks'][0]['ready'])
                self.assertFalse(data['disc']['tracks'][1]['ready'])
                self.assertEqual(action('queue-order',tracks=[3,2]).status_code,400)
                self.assertEqual(action('track',track=3).status_code,200)
                data=c.get('/api/status').get_json()
                self.assertEqual(data['player']['pending_track'],3)
                self.assertEqual(data['player']['track'],1)
                self.assertEqual(c.post('/api/action',json={'action':'stop'}).status_code,403)
                self.assertEqual(c.get('/audio/TESTDISC1/1',environ_base={'REMOTE_ADDR':'192.168.1.99'}).status_code,403)

    def test_multidisc_metadata(self):
        payload={'releases':[{'id':'release','title':'Album','artist-credit':[{'name':'Various Artists'}],
                   'media':[{'position':1,'discs':[],'tracks':[]},
                            {'position':2,'discs':[{'id':'TEST'}],
                             'tracks':[{'title':'Song','artist-credit':[{'name':'Singer'}]}]}]}]}
        r=player.release_metadata(payload,{'id':'TEST','tracks':[{}]})['releases'][0]
        self.assertEqual((r['disc_number'],r['disc_total']),(2,2))
        self.assertEqual(r['track_artists'],['Singer'])


if __name__=='__main__': unittest.main(verbosity=2)

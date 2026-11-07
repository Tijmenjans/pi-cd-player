import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import disc_media


class DiscMediaTests(unittest.TestCase):
    def setUp(self):
        device=patch('disc_media.optical_device',return_value='/dev/sr1');device.start();self.addCleanup(device.stop)
    def test_combined_title_splits_artist_once_and_keeps_raw_cdtext(self):
        snapshot={'title':'Album','artist':'Onbekende artiest',
                  'tracks':[{'number':1,'title':'Track 1'}]}
        for separator in [' - ']:
            media={'cd_text':{'status':'present','album':{},'tracks':{
                '1':{'title':'Jean-Claude Ades'+separator+'Song - Extended Mix'}}}}
            original=copy.deepcopy(media)
            result=disc_media.apply_text(snapshot,media)
            self.assertEqual(result['tracks'][0]['artist'],'Jean-Claude Ades')
            self.assertEqual(result['tracks'][0]['title'],'Song - Extended Mix')
            self.assertEqual(media,original)
            self.assertEqual(disc_media.apply_text(result,media),result)

    def test_explicit_performer_and_unspaced_hyphen_are_preserved(self):
        snapshot={'title':'Album','tracks':[{'number':1}]}
        media={'cd_text':{'status':'present','album':{},'tracks':{
            '1':{'title':'Love - Hate','artist':'Singer'}}}}
        result=disc_media.apply_text(snapshot,media)
        self.assertEqual(result['tracks'][0]['title'],'Love - Hate')
        self.assertEqual(result['tracks'][0]['artist'],'Singer')
        media['cd_text']['tracks']['1']={'title':'Re-Entry'}
        result=disc_media.apply_text(snapshot,media)
        self.assertEqual(result['tracks'][0]['title'],'Re-Entry')
        self.assertNotIn('artist',result['tracks'][0])
        for title in ['Singer – Song','Singer — Song','Singer-Song','Singer- Song','Singer -Song']:
            media['cd_text']['tracks']['1']={'title':title}
            result=disc_media.apply_text(snapshot,media)
            self.assertEqual(result['tracks'][0]['title'],title)
            self.assertNotIn('artist',result['tracks'][0])

    def test_titles_without_performer_do_not_export_loading_text_as_artist(self):
        snapshot={'title':'Audio-cd','artist':'Album wordt opgezocht…',
                  'tracks':[{'number':1,'title':'Track 1'}]}
        result=disc_media.apply_text(snapshot,{'cd_text':{'status':'present',
                    'album':{'title':'CD album'},'tracks':{'1':{'title':'Real song'}}}})
        self.assertEqual(result['artist'],'Onbekende artiest')
        self.assertEqual(result['tracks'][0]['title'],'Real song')
        self.assertEqual(result['metadata_status'],'found')

    def test_cdtext_wins_but_keeps_edition_cover_and_missing_fields(self):
        disc={'title':'Online album','artist':'Various Artists','release':'edition',
              'disc_number':2,'disc_total':4,'cover':'cover.jpg','date':'2001',
              'tracks':[{'number':1,'title':'Online title','artist':'Online singer','seconds':100},
                        {'number':2,'title':'Other title','artist':'Other singer'}]}
        original=copy.deepcopy(disc)
        media={'cd_text':{'status':'present','album':{'title':'Local album'},
                         'tracks':{'1':{'title':'Local title','artist':'Local singer'}}}}
        result=disc_media.apply_text(disc,media)
        self.assertEqual(result['title'],'Local album')
        self.assertEqual(result['tracks'][0]['artist'],'Local singer')
        self.assertEqual(result['tracks'][1],disc['tracks'][1])
        for key in ['artist','release','disc_number','disc_total','cover','date']:
            self.assertEqual(result[key],disc[key])
        self.assertEqual(result['metadata_source'],'cdtext')
        self.assertEqual(disc,original)

    def test_absent_or_failed_text_never_erases_existing_metadata(self):
        disc={'title':'Album','tracks':[{'number':1,'title':'Song'}]}
        for status in ['pending','absent','unavailable','unreadable']:
            self.assertEqual(disc_media.apply_text(disc,{'cd_text':{'status':status}}),disc)
        self.assertEqual(disc_media.decode_cdtext(b'\0\2\0\0',20)['status'],'absent')

    def test_cached_absence_skips_optical_probe_but_different_toc_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot={'id':'TEST','toc':'1 2 999'}
            cached={**snapshot,'version':disc_media.VERSION,'toc_status':'read',
                    'cd_text':{'status':'absent'},'data_tracks':[]}
            Path(tmp,'TEST-disc-media.json').write_text(json.dumps(cached))
            with patch.object(disc_media.subprocess,'run') as run:
                self.assertEqual(disc_media.cached_probe(snapshot,tmp),cached)
                run.assert_not_called()
            self.assertIsNone(disc_media.read_cache({**snapshot,'toc':'different'},tmp))

    def test_timeout_is_unavailable_and_not_permanently_cached_as_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot={'id':'TEST','toc':'TOC'}
            with patch.object(disc_media.subprocess,'run',side_effect=subprocess.TimeoutExpired('probe',45)):
                result=disc_media.cached_probe(snapshot,tmp)
            self.assertEqual(result['cd_text']['status'],'unavailable')
            self.assertIsNone(disc_media.read_cache(snapshot,tmp))


if __name__=='__main__':unittest.main(verbosity=2)

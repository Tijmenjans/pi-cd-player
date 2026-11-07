import unittest,tempfile,threading,subprocess
from pathlib import Path
from unittest.mock import patch
from dvd import DVD,parse_disc
XML='''<lsdvd><title>TEST_DVD</title><longest_track>2</longest_track><track><ix>1</ix><length>20</length></track><track><ix>2</ix><length>6650</length><width>720</width><height>576</height><aspect>16:9</aspect><chapter/><chapter/><audio><langcode>en</langcode></audio><audio><langcode>fr</langcode></audio><subp><langcode>nl</langcode></subp></track></lsdvd>'''
class Child:
 def __init__(self):self.stopped=False
 def poll(self):return 0 if self.stopped else None
 def terminate(self):self.stopped=True
 def wait(self,timeout=None):return 0
class Tests(unittest.TestCase):
 def setUp(self):
  device=patch('dvd.optical_device',return_value='/dev/sr1');device.start();self.addCleanup(device.stop)
  mock=patch('dvd.MovieMetadata.get',return_value=None);mock.start();self.addCleanup(mock.stop)
 def test_parse_duration_languages_and_video(self):
  s=parse_disc(XML);self.assertEqual(s['main_title'],2);self.assertEqual(s['seconds'],6650);self.assertTrue(s['dutch_subtitles']);self.assertEqual(s['audio_languages'],['Engels','Frans']);self.assertEqual(s['chapters'],2);self.assertEqual(s['width'],720)
 def test_no_dutch(self):self.assertFalse(parse_disc(XML.replace('<langcode>nl','<langcode>it'))['dutch_subtitles'])
 def test_missing_disc(self):self.assertIsNone(parse_disc('no disc'))
 def test_one_stream_and_old_cleanup(self):
  with tempfile.TemporaryDirectory() as path:
   d=DVD(path,observe=False);token=d.reserve_stream()
   with self.assertRaises(RuntimeError):d.reserve_stream()
   child=Child();d.attach_stream(token,child,parse_disc(XML));d.stop_stream();self.assertTrue(child.stopped)
   newer=d.reserve_stream();d.finish_stream(token);self.assertTrue(d.is_streaming());d.finish_stream(newer);self.assertFalse(d.is_streaming())
 def test_eject_stops_stream_and_clears_disc(self):
  with tempfile.TemporaryDirectory() as path:
   d=DVD(path,observe=False);token=d.reserve_stream();child=Child();d.attach_stream(token,child,parse_disc(XML))
   with patch('dvd.subprocess.run') as run:
    d.eject();run.assert_called_once();self.assertEqual(run.call_args.args[0],['eject','/dev/sr1'])
   self.assertTrue(child.stopped);self.assertFalse(d.snapshot()['present']);self.assertEqual(d.snapshot()['state'],'absent')
 def test_eject_error_keeps_disc_and_allows_retry(self):
  with tempfile.TemporaryDirectory() as path:
   d=DVD(path,observe=False);d.media=parse_disc(XML)
   with patch('dvd.subprocess.run',side_effect=subprocess.CalledProcessError(1,'eject')):
    with self.assertRaises(subprocess.CalledProcessError):d.eject()
   self.assertTrue(d.snapshot()['present']);self.assertFalse(d.ejecting)
if __name__=='__main__':unittest.main()

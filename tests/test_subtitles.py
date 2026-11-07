import unittest
from dvd_streaming import dutch_subtitle,remux_command
class Tests(unittest.TestCase):
 def subs(self,*languages):return [{'codec_type':'video'},{'codec_type':'audio'}]+[{'codec_type':'subtitle','tags':{'language':l}} for l in languages]
 def test_dutch_first(self):self.assertEqual(dutch_subtitle(self.subs('dut','eng')),0)
 def test_dutch_later(self):self.assertEqual(dutch_subtitle(self.subs('eng','fre','nld')),2)
 def test_short_code(self):self.assertEqual(dutch_subtitle(self.subs('en','nl')),1)
 def test_missing(self):self.assertIsNone(dutch_subtitle(self.subs('eng','ita')))
 def test_no_subtitles(self):self.assertIsNone(dutch_subtitle(self.subs()))
 def test_unknown_language(self):self.assertIsNone(dutch_subtitle([{'codec_type':'subtitle'}]))
 def test_default_correct_stream_and_no_encoding(self):
  cmd=remux_command('ffmpeg','/dev/sr0',3,self.subs('eng','nld'))
  self.assertIn('0:s:1',cmd);self.assertEqual(cmd[cmd.index('-disposition:s:0')+1],'default')
  self.assertEqual(cmd[cmd.index('-c')+1],'copy');self.assertIn('title=Nederlands',cmd)
 def test_missing_not_marked_dutch(self):self.assertNotIn('title=Nederlands',remux_command('ffmpeg','/dev/sr0',1,self.subs('eng')))
if __name__ == '__main__': unittest.main()

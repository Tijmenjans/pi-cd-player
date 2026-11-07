import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from optical_device import optical_device,OpticalDeviceError
class DeviceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.dev=self.root/'dev';self.sys=self.root/'sys';self.dev.mkdir();self.sys.mkdir()
 def drive(self,name,model='SuperDrive',state='running'):
  d=self.sys/name/'device';d.mkdir(parents=True)
  for file,value in [('type','5'),('state',state),('model',model)]: (d/file).write_text(value)
  (self.dev/name).touch()
 def test_replug_sr1_detected(self):
  self.drive('sr1');self.assertEqual(optical_device(self.dev,self.sys),str(self.dev/'sr1'))
 def test_removed_node_ignored(self):
  self.drive('sr0',state='offline');self.drive('sr1');self.assertTrue(optical_device(self.dev,self.sys).endswith('sr1'))
 def test_permissions_are_not_reported_as_missing_disc(self):
  self.drive('sr1')
  with patch('optical_device.os.access',return_value=False):
   with self.assertRaisesRegex(OpticalDeviceError,'toegangsrechten'):optical_device(self.dev,self.sys)
 def test_disconnected_drive(self):
  with self.assertRaisesRegex(OpticalDeviceError,'Geen aangesloten'):optical_device(self.dev,self.sys)
 def test_multiple_drives_not_guessed(self):
  self.drive('sr0');self.drive('sr1')
  with self.assertRaisesRegex(OpticalDeviceError,'Meerdere'):optical_device(self.dev,self.sys)
if __name__=='__main__':unittest.main()

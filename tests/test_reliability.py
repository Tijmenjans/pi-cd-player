import copy,json,os,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from archive import Archive
from live_audio import wav_header,RATE
from optical_reader import ProgressWatchdog,ReadFailure,DriveBusy,OpticalLease,stop_process

class Clock:
 def __init__(self):self.now=0
 def __call__(self):return self.now
class WatchdogTests(unittest.TestCase):
 def test_stall_checks_bytes_not_wall_time_only(self):
  c=Clock();w=ProgressWatchdog(300,8,clock=c)
  c.now=40;w.check(44);c.now=84;w.check(44);c.now=85
  with self.assertRaises(ReadFailure):w.check(44)
 def test_actual_growth_resets_stall(self):
  c=Clock();w=ProgressWatchdog(1000,4,clock=c)
  for n in range(1,10):c.now+=30;w.check(n*1000)
 def test_trickle_is_still_bounded(self):
  c=Clock();w=ProgressWatchdog(10,8,clock=c)
  for n in range(1,4):c.now=n*30;w.check(n)
  c.now=121
  with self.assertRaises(ReadFailure):w.check(4)
 def test_uninterruptible_process_cannot_hang_worker_shutdown(self):
  p=Mock();p.poll.return_value=None;p.wait.side_effect=subprocess.TimeoutExpired('reader',2)
  self.assertFalse(stop_process(p));p.terminate.assert_called_once();p.kill.assert_called_once();self.assertEqual(p.wait.call_count,2)
 def test_lease_inherited_by_child_outlives_parent_handle(self):
  with tempfile.TemporaryDirectory() as tmp:
   lease=OpticalLease(Path(tmp)/'optical.lock',Path(tmp)/'not-real')
   handle=lease.acquire()
   p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],pass_fds=(handle.fileno(),))
   try:
    handle.close()
    with self.assertRaises(DriveBusy):lease.acquire()
   finally:p.terminate();p.wait(timeout=2)
   lease.acquire().close()

class Cloud:
 def __init__(self,disc):self.disc=disc;self.stored=set();self.calls=[];self.fail=set();self.lose=False
 def request(self,*args):
  s=copy.deepcopy(self.disc)
  for t in s['tracks']:t.update(ready=t['number'] in self.stored,uploaded=t['number'] in self.stored)
  return s
 def upload(self,identity,number,path,**kw):
  self.calls.append(number)
  if number in self.fail:raise TimeoutError('network')
  self.stored.add(number)
  if self.lose:self.lose=False;raise TimeoutError('lost response')
  return self.request()

class ArchiveTests(unittest.TestCase):
 def setUp(self):
  device=patch('archive.optical_device',return_value='/dev/sr0');device.start();self.addCleanup(device.stop)
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  (self.root/'data').mkdir();(self.root/'data/archive.json').write_text(json.dumps({'url':'https://test.invalid','token':'x','rip_speed':24}))
  self.a=Archive(self.root);self.disc={'id':'TESTDISC1','tracks':[{'number':n,'sectors':75} for n in (1,2,3)]};self.cloud=Cloud(self.disc);self.a.cloud=self.cloud;self.a.attach(self.disc)
 def wav(self,path):path.write_bytes(wav_header(RATE)+b'\x01\x00\x01\x00'*RATE)
 def fake_rip(self,d,n,g,target):self.wav(target);return True
 def test_read_retries_bounded_persisted_and_speed_reduced(self):
  def fail(*a):raise ReadFailure('Drive geeft geen data')
  self.a._rip=fail
  for _ in range(3):
   self.a.retry_after.clear();self.a.prioritize([1,2,3]);self.assertFalse(self.a._produce_once())
  self.assertEqual(self.a.states[1]['storage'],'blocked');self.assertEqual(self.a.speed_limit,1)
  self.a._rip=self.fake_rip;self.assertTrue(self.a._produce_once());self.assertEqual(self.a.uploads.get_nowait()['number'],2)
  fresh=Archive(self.root);fresh.cloud=self.cloud;fresh.attach(self.disc)
  self.assertEqual(fresh.states[1]['storage'],'blocked');self.assertEqual(fresh.speed_limit,1)
 def test_monitor_cannot_erase_read_error(self):
  self.a._read_failed(self.disc['id'],1,'Geen data')
  self.a._receive(self.cloud.request(),self.a.generation)
  self.assertIn('Geen data',self.a.snapshot()['error'])
 def test_upload_failure_retains_file_and_slot_and_other_track_can_upload(self):
  self.a._rip=self.fake_rip;self.a._produce_once();self.a._produce_once()
  self.cloud.fail.add(1);self.a._upload_one(self.a.uploads.get_nowait())
  self.assertTrue((self.a.stage/'TESTDISC1-1.wav').exists());self.assertIn(('TESTDISC1',1),self.a.inflight)
  self.a._upload_one(self.a.uploads.get_nowait());self.assertTrue(self.a.ready(2));self.assertFalse(self.a.ready(1))
  self.assertEqual(self.a.states[1]['storage'],'retrying_upload');self.assertIn('Upload',self.a.snapshot()['error'])
 def test_lost_response_is_confirmed_without_second_upload(self):
  self.a._rip=self.fake_rip;self.a._produce_once();self.cloud.lose=True
  self.a._upload_one(self.a.uploads.get_nowait());self.a._upload_one(self.a.uploads.get_nowait())
  self.assertEqual(self.cloud.calls,[1]);self.assertTrue(self.a.ready(1))
 def test_full_wav_survives_restart_without_reread(self):
  target=self.a.stage/'TESTDISC1-1.wav';self.wav(target);self.a._rip=Mock(side_effect=AssertionError('reread'))
  self.assertTrue(self.a._produce_once());self.a._rip.assert_not_called()
 def test_invalid_wav_is_not_uploaded(self):
  target=self.a.stage/'TESTDISC1-1.wav';target.write_bytes(b'bad')
  self.a._rip=Mock(side_effect=ReadFailure('retry'))
  self.assertFalse(self.a._produce_once());self.assertFalse(target.exists());self.assertTrue(self.a.uploads.empty())
 def test_truncated_wav_with_valid_header_is_not_reused(self):
  target=self.a.stage/'TESTDISC1-1.wav';target.write_bytes(wav_header(RATE)+b'partial')
  self.a._rip=Mock(side_effect=ReadFailure('retry'))
  self.assertFalse(self.a._produce_once());self.assertFalse(target.exists());self.assertTrue(self.a.uploads.empty())
 def test_server_error_not_counted_as_optical_failure(self):
  self.cloud.request=Mock(side_effect=TimeoutError('server'))
  self.a._rip=self.fake_rip
  self.assertFalse(self.a._register(self.disc,self.a.generation))
  self.assertTrue(self.a._produce_once());self.assertFalse(self.a.failures)
  self.assertIn('server',self.a.snapshot()['error'])
 def test_drive_busy_does_not_spend_track_retries(self):
  self.a._rip=Mock(side_effect=DriveBusy('drive busy'))
  self.assertFalse(self.a._produce_once());self.assertFalse(self.a.failures);self.assertFalse(self.a.snapshot()['drive_blocked'])
 def test_manual_retry_resets_only_read_failures_and_retains_manual_skip(self):
  self.a.failures['TESTDISC1:1']=3;self.a.states[1]={'storage':'blocked'};self.a.states[2]={'storage':'skipped'}
  self.a.retry_failed();self.assertEqual(self.a.states[1]['storage'],'pending');self.assertEqual(self.a.states[2]['storage'],'skipped')
 def test_real_stalled_child_is_reaped_and_lock_released(self):
  binary=self.root/'vendor/ripping/usr/bin/cdparanoia';binary.parent.mkdir(parents=True)
  binary.write_text('#!'+sys.executable+'\nimport sys,time\nfrom pathlib import Path\nPath(sys.argv[-1]).write_bytes('+repr(wav_header(RATE))+')\ntime.sleep(30)\n');binary.chmod(0o755)
  with patch('archive.ProgressWatchdog',side_effect=lambda seconds,speed:ProgressWatchdog(seconds,speed,stall=.05)):
   started=time.monotonic()
   with self.assertRaises(ReadFailure):self.a._rip(self.disc,1,self.a.generation,self.a.stage/'TESTDISC1-1.wav')
  self.assertLess(time.monotonic()-started,4);self.assertIsNone(self.a.process);self.assertFalse(self.a.optical.busy());self.assertFalse(list(self.a.stage.glob('*.partial.wav')))

if __name__=='__main__':unittest.main()

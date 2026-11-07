"""Concurrency tests use events and isolated files, without reading a real CD."""
import copy
import hashlib
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from archive import Archive


class Cloud:
    def __init__(self,disc):
        self.disc=disc;self.stored=set();self.calls=[]
        self.started=threading.Event();self.release=threading.Event();self.finished=threading.Event()
        self.active=False;self.lose_response=False

    def request(self,*args):
        d=copy.deepcopy(self.disc)
        for t in d['tracks']:t.update(ready=t['number'] in self.stored,uploaded=t['number'] in self.stored)
        return d

    def upload(self,identity,number,path,digest=None,progress=None):
        self.calls.append(number);self.active=True
        assert digest==hashlib.sha256(path.read_bytes()).hexdigest()
        if progress:progress(50)
        self.started.set()
        if not self.release.wait(3):raise RuntimeError('Test upload was not released')
        self.stored.add(number);self.active=False;self.finished.set()
        if self.lose_response:
            self.lose_response=False;raise OSError('response lost after successful upload')
        if progress:progress(100)
        return self.request()


class PipelineTests(unittest.TestCase):
    def test_saved_skip_survives_restart_and_reader_continues_with_next_track(self):
        (self.a.root/'data/archive-skipped.json').write_text(json.dumps({'TESTDISC1':[1]}))
        a=Archive(self.a.root);a.cloud=self.cloud
        read=[]
        def rip(disc,number,generation,target):
            read.append(number);target.write_bytes(b'complete');return True
        a._rip=rip;a.attach(self.disc)
        self.assertEqual(a.snapshot()['states'][1]['storage'],'skipped')
        self.assertTrue(a._produce_once())
        self.assertEqual(read,[2])
        self.assertEqual(a.snapshot()['skipped'],1)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);(root/'data').mkdir()
        (root/'data/archive.json').write_text(json.dumps({'url':'https://example.invalid','token':'test'}))
        self.a=Archive(root)
        self.disc=dict(id='TESTDISC1',tracks=[dict(number=n,sectors=75) for n in range(1,5)])
        self.cloud=Cloud(self.disc);self.a.cloud=self.cloud
        self.read=[];self.overlap=[]
        def rip(disc,number,generation,target):
            self.read.append(number);self.overlap.append(self.cloud.active)
            target.write_bytes(b'completed WAV '+bytes([number]));return True
        self.a._rip=rip;self.a.attach(self.disc)

    def test_rips_next_during_upload_and_caps_buffer_at_two(self):
        self.assertTrue(self.a._produce_once())
        job=self.a.uploads.get_nowait()
        worker=threading.Thread(target=self.a._upload_one,args=(job,))
        worker.start()
        try:
            self.assertTrue(self.cloud.started.wait(1))
            self.assertEqual(self.a.snapshot()['states'][1]['progress'],50)
            self.assertFalse(self.a.ready(1))
            self.assertTrue(self.a._produce_once())
            self.assertTrue(self.overlap[1])
            self.assertFalse(self.a._produce_once())
            self.assertEqual(self.read,[1,2])
            self.assertEqual(len(list(self.a.stage.glob('*.wav'))),2)
        finally:
            self.cloud.release.set();worker.join(2)
        self.assertFalse(worker.is_alive())
        self.a._upload_one(self.a.uploads.get_nowait())
        self.assertTrue(self.a.ready(1));self.assertTrue(self.a.ready(2))
        self.assertEqual(list(self.a.stage.glob('*.wav')),[])
        metrics=json.loads(self.a.metrics_path.read_text())
        self.assertEqual(len(metrics),4)
        self.assertCountEqual([m['phase'] for m in metrics],['rip','rip','upload','upload'])

    def test_queue_priority_applies_when_next_slot_opens(self):
        self.a._produce_once();self.a._produce_once()
        self.a.prioritize([4,3])
        self.cloud.release.set();self.a._upload_one(self.a.uploads.get_nowait())
        self.assertTrue(self.a._produce_once());self.assertEqual(self.read,[1,2,4])

    def test_lost_upload_response_does_not_upload_twice(self):
        self.a._produce_once();self.cloud.release.set();self.cloud.lose_response=True
        self.a._upload_one(self.a.uploads.get_nowait())
        self.a._upload_one(self.a.uploads.get_nowait())
        self.assertEqual(self.cloud.calls,[1]);self.assertTrue(self.a.ready(1))
        self.assertFalse(list(self.a.stage.glob('*.wav')))

    def test_eject_cancels_queued_job_but_retains_completed_wav(self):
        self.a._produce_once();job=self.a.uploads.get_nowait()
        self.a.cancel();self.a._upload_one(job)
        self.assertEqual(self.cloud.calls,[])
        self.assertTrue(job['path'].exists())
        self.assertFalse(self.a.inflight)
        self.assertTrue(self.a.slots.acquire(blocking=False))
        self.assertTrue(self.a.slots.acquire(blocking=False))
        self.assertFalse(self.a.slots.acquire(blocking=False))

    def test_known_tracks_are_skipped_and_leftover_wav_is_cleaned(self):
        self.cloud.stored.add(1)
        old=self.a.stage/'TESTDISC1-1.wav';old.write_bytes(b'old confirmed upload')
        self.a._register(self.disc,self.a.generation)
        self.assertTrue(self.a._produce_once())
        self.assertEqual(self.read,[2]);self.assertFalse(old.exists())

    def test_read_error_releases_slot_and_is_not_queued(self):
        def fail(*args):raise RuntimeError('read failure')
        self.a._rip=fail
        self.assertFalse(self.a._produce_once());self.assertTrue(self.a.uploads.empty())
        self.assertFalse(self.a.inflight)
        self.assertEqual(self.a.snapshot()['states'][1]['storage'],'error')
        self.assertTrue(self.a.slots.acquire(blocking=False))
        self.assertTrue(self.a.slots.acquire(blocking=False))


if __name__=='__main__':unittest.main(verbosity=2)

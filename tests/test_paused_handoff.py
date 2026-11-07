"""Maintenance handoff contracts with a simulated MPD; no sockets or hardware."""
import unittest
from tools.paused_handoff import handoff

BASE='http://127.0.0.1:8080/audio/TESTDISC1/1'
class Fake:
    def __init__(self):
        self.entries=[{'Id':'1','file':BASE+'?local='+'a'*32},{'Id':'2','file':BASE[:-1]+'2'}]
        self.id='1';self.elapsed='11.898';self.state='pause';self.consume='1';self.commands=[];self.failure=None
    def __call__(self,command):
        self.commands.append(command);parts=command.split();name=parts[0]
        if self.failure==name:self.failure=None;raise RuntimeError('simulated failure')
        if name=='status':return [f'state: {self.state}',f'songid: {self.id}',f'song: {next(i for i,e in enumerate(self.entries) if e["Id"]==self.id)}',f'elapsed: {self.elapsed}',f'consume: {self.consume}']
        if name=='currentsong':return ['file: '+next(e['file'] for e in self.entries if e['Id']==self.id)]
        if name=='playlistinfo':return [row for e in self.entries for row in ('file: '+e['file'],'Id: '+e['Id'])]
        if name=='consume':self.consume=parts[1]
        elif name=='addid':
            identity=str(max(int(e['Id']) for e in self.entries)+1)
            self.entries.insert(int(parts[2]),{'Id':identity,'file':parts[1].strip('"')});return ['Id: '+identity]
        elif name=='seekid':self.id=parts[1];self.elapsed=parts[2]
        elif name=='deleteid':self.entries=[e for e in self.entries if e['Id']!=parts[1]]
        else:raise AssertionError('Unexpected command')
        return []

class HandoffTests(unittest.TestCase):
    def test_same_pause_and_position_without_play_stop_or_clear(self):
        fake=Fake();checkpoints=[];heads=[]
        self.assertTrue(handoff(fake,BASE,heads.append,checkpoints.append)['ok'])
        self.assertEqual((fake.state,fake.elapsed,fake.consume),('pause','11.898','1'))
        self.assertEqual([e['file'] for e in fake.entries],[BASE,BASE[:-1]+'2'])
        self.assertEqual(heads,[BASE]);self.assertEqual(len(checkpoints),1)
        self.assertFalse(any(c.split()[0] in ('play','playid','pause','stop','clear') for c in fake.commands))
    def test_active_audio_and_wrong_source_are_refused_before_mutation(self):
        for source in ('playing','server'):
            fake=Fake()
            if source=='playing':fake.state='play'
            else:fake.entries[0]['file']=BASE
            with self.assertRaises(RuntimeError):handoff(fake,BASE,lambda _:None,lambda _:None)
            self.assertFalse(any(c.startswith(('consume','addid','seekid','deleteid')) for c in fake.commands))
    def test_failed_seek_restores_original_pause_and_playlist(self):
        fake=Fake();fake.failure='seekid';before=[dict(e) for e in fake.entries]
        with self.assertRaisesRegex(RuntimeError,'original restored'):handoff(fake,BASE,lambda _:None,lambda _:None)
        self.assertEqual(fake.entries,before);self.assertEqual(fake.id,'1');self.assertEqual(fake.consume,'1')
        self.assertEqual(fake.state,'pause')
    def test_failed_checkpoint_does_not_touch_mpd(self):
        fake=Fake()
        def fail(_):raise OSError('disk full')
        with self.assertRaises(OSError):handoff(fake,BASE,lambda _:None,fail)
        self.assertFalse(any(c.startswith(('consume','addid','seekid','deleteid')) for c in fake.commands))

    def test_failure_after_deleting_original_restores_its_uri_and_successor(self):
        fake=Fake();queries=0
        def execute(command):
            nonlocal queries
            if command=='playlistinfo':
                queries+=1
                if queries==2:raise OSError('response lost')
            return fake(command)
        with self.assertRaisesRegex(RuntimeError,'original restored'):handoff(execute,BASE,lambda _:None,lambda _:None)
        self.assertEqual([e['file'] for e in fake.entries],[BASE+'?local='+'a'*32,BASE[:-1]+'2'])
        self.assertEqual(fake.state,'pause');self.assertEqual(fake.elapsed,'11.898')

    def test_lost_add_ack_removes_only_the_known_replacement(self):
        fake=Fake();failed=False
        def execute(command):
            nonlocal failed
            rows=fake(command)
            if command.startswith('addid') and not failed:failed=True;raise OSError('ack lost')
            return rows
        with self.assertRaisesRegex(RuntimeError,'original restored'):handoff(execute,BASE,lambda _:None,lambda _:None)
        self.assertEqual([e['Id'] for e in fake.entries],['1','2']);self.assertEqual(fake.state,'pause')

import tempfile
import unittest
from pathlib import Path
from queueing import CDQueue


class FakeMPD:
    def __init__(self):
        self.entries = [1, 2, 3, 4]
        self.pos = 0
        self.state = 'pause'
        self.commands = []
        self.error = None

    def __call__(self, *commands):
        result = []
        for command in commands:
            self.commands.append(command)
            args = command.split()
            cmd = args[0]
            rows = []
            if cmd == 'status':
                rows = ['state: ' + self.state]
                if self.pos is not None:
                    rows.append('song: ' + str(self.pos))
                if self.error:
                    rows.append('error: ' + self.error)
            elif cmd == 'playlistinfo':
                rows = [f'file: cdda:///{n}' for n in self.entries]
            elif cmd == 'move':
                self.entries.insert(int(args[2]), self.entries.pop(int(args[1])))
            elif cmd == 'delete':
                self.entries.pop(int(args[1]))
            elif cmd == 'clear':
                self.entries = []; self.pos = None; self.state = 'stop'
            elif cmd == 'add':
                self.entries.append(int(args[1].strip('"').rsplit('/', 1)[1]))
            elif cmd == 'play':
                self.state = 'play'; self.pos = int(args[1]) if len(args) > 1 else (self.pos or 0)
            elif cmd == 'pause':
                self.state = 'pause'
            elif cmd == 'stop':
                self.state = 'stop'
            elif cmd == 'next':
                self.pos += 1
            result.append(rows)
        return result


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'queue.json'
        self.mpd = FakeMPD()
        self.q = CDQueue(self.mpd, self.path)
        self.disc = dict(id='A', tracks=[dict(number=n) for n in range(1,5)])
        self.q.attach(self.disc)

    def test_shuffle_preserves_current_and_contains_remaining_once(self):
        self.q.toggle(self.disc, True)
        self.assertEqual(self.mpd.entries[0], 1)
        self.assertCountEqual(self.mpd.entries[1:], [2,3,4])
        self.assertEqual(self.mpd.state, 'pause')
        self.assertFalse(any(c.split()[0] in ('play', 'clear', 'stop') for c in self.mpd.commands))

    def test_reorder_skip_and_reject_stale_order(self):
        self.q.action(self.disc, 'queue-order', {'tracks':[4,2,3]})
        self.assertEqual(self.mpd.entries,[1,4,2,3])
        self.q.action(self.disc, 'queue-skip', {'track':2})
        self.assertEqual(self.mpd.entries,[1,4,3])
        self.assertIn(2,self.q.data['handled'])
        with self.assertRaises(ValueError):
            self.q.action(self.disc,'queue-order',{'tracks':[4,2,3]})
        with self.assertRaises(ValueError):
            self.q.action(self.disc,'queue-skip',{'track':1})

    def test_natural_end_restores_skips_and_avoids_immediate_repeat(self):
        self.q.toggle(self.disc, True)
        self.q.action(self.disc,'queue-skip',{'track':2})
        self.mpd.pos = len(self.mpd.entries)-1; self.mpd.state = 'play'
        last = self.mpd.entries[-1]
        self.q.observe(self.disc)
        self.mpd.state = 'stop'; self.mpd.pos = None
        self.q.observe(self.disc)
        self.assertCountEqual(self.mpd.entries,[1,2,3,4])
        self.assertNotEqual(self.mpd.entries[0],last)
        self.assertEqual(self.q.data['round'],2)
        self.assertEqual(self.mpd.state,'play')
        self.assertEqual(self.q.data['handled'],[])

    def test_stop_pause_error_and_restart_do_not_restart_round(self):
        self.q.toggle(self.disc,True)
        self.mpd.pos=3; self.mpd.state='play'; self.q.observe(self.disc)
        self.q.action(self.disc,'pause',{})
        self.assertEqual(self.q.data['round'],1)
        self.mpd.state='play'; self.q.observe(self.disc)
        self.q.action(self.disc,'stop',{})
        self.assertEqual(self.q.data['round'],1)
        self.mpd.state='play'; self.q.observe(self.disc)
        self.mpd.state='stop'; self.mpd.error='read failed'; self.q.observe(self.disc)
        self.assertEqual(self.q.data['round'],1)
        restored=CDQueue(self.mpd,self.path); restored.observe(self.disc)
        self.assertEqual(restored.data['round'],1)

    def test_next_on_last_rolls_round_only_in_shuffle(self):
        self.q.toggle(self.disc,True); self.mpd.pos=3
        self.q.action(self.disc,'next',{})
        self.assertEqual(self.q.data['round'],2)
        self.assertEqual(self.mpd.state,'play')

    def test_single_track_and_new_disc(self):
        self.disc['tracks']=[{'number':1}]; self.mpd.entries=[1]
        self.q.toggle(self.disc,True); self.mpd.state='play'; self.q.observe(self.disc)
        self.mpd.state='stop'; self.mpd.pos=None; self.q.observe(self.disc)
        self.assertEqual(self.mpd.entries,[1]); self.assertEqual(self.q.data['round'],2)
        self.q.attach(dict(id='B'),reset=True)
        self.assertEqual(self.q.data['round'],1); self.assertTrue(self.q.data['shuffle'])

    def test_disable_shuffle_sorts_future_without_touching_current(self):
        self.mpd.entries=[3,4,1,2]; self.mpd.pos=0
        self.q.toggle(self.disc,False)
        self.assertEqual(self.mpd.entries,[3,1,2,4])

    def test_skip_all_future_then_cycle_restores_every_track(self):
        self.q.toggle(self.disc, True)
        for number in [2,3,4]:
            self.q.action(self.disc, 'queue-skip', {'track':number})
        self.assertEqual(self.mpd.entries,[1])
        self.q.action(self.disc,'next',{})
        self.assertCountEqual(self.mpd.entries,[1,2,3,4])
        self.assertEqual(self.q.data['handled'],[])

    def test_saved_queue_survives_engine_restart_and_ensure(self):
        self.q.toggle(self.disc,True)
        self.q.action(self.disc,'queue-order',{'tracks':[4,3,2]})
        self.q.action(self.disc,'queue-skip',{'track':3})
        restored=CDQueue(self.mpd,self.path)
        restored.ensure(self.disc)
        _, snapshot=restored.observe(self.disc)
        self.assertTrue(snapshot['shuffle'])
        self.assertEqual(snapshot['upcoming'],[4,2])
        self.assertEqual(snapshot['handled'],[3])

    def test_track_mapping_uses_actual_disc_number(self):
        self.mpd.entries=[4,2,1,3]; self.mpd.pos=1
        _, snapshot=self.q.observe(self.disc)
        self.assertEqual(snapshot['current'],2)
        self.assertEqual(snapshot['upcoming'],[1,3])
        self.assertEqual(snapshot['handled'],[4])

if __name__ == '__main__':
    unittest.main()

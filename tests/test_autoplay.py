import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))
import tests as _isolated_test_state
import app as player


class EndScan(BaseException):
    pass


class AutoplayTests(unittest.TestCase):
    def test_scan_detects_insertions_without_restarting_existing_disc(self):
        a = SimpleNamespace(id='A', toc='toc', first_track=1, track_lengths=(750, 1500))
        b = SimpleNamespace(id='B', toc='toc', first_track=1, track_lengths=(2250,))
        reads = [a, player.libdiscid.DiscError('no disc'), a, b, b]
        count = 0

        def sleep(_):
            nonlocal count
            count += 1
            if count == 7:
                raise EndScan()

        with patch.object(player, 'source', 'cd'), patch.object(player.dvd, 'busy', return_value=False), patch.object(player.archive, 'reading', return_value=False), patch.object(player.archive, 'cancel'), patch.object(player, 'optical_device', return_value='/dev/fake'), patch.object(player, 'prepare_disc', side_effect=lambda s:s), patch.object(player.libdiscid, 'read', side_effect=reads) as read, \
             patch.object(player, 'media_changed', side_effect=[True, False, True, True, False, True, True]), \
             patch.object(player, 'accept_disc') as accept, \
             patch.object(player, 'mpd'), \
             patch.object(player.threading, 'Thread'), \
             patch.object(player.time, 'sleep', side_effect=sleep):
            with self.assertRaises(EndScan):
                player.scan_loop()
        self.assertEqual([(c.args[0]['id'], c.kwargs['autoplay']) for c in accept.call_args_list],
                         [('A', False), ('A', True), ('B', True)])
        self.assertEqual(read.call_count, 5)

    def test_insert_switches_from_spotify_and_starts_first_track(self):
        snapshot = {'present': True, 'id': 'A', 'tracks': [{'number': 1}, {'number': 2}]}
        with patch.object(player, 'choose_source') as choose, \
             patch.object(player, 'load_queue') as load, \
             patch.object(player, 'queue') as queue, \
             patch.object(player, 'mpd') as mpd:
            queue.data = {}
            player.accept_disc(snapshot, autoplay=True)
        choose.assert_called_once_with('cd')
        load.assert_called_once_with()
        self.assertEqual([c.args for c in mpd.call_args_list], [('stop', 'clear')])
        queue.action.assert_called_once_with(snapshot, 'play', {})

    def test_startup_leaves_audio_unchanged(self):
        with patch.object(player, 'choose_source') as choose, patch.object(player, 'queue'), patch.object(player, 'mpd') as mpd:
            player.accept_disc({'present': True, 'id': 'A'}, autoplay=False)
        choose.assert_not_called()
        mpd.assert_not_called()


if __name__ == '__main__': unittest.main()

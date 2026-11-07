import array
import json
import subprocess
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from vinyl import Vinyl, track_metadata


def capture(args, **kwargs):
    with wave.open(args[-1], 'wb') as wav:
        wav.setparams((2, 2, 44100, 0, 'NONE', 'not compressed'))
        wav.writeframes(array.array('h', [2000, -2000] * 44100).tobytes())
    return subprocess.CompletedProcess(args, 0)


class VinylTests(unittest.TestCase):
    def engine(self, root):
        v = Vinyl(root)
        v.set_active(True)
        return v

    def test_silence_never_calls_shazam_and_deletes_recording(self):
        with tempfile.TemporaryDirectory() as root:
            v = self.engine(root)
            def silent(args, **kwargs):
                with wave.open(args[-1], 'wb') as wav:
                    wav.setparams((2, 2, 44100, 0, 'NONE', 'not compressed'))
                    wav.writeframes(b'\0' * 176400)
                return subprocess.CompletedProcess(args, 0)
            with patch('vinyl.subprocess.run', side_effect=silent) as run:
                v.run(v.generation)
            self.assertEqual(v.state['state'], 'silent')
            self.assertEqual(run.call_count, 1)
            self.assertFalse(Path(run.call_args.args[0][-1]).exists())

    def test_matching_then_no_match_clears_current_and_keeps_history(self):
        with tempfile.TemporaryDirectory() as root:
            v = self.engine(root)
            match = {'matches': [{'timeskew': 0.002, 'frequencyskew': 0.001}], 'track': {'title': 'Song', 'subtitle': 'Artist',
                     'images': {'coverart': 'https://example.com/cover.jpg'}}}
            for result in (match, {}):
                def run(args, **kwargs):
                    if 'pw-record' in args:
                        return capture(args, **kwargs)
                    return subprocess.CompletedProcess(args, 0, json.dumps(result), '')
                with patch('vinyl.subprocess.run', side_effect=run):
                    v.run(v.generation)
            self.assertEqual(v.state['state'], 'no_match')
            self.assertIsNone(v.state['track'])
            self.assertEqual(len(v.state['history']), 1)

    def test_source_switch_discards_pending_result(self):
        with tempfile.TemporaryDirectory() as root:
            v = self.engine(root)
            generation = v.generation
            def run(args, **kwargs):
                if 'pw-record' in args:
                    return capture(args, **kwargs)
                v.set_active(False)
                return subprocess.CompletedProcess(args, 0, json.dumps({
                    'matches': [{}], 'track': {'title': 'Old song'}}), '')
            with patch('vinyl.subprocess.run', side_effect=run):
                v.run(generation)
            self.assertIsNone(v.state['track'])
            self.assertEqual(v.state['state'], 'idle')

    def test_timeout_cleans_up_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as root:
            v = self.engine(root)
            v.working = True
            with patch('vinyl.subprocess.run', side_effect=subprocess.TimeoutExpired('arecord', 18)):
                v.run(v.generation)
            self.assertEqual(v.state['state'], 'error')
            self.assertFalse(v.working)

    def test_duplicate_requests_do_not_spawn_second_capture(self):
        v = self.engine('.')
        with patch.object(v, 'connected', return_value=True), \
             patch.object(v, 'available', return_value=True), patch('vinyl.threading.Thread') as thread:
            self.assertTrue(v.start())
            self.assertFalse(v.start())
            self.assertEqual(thread.call_count, 1)
        v.set_automatic(True)
        v.state['track'] = {'title': 'Previous record'}
        v.set_active(False)
        self.assertFalse(v.state['automatic'])
        self.assertIsNone(v.state['track'])
        with self.assertRaises(ValueError):
            v.set_automatic(True)

    def test_requires_real_match_and_rejects_unsafe_metadata_links(self):
        self.assertIsNone(track_metadata({'track': {'title': 'Song'}}))
        result = track_metadata({'matches': [{'timeskew': 0, 'frequencyskew': 0}], 'track': {
            'title': '<script>', 'url': 'javascript:alert(1)',
            'images': {'coverart': 'http://example.com/image'}}})
        self.assertEqual(result['url'], '')
        self.assertEqual(result['cover'], '')

    def test_rejects_unreliable_matches_and_allows_small_vinyl_speed_variation(self):
        for skew in (0.051, 0.2, float('nan'), float('inf')):
            self.assertIsNone(track_metadata({'matches': [{'timeskew': skew,
                'frequencyskew': 0}], 'track': {'title': 'False match'}}))
        self.assertIsNone(track_metadata({'matches': [{}], 'track': {'title': 'Missing quality'}}))
        self.assertIsNotNone(track_metadata({'matches': [{'timeskew': -0.003,
            'frequencyskew': -0.002}], 'track': {'title': 'Vinyl'}}))

    def test_taylor_swift_vinyl_match_with_two_percent_skew_is_accepted(self):
        # Raw Shazam reply for the user's recording; the phone confirmed it.
        result = track_metadata({'matches': [{'id': '678501694',
            'offset': 126.144335937, 'timeskew': 0.021433711,
            'frequencyskew': 0.020998716}], 'track': {
            'title': 'All You Had To Do Was Stay', 'subtitle': 'Taylor Swift',
            'key': '157666214'}})
        self.assertIsNotNone(result)
        self.assertEqual(result['artist'], 'Taylor Swift')
        self.assertEqual(result['title'], 'All You Had To Do Was Stay')

    def test_quiet_input_noise_does_not_get_sent_to_shazam(self):
        with tempfile.TemporaryDirectory() as root:
            v = self.engine(root)
            def quiet(args, **kwargs):
                with wave.open(args[-1], 'wb') as wav:
                    wav.setparams((2, 2, 44100, 0, 'NONE', 'not compressed'))
                    wav.writeframes(array.array('h', [120, -120] * 44100).tobytes())
                return subprocess.CompletedProcess(args, 0)
            with patch('vinyl.subprocess.run', side_effect=quiet) as run:
                v.run(v.generation)
            self.assertEqual(v.state['state'], 'silent')
            self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()

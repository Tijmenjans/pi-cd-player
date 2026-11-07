import tempfile
import unittest
from unittest.mock import patch

from vinyl_transitions import TransitionDetector
from vinyl import Vinyl


def feed(detector, start, stop, level):
    for quarter in range(round(start * 4), round(stop * 4)):
        detector.feed(level, quarter / 4)


class TransitionTests(unittest.TestCase):
    def test_matches_once_and_never_periodically_rechecks_continuous_music(self):
        d = TransitionDetector()
        feed(d, 0, 2, -28)
        self.assertTrue(d.due(2, 60))
        d.attempted(2)
        d.matched()
        feed(d, 2, 900, -28)
        self.assertFalse(d.due(900, 60))
        self.assertIn('Wacht op een stille overgang', d.message(900, 60))

    def test_short_volume_dip_is_not_a_new_song(self):
        d = TransitionDetector()
        d.matched()
        feed(d, 0, 10, -28)
        feed(d, 10, 10.75, -60)
        feed(d, 10.75, 30, -28)
        self.assertFalse(d.pending)
        self.assertEqual(d.transition, 0)

    def test_quiet_transition_triggers_only_after_music_returns_and_cooldown(self):
        d = TransitionDetector()
        d.attempted(10)
        d.matched()
        feed(d, 10, 30, -28)
        feed(d, 30, 33, -58)
        self.assertTrue(d.armed)
        self.assertFalse(d.due(33, 60))
        feed(d, 33, 36, -26)
        self.assertTrue(d.pending)
        self.assertEqual(d.transition, 1)
        self.assertFalse(d.due(36, 60))
        feed(d, 36, 70, -26)
        self.assertTrue(d.due(70, 60))
        self.assertFalse(d.due(70, 120))

    def test_missing_samples_do_not_trigger_transition(self):
        d = TransitionDetector()
        d.matched()
        feed(d, 0, 5, -28)
        feed(d, 5, 20, None)
        feed(d, 20, 25, -28)
        self.assertFalse(d.pending)
        self.assertFalse(d.armed)

    def test_silence_never_triggers_network_request(self):
        d = TransitionDetector()
        feed(d, 0, 100, -65)
        self.assertFalse(d.due(100, 60))

    def test_failed_recognition_retries_at_interval_and_stops_after_three(self):
        d = TransitionDetector()
        feed(d, 0, 2, -28)
        for start in (2, 62, 122):
            self.assertTrue(d.due(start, 60))
            d.attempted(start)
            self.assertFalse(d.due(start + 59, 60))
        self.assertFalse(d.due(182, 60))
        self.assertIn('3 pogingen', d.message(182, 60))
        feed(d, 182, 185, -60)
        feed(d, 185, 187, -28)
        self.assertTrue(d.due(187, 60))
        self.assertEqual(d.attempts, 0)

    def test_interval_is_validated_persisted_and_reloaded(self):
        with tempfile.TemporaryDirectory() as directory:
            v = Vinyl(directory)
            self.assertEqual(v.interval, 60)
            for bad in (True, '60', 19, 601, 60.5, None):
                with self.assertRaises(ValueError):
                    v.set_interval(bad)
            v.set_interval(120)
            self.assertEqual(Vinyl(directory).interval, 120)

    def test_auto_enable_keeps_already_known_track_and_user_setting(self):
        with tempfile.TemporaryDirectory() as directory:
            v = Vinyl(directory)
            v.set_active(True)
            v.state['track'] = {'title': 'Known song'}
            v.set_automatic(True)
            self.assertFalse(v.detector.pending)
            v.set_automatic(False)
            with patch.object(v, 'start') as start:
                for now in range(100):
                    v.tick(-28, now)
                start.assert_not_called()

    def test_busy_recognition_does_not_spawn_another(self):
        with tempfile.TemporaryDirectory() as directory:
            v = Vinyl(directory)
            v.set_active(True)
            v.set_automatic(True)
            v.working = True
            with patch.object(v, 'start') as start:
                for now in range(100):
                    v.tick(-28, now)
                start.assert_not_called()


if __name__ == '__main__':
    unittest.main()

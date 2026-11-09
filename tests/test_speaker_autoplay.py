import threading
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import tests
import app as player
import plexamp
from speaker_autoplay import ConnectionTrigger


class SpeakerAutoplayTests(unittest.TestCase):
    def test_manual_pause_or_source_choice_does_not_retrigger(self):
        trigger = ConnectionTrigger()
        self.assertTrue(trigger.update(True))
        for _ in range(30):
            self.assertFalse(trigger.update(True))
        self.assertFalse(trigger.update(False))
        self.assertFalse(trigger.update(True))
        self.assertFalse(trigger.update(None))
        self.assertFalse(trigger.update(True))
        trigger.update(False); trigger.update(False)
        self.assertTrue(trigger.update(True))

    def test_unknown_status_does_not_rearm(self):
        trigger = ConnectionTrigger(); trigger.update(True)
        for _ in range(10):trigger.update(None)
        self.assertFalse(trigger.update(True))

    def test_unavailable_playlist_does_not_change_source(self):
        from dataclasses import replace
        settings=replace(player.SETTINGS,speaker_autoplay_server='server',speaker_autoplay_playlist='123')
        with patch.object(player,'SETTINGS',settings), patch.object(player,'source','cd'), patch.object(plexamp,'prepare_playlist',side_effect=RuntimeError('offline')), patch.object(player,'choose_source') as choose:
            with self.assertRaises(RuntimeError):player.start_speaker_playlist()
            choose.assert_not_called()

    def test_failed_start_restores_previous_source(self):
        from dataclasses import replace
        settings=replace(player.SETTINGS,speaker_autoplay_server='server',speaker_autoplay_playlist='123')
        def choose(name):player.source=name
        with patch.object(player,'SETTINGS',settings), patch.object(player,'source','cd'), patch.object(plexamp,'prepare_playlist',return_value='uri'), patch.object(plexamp,'start_playlist',side_effect=RuntimeError('offline')), patch.object(player,'choose_source',side_effect=choose) as switch:
            with self.assertRaises(RuntimeError):player.start_speaker_playlist()
            self.assertEqual(player.source,'cd')
            self.assertEqual(switch.call_count,2)

    def test_native_queue_creation_and_confirmed_playback(self):
        import io
        with patch.object(plexamp,'request',side_effect=[ET.Element('MediaContainer'),ET.fromstring('<MediaContainer><Timeline type="music" state="playing" /></MediaContainer>')]), patch.object(plexamp.urllib.request,'urlopen',return_value=io.BytesIO(b'OK')) as send:
            plexamp.start_playlist('server://example/playlists/123/items',threading.Event())
            req=send.call_args.args[0]
            self.assertEqual(req.get_method(),'GET')
            self.assertIn('/player/playback/createPlayQueue?',req.full_url)
            self.assertIn('source=example',req.full_url)
            self.assertNotIn('token',req.full_url.lower())

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
        from urllib.parse import urlsplit, parse_qs
        import contextlib
        timeline = lambda state, shuffle: ET.fromstring('<MediaContainer><Timeline type="music" state="'+state+'" shuffle="'+shuffle+'" /></MediaContainer>')
        @contextlib.contextmanager
        def response(*args, **kwargs):
            yield io.BytesIO(b'OK')
        with patch.object(plexamp,'request',side_effect=[ET.Element('MediaContainer'),timeline('paused','0'),timeline('playing','1')]), patch.object(plexamp.urllib.request,'urlopen',side_effect=response) as send:
            plexamp.start_playlist('server://example/playlists/123/items',threading.Event())
            urls=[urlsplit(call.args[0].full_url) for call in send.call_args_list]
            self.assertEqual([url.path for url in urls],['/player/playback/createPlayQueue','/player/playback/setParameters','/player/playback/skipNext','/player/playback/play'])
            self.assertEqual(parse_qs(urls[0].query)['paused'],['1'])
            self.assertEqual(parse_qs(urls[1].query)['shuffle'],['1'])
            self.assertNotIn('token', urls[0].query.lower())

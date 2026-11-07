"""Isolated streaming checks; these never operate the real audio services."""
import tempfile
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import app as player
import plexamp


class StreamingTests(unittest.TestCase):
    def test_metadata_publishes_before_artwork_and_compilation_uses_track_artist(self):
        key = ('server', '42')
        xml = ET.fromstring('<MediaContainer><Track title="Song" originalTitle="Singer" '
                            'grandparentTitle="Various Artists" parentTitle="Album" '
                            'thumb="/library/metadata/10/thumb/1"/></MediaContainer>')
        def fetch(url, token, image=False):
            self.assertEqual(token, 'private-test-token')
            if image:
                self.assertEqual(plexamp.snapshot()['title'], 'Song')
                return b'cover-data', 'image/jpeg'
            return xml
        with tempfile.TemporaryDirectory() as tmp:
            prefs = Path(tmp) / 'preferences.json'
            prefs.write_text(json.dumps({'plex': {'token': 'private-test-token'}}))
            with patch.object(plexamp, 'PREFERENCES', prefs), \
                 patch.object(plexamp, '_metadata', plexamp.OrderedDict()), \
                 patch.object(plexamp, '_state', {'machineIdentifier': 'server', 'ratingKey': '42'}), \
                 patch.object(plexamp, 'server_urls', return_value=['https://server.example']), \
                 patch.object(plexamp, 'remote', side_effect=fetch):
                plexamp.load_metadata(key)
                result = plexamp.snapshot()
                self.assertEqual(result['artist'], 'Singer')
                self.assertEqual(result['album'], 'Album')
                self.assertNotIn('private-test-token', json.dumps(result))
                digest = result['cover'].rsplit('/', 1)[1]
                self.assertEqual(plexamp.cover(digest), (b'cover-data', 'image/jpeg'))
                with patch.dict(plexamp._state, ratingKey='43'):
                    self.assertEqual(plexamp.snapshot()['title'], '')
                    self.assertTrue(plexamp.snapshot()['metadata_loading'])

    def test_server_discovery_uses_matching_server_and_secure_connections_only(self):
        xml = ET.fromstring('<MediaContainer>'
            '<Device clientIdentifier="wrong" provides="server"><Connection uri="https://wrong.example"/></Device>'
            '<Device clientIdentifier="correct" provides="server">'
            '<Connection uri="http://insecure.example"/>'
            '<Connection uri="https://local.example" local="1"/>'
            '<Connection uri="https://public.example" local="0"/>'
            '<Connection uri="https://credentials@example.com"/>'
            '</Device></MediaContainer>')
        with patch.object(plexamp, '_servers', {}), patch.object(plexamp, 'remote', return_value=xml):
            self.assertEqual(plexamp.server_urls('correct', 'token'),
                             ['https://public.example', 'https://local.example'])

    def test_source_selection_stops_other_engines_and_remembers_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(player, 'DATA', Path(tmp)), \
                 patch.object(player, 'source_file', Path(tmp) / 'source'), \
                 patch.object(player, 'streaming_source_file', Path(tmp) / 'streaming-source'), \
                 patch.object(player, 'source', 'spotify'), \
                 patch.object(player, 'streaming_source', 'spotify'), \
                 patch.object(player.plexamp, 'configured', return_value=True), \
                 patch.object(player, 'service') as service:
                player.choose_source('plexamp')
                self.assertEqual(service.call_args_list, [
                    unittest.mock.call('stop', 'mpd'), unittest.mock.call('stop', 'spotify'),
                    unittest.mock.call('stop', 'vinyl'), unittest.mock.call('start', 'plexamp')])
                self.assertEqual(player.source, 'plexamp')
                self.assertEqual((Path(tmp) / 'streaming-source').read_text(), 'plexamp')

    def test_unlinked_receiver_does_not_stop_current_music(self):
        with patch.object(player.plexamp, 'configured', return_value=False), \
             patch.object(player, 'service') as service:
            with self.assertRaisesRegex(RuntimeError, 'gekoppeld'):
                player.choose_source('plexamp')
            service.assert_not_called()

    def test_failed_receiver_start_restores_previous_service(self):
        with patch.object(player, 'source', 'spotify'), \
             patch.object(player.plexamp, 'configured', return_value=True), \
             patch.object(player, 'service', side_effect=[None, None, None, OSError(), None]) as service:
            with self.assertRaises(RuntimeError):
                player.choose_source('plexamp')
            self.assertEqual(service.call_args_list[-1], unittest.mock.call('start', 'spotify'))
            self.assertEqual(player.source, 'spotify')

    def test_companion_actions_convert_seconds_and_reject_invalid_seek(self):
        with patch.object(plexamp, 'request', return_value=ET.Element('Response')) as send:
            plexamp.command('next')
            send.assert_called_with('/player/playback/skipNext')
            plexamp.command('seek', seconds=12.5)
            send.assert_called_with('/player/playback/seekTo', offset=12500)
            for value in (float('nan'), float('inf'), -1):
                with self.assertRaises(ValueError): plexamp.command('seek', seconds=value)

    def test_plex_status_and_actions_are_separate_from_spotify(self):
        status = {'state': 'playing', 'has_track': True, 'connected': True,
                  'seconds': 180, 'elapsed': 12, 'volume': 100}
        with patch.object(player, 'source', 'plexamp'), \
             patch.object(player.plexamp, 'snapshot', return_value=status), \
             patch.object(player.plexamp, 'command') as command, \
             patch.object(player.spotify, 'command') as spotify:
            client = player.app.test_client()
            result = client.get('/api/status').get_json()
            self.assertEqual(result['player']['state'], 'play')
            self.assertEqual(result['plexamp']['elapsed'], 12)
            self.assertNotIn('spotify', result)
            response = client.post('/api/action', json={'action': 'pause'}, headers={'X-CDSpeler': '1'})
            self.assertEqual(response.status_code, 200)
            command.assert_called_once_with('pause', seconds=None)
            spotify.assert_not_called()


if __name__ == '__main__': unittest.main()

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, call

import app as player
from vinyl import Vinyl


class VinylAPITests(unittest.TestCase):
    def test_interval_route_validates_and_saves_setting(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Vinyl(tmp)
            with patch.object(player, 'vinyl', engine), patch.object(player, 'source', 'vinyl'):
                client = player.app.test_client()
                headers = {'X-CDSpeler': '1'}
                self.assertEqual(client.post('/api/action', json={'action':'vinyl-interval', 'seconds':120}).status_code, 403)
                self.assertEqual(client.post('/api/action', json={'action':'vinyl-interval', 'seconds':120}, headers=headers).status_code, 200)
                self.assertEqual(Vinyl(tmp).interval, 120)
                self.assertEqual(client.get('/api/status').get_json()['vinyl']['auto_interval'], 120)
                for value in (True, None, 0, 601, '120'):
                    self.assertEqual(client.post('/api/action', json={'action':'vinyl-interval', 'seconds':value}, headers=headers).status_code, 400)
                self.assertEqual(engine.interval, 120)

    def test_select_vinyl_stops_engines_without_changing_streaming_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Vinyl(tmp)
            with patch.object(player, 'vinyl', engine), \
                 patch.object(engine, 'connected', return_value=True), \
                 patch.object(player, 'source', 'cd'), \
                 patch.object(player, 'streaming_source', 'plexamp'), \
                 patch.object(player, 'source_file', Path(tmp) / 'source'), \
                 patch.object(player, 'service') as service:
                player.choose_source('vinyl')
                self.assertEqual(service.call_args_list, [call('stop', 'mpd'),
                                 call('stop', 'spotify'), call('stop', 'plexamp'), call('start', 'vinyl')])
                self.assertEqual(player.streaming_source, 'plexamp')
                self.assertTrue(engine.active)
                self.assertEqual((Path(tmp) / 'source').read_text(), 'vinyl')

    def test_unplugged_input_does_not_stop_current_player(self):
        with patch.object(player.vinyl, 'connected', return_value=False), \
             patch.object(player, 'service') as service:
            with self.assertRaises(RuntimeError):
                player.choose_source('vinyl')
            service.assert_not_called()

    def test_status_actions_and_post_protection(self):
        with patch.object(player, 'source', 'vinyl'), \
             patch.object(player.vinyl, 'snapshot', return_value={'state': 'idle', 'monitor': {'name':'IKEA VAPPEBY', 'type':'bluetooth', 'playing':True}}), \
             patch.object(player.vinyl, 'start') as start, \
             patch.object(player.vinyl, 'set_automatic') as automatic:
            client = player.app.test_client()
            headers = {'X-CDSpeler': '1'}
            status = client.get('/api/status').get_json()
            self.assertEqual(status['vinyl']['state'], 'idle')
            self.assertNotIn('spotify', status)
            self.assertEqual(client.post('/api/action', json={'action': 'vinyl-recognize'}).status_code, 403)
            self.assertEqual(client.post('/api/action', json={'action': 'vinyl-recognize'}, headers=headers).status_code, 200)
            start.assert_called_once()
            self.assertEqual(client.post('/api/action', json={'action': 'vinyl-auto', 'enabled': True}, headers=headers).status_code, 200)
            automatic.assert_called_once_with(True)
            self.assertEqual(client.post('/api/action', json={'action': 'play'}, headers=headers).status_code, 400)
            self.assertEqual(client.post('/api/action', json={'action': 'vinyl-auto', 'enabled': True}, headers={**headers, 'Origin':'https://evil.invalid'}).status_code, 403)


if __name__ == '__main__':
    unittest.main()

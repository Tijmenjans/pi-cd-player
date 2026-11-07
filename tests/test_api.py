"""Route-level verification with an isolated player; never touches live audio."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tests as _isolated_test_state
import app as player
from archive_queue import ArchiveQueue
from test_archive_api import MPD, Store


class APITests(unittest.TestCase):
    def test_track_artists_preserve_collaborations_and_recording_fallback(self):
        payload = {'releases':[{'id':'release','title':'Compilation','artist-credit':[{'name':'Various Artists'}],
            'media':[{'discs':[{'id':'TEST'}],'tracks':[
                {'title':'A','artist-credit':[{'name':'Singer A','joinphrase':' feat. '},{'artist':{'name':'Singer B'}}]},
                {'title':'B','recording':{'artist-credit':[{'name':'Band'}]}},
                {'title':'C'}]}]}]}
        result=player.release_metadata(payload,{'id':'TEST','tracks':[{}, {}, {}]})
        self.assertEqual(result['releases'][0]['track_artists'],['Singer A feat. Singer B','Band','Onbekende artiest'])

    def test_queue_routes_and_current_track(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = MPD()
            store = Store()
            store.ready = store.playable = lambda n: True
            engine = ArchiveQueue(fake, Path(directory) / 'queue.json', store)
            disc = dict(id='TEST', present=True, tracks=[dict(number=n,title=str(n),seconds=100) for n in range(1,5)])
            with patch.object(player, 'archive', store), patch.object(player, 'queue', engine), patch.object(player,'mpd',fake), \
                    patch.object(player,'disc',disc), patch.object(player,'source','cd'):
                client = player.app.test_client()
                def post(action, **extra):
                    return client.post('/api/action', json=dict(action=action,**extra), headers={'X-CDSpeler':'1'})
                self.assertEqual(post('shuffle',enabled=True).status_code,200)
                self.assertEqual(post('queue-order',tracks=[4,3,2]).status_code,400)
                engine.action(disc,'queue-order',{'tracks':[4,3,2]})
                self.assertEqual(post('queue-skip',track=3).status_code,400)
                engine.action(disc,'queue-skip',{'track':3})
                snapshot=client.get('/api/status').get_json()
                self.assertEqual(snapshot['queue']['upcoming'],[4,2])
                self.assertEqual(snapshot['player']['track'],1)
                self.assertEqual(post('queue-order',tracks=[2,3,4]).status_code,400)
                self.assertEqual(post('shuffle',enabled='false').status_code,400)
                self.assertEqual(client.post('/api/action',json={'action':'play'}).status_code,403)
                self.assertEqual(fake.state,'stop')


if __name__ == '__main__':
    unittest.main()

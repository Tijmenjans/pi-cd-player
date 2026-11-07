"""Real loopback HTTP through Waitress, synthetic media only. No hardware workers."""
import http.client
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import tests  # Standard isolated state/backend bootstrap.
import app
from flask import Flask,Response
from live_audio import GrowingWav,RATE,wav_header
from waitress.server import create_server

class StreamingTests(unittest.TestCase):
    def with_server(self,application,check):
        channels={};errors=[]
        server=create_server(application,host='127.0.0.1',port=0,threads=4,map=channels,asyncore_loop_timeout=.05)
        thread=threading.Thread(target=server.run,daemon=True);thread.start()
        try:check(int(server.effective_port))
        finally:
            server.task_dispatcher.shutdown(timeout=2)
            for channel in list(channels.values()):channel.close()
            thread.join(3)
            self.assertFalse(thread.is_alive())

    def test_response_streams_before_completion_while_health_stays_available(self):
        application=Flask(__name__);release=threading.Event()
        @application.get('/stream')
        def stream():
            def chunks():
                yield b'first'
                release.wait(3)
                yield b'last'
            return Response(chunks(),mimetype='application/octet-stream')
        @application.get('/health')
        def health():return {'ok':True}
        def check(port):
            conn=http.client.HTTPConnection('127.0.0.1',port,timeout=2)
            other=http.client.HTTPConnection('127.0.0.1',port,timeout=2)
            try:
                conn.request('GET','/stream');response=conn.getresponse()
                self.assertEqual(response.read(5),b'first');self.assertFalse(release.is_set())
                other.request('GET','/health');self.assertEqual(other.getresponse().status,200)
                release.set();self.assertEqual(response.read(),b'last')
            finally:release.set();conn.close();other.close()
        self.with_server(application,check)

    def test_real_player_range_and_head_survive_production_wsgi(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'track.wav';path.write_bytes(wav_header(RATE*4)+b'\1\0\1\0'*RATE*4)
            live=GrowingWav(path,RATE*4);live.refresh(complete=True)
            class Store:
                def local_audio(self,identity,number,token):
                    if (identity,number,token)!=('TESTDISC1',1,live.token):raise FileNotFoundError()
                    return live.open()
            def check(port):
                conn=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
                try:
                    uri='/audio/TESTDISC1/1?local='+live.token
                    conn.request('GET',uri,headers={'Range':'bytes=40-53'})
                    response=conn.getresponse();self.assertEqual(response.status,206)
                    self.assertEqual(response.read(),path.read_bytes()[40:54])
                    conn.request('HEAD',uri);response=conn.getresponse()
                    self.assertEqual(response.status,200);self.assertEqual(response.read(),b'')
                finally:conn.close()
            try:
                with patch.object(app,'archive',Store()):self.with_server(app.app,check)
            finally:live.close()

if __name__=='__main__':unittest.main()

"""Pi-only integration test: isolated MPD/null output and synthetic growing WAV."""
import json
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from flask import Flask, Response, request
from werkzeug.serving import make_server
from live_audio import GrowingWav, RATE, wav_header


class MPDStreamTest(unittest.TestCase):
    def test_mpd_plays_before_writer_finishes_and_can_seek_after_unlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'test.wav'
            tone=b'\xe8\x03\x18\xfc'
            path.write_bytes(wav_header(RATE*40)+tone*RATE*4)
            live=GrowingWav(path,RATE*40);live.refresh()
            self.assertTrue(live.playable())
            app=Flask(__name__);ranges=[]
            @app.route('/test.wav',methods=['GET','HEAD'])
            def audio():
                ranges.append(request.headers.get('Range'))
                reader=live.open();start,end=reader.response_range(request.headers.get('Range'))
                headers={'Content-Type':'audio/wav','Content-Length':str(end-start+1),'Accept-Ranges':'bytes'}
                if request.headers.get('Range'):headers['Content-Range']=f'bytes {start}-{end}/{reader.size}'
                if request.method=='HEAD':reader.close();return Response(headers=headers)
                response=Response(reader.chunks(start,end),headers=headers,status=206 if request.headers.get('Range') else 200)
                response.call_on_close(reader.close);return response
            server=make_server('127.0.0.1',0,app,threaded=True)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            config=root/'mpd.conf'
            config.write_text(f'bind_to_address "127.0.0.1"\nport "{port}"\n'
                f'db_file "{root}/mpd.db"\nplaylist_directory "{root}"\n'
                'audio_buffer_size "4096"\nlog_level "verbose"\n'
                'decoder {\n plugin "ffmpeg"\n analyzeduration "100000"\n probesize "32768"\n}\n'
                'audio_output {\n type "null"\n name "silent test"\n}\n')
            log=(root/'mpd.log').open('wb')
            proc=subprocess.Popen(['mpd','--no-daemon','--stderr',str(config)],stdout=log,stderr=log)
            connection=None
            try:
                for _ in range(50):
                    try:connection=socket.create_connection(('127.0.0.1',port),timeout=1);break
                    except OSError:time.sleep(.1)
                self.assertIsNotNone(connection)
                stream=connection.makefile('rwb');self.assertTrue(stream.readline().startswith(b'OK MPD'))
                def command(text):
                    stream.write((text+'\n').encode());stream.flush();rows=[]
                    while True:
                        line=stream.readline().decode().strip()
                        if line=='OK':return dict(r.split(': ',1) for r in rows if ': ' in r)
                        if not line or line.startswith('ACK'):raise RuntimeError(line)
                        rows.append(line)
                command(f'add "http://127.0.0.1:{server.server_port}/test.wav"')
                started=time.monotonic();command('play')
                for _ in range(80):
                    state=command('status')
                    if float(state.get('elapsed',0))>.2:break
                    if state.get('error'):self.fail(state['error'])
                    time.sleep(.1)
                self.assertGreater(float(state.get('elapsed',0)),.2,(state,ranges))
                self.assertFalse(live.complete)
                print('MPD began playing after',round(time.monotonic()-started,3),'seconds; writer still incomplete;',json.dumps(ranges),flush=True)
                with path.open('ab') as out:out.write(tone*RATE*36)
                live.refresh(complete=True);path.unlink()
                command('seekcur 20');time.sleep(.3)
                state=command('status')
                self.assertEqual(state['state'],'play');self.assertGreaterEqual(float(state['elapsed']),20)
                command('stop');stream.close()
            finally:
                live.fail()
                if connection:connection.close()
                proc.terminate()
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
                log.close();server.shutdown();server.server_close()
                if not live.complete:print((root/'mpd.log').read_text(),flush=True)


if __name__=='__main__':unittest.main(verbosity=2)

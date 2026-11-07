"""Pi-only: record an isolated MPD's synthetic output; no real AUX or music files."""
import array
import io
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path

from flask import Flask,Response,request
from werkzeug.serving import make_server
from archive_queue import ArchiveQueue
from live_audio import RATE,wav_header


class NativeFadeTest(unittest.TestCase):
    def test_three_second_overlap_and_logical_queue_advance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);output=root/'mixed.wav'
            app=Flask(__name__)
            @app.get('/audio/TESTDISC1/<int:number>')
            def audio(number):
                # MPD deliberately excludes clips shorter than 20 s from crossfades.
                pcm=struct.pack('<hh',4000 if number==1 else 0,4000 if number==2 else 0)*RATE*21
                data=wav_header(RATE*21)+pcm;start,end=0,len(data)-1
                if request.headers.get('Range'):
                    value=request.headers['Range'].removeprefix('bytes=');a,b=value.split('-')
                    start=int(a);end=min(end,int(b)) if b else end
                headers={'Content-Type':'audio/wav','Content-Length':str(end-start+1),'Accept-Ranges':'bytes'}
                if request.headers.get('Range'):headers['Content-Range']=f'bytes {start}-{end}/{len(data)}'
                return Response(data[start:end+1],headers=headers,status=206 if request.headers.get('Range') else 200)
            server=make_server('127.0.0.1',0,app,threaded=True)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            config=root/'mpd.conf'
            config.write_text(f'bind_to_address "127.0.0.1"\nport "{port}"\n'
                f'db_file "{root}/db"\nplaylist_directory "{root}"\naudio_buffer_size "4096"\n'
                'decoder {\n plugin "ffmpeg"\n analyzeduration "100000"\n probesize "32768"\n}\n'
                'audio_output {\n type "null"\n name "silent clock"\n}\n'
                f'audio_output {{\n type "recorder"\n name "test recording"\n path "{output}"\n encoder "wave"\n format "44100:16:2"\n}}\n')
            log=(root/'mpd.log').open('wb')
            proc=subprocess.Popen(['mpd','--no-daemon','--stderr',str(config)],stdout=log,stderr=log)
            connection=None;stream=None
            try:
                for _ in range(50):
                    try:connection=socket.create_connection(('127.0.0.1',port),timeout=3);break
                    except OSError:time.sleep(.1)
                self.assertIsNotNone(connection)
                stream=connection.makefile('rwb');stream.readline()
                commands=[]
                def execute(*values):
                    results=[]
                    for text in values:
                        commands.append(text);stream.write((text+'\n').encode());stream.flush();rows=[]
                        while True:
                            line=stream.readline().decode().strip()
                            if line=='OK':break
                            if not line or line.startswith('ACK'):raise RuntimeError(line)
                            rows.append(line)
                        results.append(rows)
                    return results
                class Store:
                    def attach(self,d):pass
                    def ready(self,n):return n in (1,2)
                    playable=ready
                    def playback_uri(self,n):return f'http://127.0.0.1:{server.server_port}/audio/TESTDISC1/{n}'
                    server_uri=playback_uri
                    def local_end_seconds(self,n):return None
                    def release_playback(self):pass
                    def prioritize(self,order):pass
                disc={'id':'TESTDISC1','tracks':[{'number':1},{'number':2}]}
                q=ArchiveQueue(execute,root/'queue.json',Store())
                q.action(disc,'play',{})
                seen=[];deadline=time.monotonic()+50
                while time.monotonic()<deadline:
                    state,_=q.observe(disc);seen.append(state['track'])
                    if state.get('error'):self.fail(state['error'])
                    if state.get('state')=='stop' and not q.data['intent']:break
                    time.sleep(.05)
                else:self.fail('Playback did not finish')
                self.assertIn(2,seen);self.assertIn(1,q.data['handled'])
                self.assertEqual(commands.count('clear'),1,'Native transition must not reload the playlist')
            finally:
                if stream:stream.close()
                if connection:connection.close()
                proc.terminate()
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
                log.close();server.shutdown();server.server_close()
            if not output.exists():self.fail((root/'mpd.log').read_text())
            with wave.open(str(output)) as wav:
                self.assertEqual((wav.getframerate(),wav.getsampwidth(),wav.getnchannels()),(RATE,2,2))
                samples=array.array('h',wav.readframes(RATE*50))
            frames=len(samples)//2
            overlap=sum(samples[2*i]>10 and samples[2*i+1]>10 for i in range(frames))/RATE
            scheduled_overlap=42-frames/RATE
            print('Recorded duration:',round(frames/RATE,3),'s; overlap from duration:',round(scheduled_overlap,3),
                  's; simultaneous samples above threshold:',round(overlap,3),'s',flush=True)
            self.assertAlmostEqual(frames/RATE,39,delta=.15)
            self.assertAlmostEqual(scheduled_overlap,3,delta=.05)
            # The near-silent tips of MPD's fade curve can round below 10/32768.
            self.assertGreater(overlap,2.5);self.assertLess(overlap,3.05)


if __name__=='__main__':unittest.main(verbosity=2)

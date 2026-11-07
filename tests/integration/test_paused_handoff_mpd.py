"""Isolated native MPD/null output; synthetic audio and no production commands."""
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from flask import Flask, send_file
from werkzeug.serving import make_server
from live_audio import RATE, wav_header
from tools.paused_handoff import Client, handoff, values, playlist


class PausedHandoffTest(unittest.TestCase):
    def test_seekid_replacement_keeps_pause_position_and_successor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);audio=root/'test.wav';audio.write_bytes(wav_header(RATE*30)+b'\xe8\x03\x18\xfc'*RATE*30)
            web=Flask(__name__)
            @web.route('/audio/TESTDISC1/<int:number>',methods=['GET','HEAD'])
            def serve(number):
                response=send_file(audio,mimetype='audio/wav',conditional=True)
                response.headers['Accept-Ranges']='bytes'
                return response
            server=make_server('127.0.0.1',0,web,threaded=True)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            config=root/'mpd.conf';config.write_text(f'bind_to_address "127.0.0.1"\nport "{port}"\ndb_file "{root}/db"\nplaylist_directory "{root}"\naudio_buffer_size "4096"\ndecoder {{\n plugin "ffmpeg"\n analyzeduration "100000"\n probesize "32768"\n}}\naudio_output {{\n type "null"\n name "silent handoff test"\n}}\n')
            log=(root/'mpd.log').open('wb');proc=subprocess.Popen(['mpd','--no-daemon','--stderr',str(config)],stdout=log,stderr=log)
            client=Client('127.0.0.1',port)
            try:
                for _ in range(50):
                    try:client('status');break
                    except OSError:time.sleep(.1)
                base=f'http://127.0.0.1:{server.server_port}/audio/TESTDISC1/'
                old=values(client('addid "'+base+'1?local='+'a'*32+'"'))['Id']
                successor=values(client('addid "'+base+'2"'))['Id']
                client('consume 1');client('playid '+old)
                for _ in range(50):
                    if float(values(client('status')).get('elapsed',0))>.2:break
                    time.sleep(.1)
                client('pause 1');client('seekcur 11.898')
                checkpoints=[];commands=[]
                def execute(command):commands.append(command.split()[0]);return client(command)
                result=handoff(execute,base+'1',lambda _:None,checkpoints.append)
                self.assertTrue(result['ok']);self.assertTrue(checkpoints)
                after=values(client('status'));self.assertEqual(after['state'],'pause')
                self.assertAlmostEqual(float(after['elapsed']),11.898,delta=.05)
                self.assertEqual(after['consume'],'1');self.assertNotEqual(after['songid'],old)
                entries=playlist(client('playlistinfo'));self.assertEqual(len(entries),2)
                self.assertEqual(entries[0]['file'],base+'1');self.assertEqual(entries[1]['Id'],successor)
                self.assertFalse(set(commands)&{'play','playid','stop','clear','pause'})
                time.sleep(.3);self.assertEqual(values(client('status'))['state'],'pause')
                self.assertAlmostEqual(float(values(client('status'))['elapsed']),11.898,delta=.05)
                print('Native paused server handoff: pause retained at 11.898, consume and successor retained; no play/stop/clear/pause command.',flush=True)
            except Exception:
                print('Synthetic MPD diagnostics:',values(client('status')),(root/'mpd.log').read_text(),flush=True)
                raise
            finally:
                proc.terminate()
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
                log.close();server.shutdown();server.server_close()

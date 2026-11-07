"""Explicit maintenance handoff of a paused complete local track; no play/stop/restart."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time


def values(rows):return dict(line.split(': ',1) for line in rows if ': ' in line)


def playlist(rows):
    result=[]
    for line in rows:
        key,_,value=line.partition(': ')
        if key=='file':result.append({'file':value})
        elif result:result[-1][key]=value
    return result


class Client:
    def __init__(self,host,port):self.host,self.port=host,port
    def __call__(self,command):
        with socket.create_connection((self.host,self.port),timeout=5) as sock:
            sock.settimeout(20)
            with sock.makefile('rwb') as stream:
                if not stream.readline().startswith(b'OK MPD'):raise RuntimeError('MPD unavailable')
                stream.write((command+'\n').encode());stream.flush();rows=[]
                for _ in range(10000):
                    line=stream.readline().decode().strip()
                    if line=='OK':return rows
                    if not line or line.startswith('ACK'):raise RuntimeError('MPD command refused')
                    rows.append(line)
                raise RuntimeError('MPD response too large')


def handoff(client,server,head,checkpoint):
    """Requires a complete server copy and exclusive maintenance ownership outside."""
    def status():return values(client('status'))
    def checked(row,identity,elapsed):
        if row.get('state')!='pause' or row.get('songid')!=identity or row.get('error'):
            raise RuntimeError('Paused player changed')
        if abs(float(row.get('elapsed',-999))-elapsed)>.05:raise RuntimeError('Paused position changed')
    before=status();old=values(client('currentsong'));entries=playlist(client('playlistinfo'))
    if before.get('state')!='pause' or before.get('error'):raise RuntimeError('Only paused audio can be adopted')
    original=old.get('file','');oldid=before.get('songid','')
    if not re.fullmatch(re.escape(server)+r'\?local=[0-9a-f]{32}',original):raise RuntimeError('Not the expected local track')
    if not oldid.isdecimal() or not before.get('song','').isdecimal():raise RuntimeError('Unknown current song')
    position=int(before['song']);elapsed=float(before['elapsed'])
    if position>=len(entries) or entries[position].get('Id')!=oldid:raise RuntimeError('Playlist changed')
    if len(entries)>99 or before.get('consume') not in ('0','1'):raise RuntimeError('Unsupported playlist mode')
    if any(not e.get('Id','').isdecimal() for e in entries):raise RuntimeError('Unknown playlist id')
    head(server)
    checkpoint({'status':before,'entries':entries})
    checked(status(),oldid,elapsed)
    new=None
    try:
        client('consume 0')
        new=values(client(f'addid "{server}" {position+1}')).get('Id')
        if not new or not new.isdecimal():raise RuntimeError('No replacement id')
        checked(status(),oldid,elapsed)
        client(f'seekid {new} {elapsed}')
        checked(status(),new,elapsed)
        if values(client('currentsong')).get('file')!=server:raise RuntimeError('Replacement URI mismatch')
        client('deleteid '+oldid)
        expected=[(e['file'],e['Id']) for e in entries];expected[position]=(server,new)
        if [(e['file'],e['Id']) for e in playlist(client('playlistinfo'))]!=expected:
            raise RuntimeError('Playlist sequence changed')
        client('consume '+before['consume']);checked(status(),new,elapsed)
        return {'ok':True,'paused':True,'elapsed':elapsed,'playlist_preserved':True,'server_copy':True}
    except BaseException:
        try:
            client('consume 0')
            actual=playlist(client('playlistinfo'))
            actual_ids={e.get('Id') for e in actual}
            if new is None:
                extras=[e for e in actual if e.get('Id') not in {x['Id'] for x in entries} and e.get('file')==server]
                if len(extras)>1:raise RuntimeError('Ambiguous replacement')
                new=extras[0]['Id'] if extras else None
            restoreid=values(client(f'addid "{original}" {position}')).get('Id') if oldid not in actual_ids else oldid
            client(f'seekid {restoreid} {elapsed}');checked(status(),restoreid,elapsed)
            if new:client('deleteid '+new)
            client('consume '+before['consume'])
        except BaseException:raise RuntimeError('Handoff recovery failed; inspect private checkpoint') from None
        raise RuntimeError('Handoff refused/failed; paused original restored') from None


def remote_main(helpers):
    ns={'__name__':'deployment_helpers'};exec(helpers,ns)
    root=Path('/home/tijmen/cdspeler');system=ns['System'](root)
    fd=os.open(root/'.deployment.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        system.verify_identity(root)
        manifest=ns['installed'](root);ns['verify'](root,manifest['files'])
        before=system.mpd('status');snapshot=system.status();ns['safe_state'](snapshot,before)
        identity=snapshot['disc']['id'];number=snapshot['player']['track']
        if not re.fullmatch(r'[A-Za-z0-9_.-]{8,100}',identity) or not str(number).isdigit():raise RuntimeError('Invalid track')
        if not snapshot['disc'].get('present'):raise RuntimeError('Unknown album')
        server=system.audio_base_url+f'/audio/{identity}/{number}'
        pid=system.pid();folder=Path(tempfile.mkdtemp(prefix='paused-handoff-',dir=root/'backups'));folder.chmod(0o700)
        def checkpoint(row):ns['atomic_write'](folder/'checkpoint.json',json.dumps(row).encode(),0o600)
        result=handoff(Client(system.mpd_host,system.mpd_port),server,system.head,checkpoint)
        if system.pid()!=pid:raise RuntimeError('MPD identity changed')
        result['backup_id']=folder.name
        ns['atomic_write'](folder/'result.json',json.dumps(result).encode(),0o600)
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    if not args.apply:
        print('Plan only: adopt a confirmed server copy at the same paused position; --apply required.')
        return
    root=Path(__file__).resolve().parents[1]
    if subprocess.check_output(['git','status','--porcelain'],cwd=root):raise SystemExit('Clean committed sources required')
    source=Path(__file__).read_text();helpers=(root/'tools/deploy_remote.py').read_text()
    bootstrap="import sys,json; p=json.load(sys.stdin); n={'__name__':'handoff_remote'};exec(p['source'],n);\ntry: print(json.dumps(n['remote_main'](p['helpers'])))\nexcept BaseException: print('Paused handoff refused/failed; inspect private checkpoint.',file=sys.stderr);sys.exit(1)"
    import shlex
    result=subprocess.run([str(root/'tools/pi-ssh'),'python3 -c '+shlex.quote(bootstrap)],input=json.dumps({'source':source,'helpers':helpers}),text=True,capture_output=True)
    if result.returncode:raise SystemExit('Paused handoff refused/failed; inspect state before retrying.')
    print(result.stdout.strip())


if __name__=='__main__':main()

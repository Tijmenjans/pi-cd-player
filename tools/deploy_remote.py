"""Pi-only deployment transaction. Standard library; stdin/stdout JSON protocol.

No work on import. All transport errors are deliberately redacted by main().
"""
import base64
import contextlib
import datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import shlex
import socket
import stat
import subprocess
import tempfile
import time
import urllib.request

ROOT = Path('/home/tijmen/cdspeler')
HEX = re.compile(r'[0-9a-f]{64}')
COMMIT = re.compile(r'[0-9a-f]{40}')
TOOLS = {'tools/dependency_manifest.py', 'tools/import_discogs.py'}
MAX_BYTES = 32 * 1024 * 1024

class Refused(RuntimeError):
    """A precondition failed; messages must never contain private runtime values."""


def require(condition, message):
    if not condition:
        raise Refused(message)


def allowed(name):
    if not isinstance(name, str) or not name or '\\' in name:
        return False
    p = PurePosixPath(name)
    if p.is_absolute() or str(p) != name or any(x in ('..', '.') or x.startswith('.') for x in p.parts):
        return False
    return (name == 'static/christmas-fire.mp4' or (len(p.parts) == 1 and re.fullmatch(r'[A-Za-z0-9_-]+\.py', name) is not None)
            or (len(p.parts) > 1 and p.parts[0] == 'static'
                and p.suffix.lower() in {'.js', '.css', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.ico', '.html'})
            or (len(p.parts) == 2 and p.parts[0] == 'catalogue' and p.suffix == '.json')
            or name in TOOLS)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def manifest_valid(m):
    require(isinstance(m, dict) and m.get('schema') == 1 and m.get('component') == 'pi-player', 'Invalid release schema')
    require(isinstance(m.get('commit'), str) and COMMIT.fullmatch(m['commit']), 'Invalid commit')
    try:
        stamp = datetime.datetime.fromisoformat(m['built_at'].replace('Z', '+00:00'))
        require(stamp.tzinfo is not None, 'Timestamp needs timezone')
    except (ValueError, KeyError, TypeError, AttributeError):
        raise Refused('Invalid release timestamp') from None
    require(isinstance(m.get('files'), dict) and 'app.py' in m['files'], 'Missing runtime manifest')
    require(len(m['files']) <= 1000, 'Too many files')
    for name, record in m['files'].items():
        require(allowed(name), 'Non-allowlisted path')
        require(isinstance(record, dict) and isinstance(record.get('sha256'), str)
                and HEX.fullmatch(record['sha256']) and type(record.get('mode')) is int
                and record['mode'] in (0o644, 0o755), 'Invalid file record')
    return m


def safe_path(root, name):
    require(allowed(name) or name == 'release.json', 'Non-allowlisted destination')
    path = root / name
    require(not root.is_symlink(), 'Symlink root')
    cursor = path
    while cursor != root:
        require(not cursor.is_symlink(), 'Symlink destination')
        cursor = cursor.parent
    require(not path.exists() or path.is_file(), 'Not a regular destination')
    return path


def record(path):
    if not path.exists():
        return None
    require(path.is_file() and not path.is_symlink(), 'Not a regular file')
    return {'sha256': digest(path.read_bytes()), 'mode': stat.S_IMODE(path.stat().st_mode)}


def validate_bundle(bundle):
    m = manifest_valid(bundle['manifest'])
    require(set(bundle['content']) == set(m['files']), 'Payload names mismatch')
    total = 0
    decoded = {}
    for name, entry in m['files'].items():
        try:
            data = base64.b64decode(bundle['content'][name], validate=True)
        except (ValueError, TypeError):
            raise Refused('Invalid payload encoding') from None
        total += len(data)
        require(total <= MAX_BYTES and digest(data) == entry['sha256'], 'Payload size/hash mismatch')
        if name.endswith('.py'):
            compile(data, name, 'exec')
        decoded[name] = data
    return m, decoded


def safe_state(s, mpd, interrupt_import=False):
    require(isinstance(s, dict) and s.get('source') == 'cd', 'Only inactive/paused CD is supported')
    require(not s.get('error') and not s.get('transition', {}).get('pending')
            and not s.get('transition', {}).get('active') and not s.get('transition', {}).get('error'), 'Unknown/error/transition status')
    require(s.get('player', {}).get('state') in ('stop', 'pause'), 'Playback is active or unknown')
    require(not s.get('player', {}).get('buffering'), 'Player buffering')
    require(not s.get('dvd', {}).get('streaming') and not s.get('vinyl'), 'DVD/vinyl active')
    a = s.get('archive', {})
    if interrupt_import:
        require(mpd.get('state') == 'stop', 'Import interruption requires stopped playback')
        require(type(a.get('total')) is int and type(a.get('stored')) is int
                and 0 <= a['stored'] <= a['total'], 'Unknown import counts')
        require(not a.get('error') and not a.get('drive_blocked') and not a.get('buffer_full'), 'Archive unhealthy')
        states = a.get('states')
        require(isinstance(states, dict) and len(states) == a['total'], 'Unknown archive states')
        require(all(isinstance(v, dict) and not v.get('archive_error') and
                    v.get('storage') in ('ready', 'pending', 'ripping', 'uploading', 'retrying_upload', 'processing', 'buffered')
                    for v in states.values()), 'Unsafe archive state')
    else:
        require(type(a.get('total')) is int and type(a.get('stored')) is int
                and a['total'] >= 0 and a['stored'] == a['total'], 'Imports incomplete or unknown')
        require(not a.get('error') and not a.get('drive_blocked') and not a.get('buffer_full'), 'Archive not idle')
        states = a.get('states')
        require(isinstance(states, dict) and len(states) == a['total'], 'Unknown archive states')
        require(all(isinstance(v, dict) and v.get('ready') is True and v.get('storage') == 'ready'
                    for v in states.values()), 'Imports pending')
        tracks = s.get('disc', {}).get('tracks', [])
        require(isinstance(tracks, list) and len(tracks) == a['total'], 'Unknown disc state')
        require(all(t.get('ready') is True and t.get('storage') == 'ready' for t in tracks), 'Track imports pending')
    require(mpd.get('state') == s['player']['state'] and not mpd.get('error'), 'MPD disagrees with API')
    require(mpd['state'] in ('stop', 'pause'), 'MPD not idle')
    if mpd['state'] == 'pause':
        require(str(mpd.get('songid', '')).isdigit(), 'Unknown song')
        try:
            require(float(mpd['elapsed']) >= 0, 'Invalid position')
        except (KeyError, ValueError, TypeError):
            raise Refused('Unknown position') from None


def compatible_session(status, files):
    # Older releases interpret absent physical media as a lost playback session.
    require(not status.get('disc', {}).get('ejected') or 'cd_session.py' in files,
            'Detached album requires a session-compatible release; do not roll back during detached playback')


def unchanged(before, after):
    require(before.get('state') == after.get('state') and before.get('songid') == after.get('songid'), 'Player changed')
    require(not after.get('error'), 'MPD error')
    if before['state'] == 'pause':
        require(abs(float(before['elapsed']) - float(after.get('elapsed', '-999'))) < .05, 'Position changed')


def wait_idle(system,before,timeout=30,interrupt_import=False):
    deadline=time.monotonic()+timeout
    while True:
        current=system.mpd('status');unchanged(before,current)
        try:
            safe_state(system.status(),current,interrupt_import)
            return
        except Refused:
            require(time.monotonic()<deadline,'Archive status did not settle after restart')
            time.sleep(.2)


class System:
    """Bounded, fixed local endpoints; never reads secret configuration."""
    def __init__(self, root=ROOT):
        self.root=Path(root)
        path=self.root/'data/installation.json'
        row=json.loads(path.read_text()) if path.exists() else {}
        require(isinstance(row,dict),'Invalid installation configuration')
        self.web_port=row.get('web_port',8080)
        self.mpd_port=row.get('mpd_port',6601)
        self.mpd_host=row.get('mpd_host','127.0.0.1')
        require(row.get('web_host','0.0.0.0') in ('0.0.0.0','127.0.0.1'),'Unsupported local relay binding')
        require(all(type(p) is int and 1024<=p<=65535 for p in (self.web_port,self.mpd_port)),'Invalid installation ports')
        try:local=ipaddress.ip_address(self.mpd_host).is_loopback
        except (ValueError,TypeError):local=self.mpd_host=='localhost'
        require(local,'MPD must be local')
        self.audio_base_url=f'http://127.0.0.1:{self.web_port}'

    def verify_identity(self,root):
        raw=subprocess.check_output(['systemctl','--user','show','cdspeler-web',
                                     '-p','ExecStart','-p','WorkingDirectory','-p','MainPID'],timeout=5,text=True)
        fields=dict(line.split('=',1) for line in raw.splitlines() if '=' in line)
        require(fields.get('WorkingDirectory')==str(root),'Service working directory does not match target')
        args=re.search(r'argv\[\]=(.*?) ;',fields.get('ExecStart',''))
        require(args is not None,'Unknown service command')
        argv=shlex.split(args[1])
        require(len(argv)==2 and argv[1] in (str(root/'app.py'),str(root/'player_server.py')),'Service entrypoint does not match target')
        process=fields.get('MainPID','0')
        require(process.isdigit() and process!='0','Service process unavailable')
        require(Path('/proc',process,'cwd').resolve()==root.resolve(),'Process directory does not match target')
        # Inspect only the two relevant environment keys; never output process environment.
        env={}
        for entry in Path('/proc',process,'environ').read_bytes().split(b'\0'):
            key,_,value=entry.partition(b'=')
            if key in (b'CDSPELER_ROOT',b'CDSPELER_CONFIG'):env[key.decode()]=value.decode()
        require(Path(env.get('CDSPELER_ROOT',str(root))).resolve()==root.resolve(),'Runtime root does not match target')
        require(Path(env.get('CDSPELER_CONFIG',str(root/'data/installation.json'))).resolve()==(root/'data/installation.json').resolve(),'Unsupported service configuration override')

    def status(self):
        return self.get('/api/status')

    def get(self, path):
        with urllib.request.urlopen(self.audio_base_url + path, timeout=5) as r:
            require(r.status == 200, 'Backend unavailable')
            return json.loads(r.read(2 * 1024 * 1024))

    def service(self, action):
        require(action in ('stop', 'start'), 'Invalid service action')
        subprocess.run(['systemctl', '--user', action, 'cdspeler-web'], check=True,
                       capture_output=True, timeout=35)

    def web_pid(self):
        return subprocess.check_output(['systemctl', '--user', 'show', 'cdspeler-web',
                                        '-p', 'MainPID', '--value'], timeout=5).strip()

    def pid(self):
        return subprocess.check_output(['systemctl', '--user', 'show', 'cdspeler-mpd',
                                        '-p', 'MainPID', '--value'], timeout=5).strip()

    def mpd(self, command):
        with socket.create_connection((self.mpd_host, self.mpd_port), timeout=5) as sock:
            sock.settimeout(5)
            with sock.makefile('rwb') as f:
                require(f.readline(4096).startswith(b'OK MPD'), 'MPD unavailable')
                f.write((command + '\n').encode()); f.flush()
                result = {}
                for _ in range(10000):
                    line = f.readline(65536).decode().rstrip('\n')
                    if line == 'OK':
                        return result
                    require(line and not line.startswith('ACK'), 'MPD command failed')
                    if ': ' in line:
                        key, value = line.split(': ', 1); result[key] = value
                raise Refused('MPD response too large')

    def head(self, url):
        with urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=10) as r:
            require(r.status == 200 and int(r.headers.get('Content-Length', '0')) > 0, 'Server audio not ready')
            require(r.geturl() == url, 'Unexpected audio redirect')

    def healthy(self, manifest):
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                require(self.get('/health').get('ok') is True, 'Health unavailable')
                require(self.get('/ready').get('ok') is True, 'Backend not ready')
                version = self.get('/api/version')
                require(all(version.get(k) == manifest[k] for k in ('schema', 'component', 'commit', 'built_at'))
                        and version.get('installed') is True, 'Backend version mismatch')
                return
            except Exception:
                time.sleep(.5)
        raise Refused('Backend health/version verification failed')

    def old_healthy(self):
        self.status()  # Pre-release installations may not have health endpoints.


def installed(root):
    path = safe_path(root, 'release.json')
    return manifest_valid(json.loads(path.read_text())) if path.exists() else None


def baseline_check(root, target, baseline):
    old = installed(root)
    expected = dict(old['files']) if old else baseline
    if old and baseline is not None:
        for name in set(target['files']) - set(old['files']):
            require(name in baseline and baseline[name] is None, 'New path needs explicit absent baseline')
            expected[name] = None
    require(isinstance(expected, dict) and set(target['files']).issubset(expected), 'Explicit baseline required for unmarked installation/new files')
    if old:
        require(set(old['files']).issubset(target['files']), 'Removing runtime files requires separate maintenance')
    for name, exp in expected.items():
        path = safe_path(root, name)
        require(exp is None or (isinstance(exp, dict) and isinstance(exp.get('sha256'), str)
                               and HEX.fullmatch(exp['sha256']) and exp.get('mode') in (0o644, 0o755)), 'Invalid baseline')
        require(record(path) == exp, 'Installed files drifted; inspect and supply reviewed baseline')
    return old


def atomic_write(path, data, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.deploy-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def verify(root, entries):
    for name, expected in entries.items():
        require(record(safe_path(root, name)) == expected, 'File verification failed')


def restore(root, backup, info):
    # Verify every backup before any overwrite or deletion.
    for name, expected in info['previous'].items():
        safe_path(root, name)
        if expected is not None:
            require(record(safe_path(backup / 'code', name)) == expected, 'Backup corrupt')
    for name, expected in info['previous'].items():
        dest = safe_path(root, name)
        if expected is None:
            dest.unlink(missing_ok=True)
        else:
            atomic_write(dest, (backup / 'code' / name).read_bytes(), expected['mode'])
    verify(root, info['previous'])


def assets_transaction(root, manifest, content, system, baseline=None):
    """Static-only update: no status/MPD/optical calls, no service stop/start."""
    system.verify_identity(root)
    old=installed(root)
    require(old is not None,'Static updates require an installed release')
    added=set(manifest['files'])-set(old['files'])
    require(not (set(old['files'])-set(manifest['files'])),'Static updates cannot remove paths')
    require(added <= {'static/christmas-fire.mp4'} and all(baseline is not None and name in baseline and baseline[name] is None and record(safe_path(root,name)) is None for name in added),'New UI video requires explicit absent baseline')
    if 'static/christmas-fire.mp4' in manifest['files']:
        require(len(content['static/christmas-fire.mp4']) <= 2*1024*1024 and content['static/christmas-fire.mp4'][4:8] == b'ftyp','Invalid or oversized UI video')
    changed={name for name,entry in manifest['files'].items() if old['files'].get(name)!=entry}
    require(bool(changed) and all(name.startswith('static/') for name in changed),
            'Only existing static files may change; runtime changes require normal apply')
    verify(root,old['files'])
    pid=system.web_pid();require(pid not in (b'',b'0','','0'),'Unknown web process')
    system.healthy(old)
    backups=root/'backups';require(not backups.is_symlink(),'Symlink backup directory')
    backups.mkdir(mode=0o700,exist_ok=True)
    backup=Path(tempfile.mkdtemp(prefix='deploy-',dir=backups));backup.chmod(0o700)
    previous={name:record(safe_path(root,name)) for name in list(manifest['files'])+['release.json']}
    info={'schema':1,'mode':'assets','previous':previous,'installed':manifest,'old_manifest':old}
    for name,entry in previous.items():
        if entry is None:continue
        dest=backup/'code'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(safe_path(root,name),dest)
        require(record(dest)==entry,'Static backup verification failed')
    atomic_write(backup/'backup.json',json.dumps(info).encode(),0o600)
    require(json.loads((backup/'backup.json').read_text())==info,'Static backup metadata mismatch')
    with tempfile.TemporaryDirectory(prefix='.deploy-assets-',dir=root) as staging:
        stage=Path(staging)
        for name in changed:atomic_write(stage/name,content[name],manifest['files'][name]['mode'])
        verify(stage,{name:manifest['files'][name] for name in changed})
        verify(root,old['files']);require(installed(root)==old,'Release changed during staging')
        require(system.web_pid()==pid,'Web process changed during staging')
        try:
            for name in sorted(changed,key=lambda n:(n.endswith('.html'),n)):atomic_write(safe_path(root,name),(stage/name).read_bytes(),manifest['files'][name]['mode'])
            atomic_write(root/'release.json',json.dumps(manifest).encode(),0o644)
            verify(root,manifest['files']);system.healthy(manifest);system.verify_identity(root)
            require(system.web_pid()==pid,'Web process changed during static update')
        except BaseException:
            try:
                # Restore only the assets and marker; never touch loaded modules.
                for name in sorted(changed|{'release.json'}):
                    require(previous[name] is None or record(backup/'code'/name)==previous[name],'Static recovery backup corrupt')
                for name in sorted(changed|{'release.json'}):
                    if previous[name] is None:safe_path(root,name).unlink(missing_ok=True)
                    else:atomic_write(safe_path(root,name),(backup/'code'/name).read_bytes(),previous[name]['mode'])
                verify(root,old['files']);system.healthy(old)
            except BaseException:
                raise Refused('Static recovery failed. Safety backup ID: '+backup.name) from None
            raise Refused('Static update failed; previous assets restored. Safety backup ID: '+backup.name) from None
    return {'ok':True,'mode':'assets','commit':manifest['commit'],'backup_id':backup.name,
            'web_pid_unchanged':True,'services_restarted':False,'changed':sorted(changed)}


def transaction(root, manifest, content, system, baseline=None, interrupt_import=False):
    require(root.is_dir(), 'Runtime root missing')
    system.verify_identity(root)
    old = baseline_check(root, manifest, baseline)
    before = system.mpd('status'); status=system.status(); safe_state(status, before, interrupt_import)
    compatible_session(status, manifest['files'])
    mpd_pid = system.pid(); require(mpd_pid not in (b'', b'0', '', '0'), 'MPD process unknown')
    # Fail closed for old local stream tokens: require the separately tested
    # replacement mechanism before stopping web. No local file deletion occurs.
    if before['state'] == 'pause':
        song = system.mpd('currentsong')
        url = song.get('file', '')
        require('?local=' not in url, 'Paused local token: use verified server track before maintenance')
        require(re.fullmatch(re.escape(getattr(system,'audio_base_url','http://127.0.0.1:8080'))+r'/audio/[A-Za-z0-9_.-]+/[0-9]+', url),
                'Paused track is not a known server route')
        system.head(url)
        unchanged(before, system.mpd('status'))
    backups = root / 'backups'
    require(not backups.is_symlink(), 'Symlink backup directory')
    backups.mkdir(mode=0o700, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='deploy-', dir=backups)); backup.chmod(0o700)
    names = list(manifest['files']) + ['release.json']
    previous = {name: record(safe_path(root, name)) for name in names}
    info = {'schema': 1, 'previous': previous, 'installed': manifest, 'old_manifest': old}
    for name, entry in previous.items():
        if entry is not None:
            dest = backup / 'code' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(safe_path(root, name), dest)
            require(record(dest) == entry, 'Backup verification failed')
    atomic_write(backup / 'backup.json', json.dumps(info).encode(), 0o600)
    require(json.loads((backup / 'backup.json').read_text()) == info, 'Backup metadata verification failed')
    with tempfile.TemporaryDirectory(prefix='.deploy-stage-', dir=root) as stage_name:
        stage = Path(stage_name)
        for name, data in content.items():
            atomic_write(stage / name, data, manifest['files'][name]['mode'])
        verify(stage, manifest['files'])
        # Revalidate after backup and staging, immediately before stopping web.
        baseline_check(root, manifest, baseline)
        safe_state(system.status(), system.mpd('status'), interrupt_import)
        unchanged(before, system.mpd('status'))
        system.verify_identity(root)
        stopped = False
        try:
            stopped = True  # stop may have succeeded even if the command fails
            system.service('stop')
            unchanged(before, system.mpd('status'))
            for name in manifest['files']:
                atomic_write(safe_path(root, name), (stage / name).read_bytes(), manifest['files'][name]['mode'])
            atomic_write(safe_path(root, 'release.json'), json.dumps(manifest, sort_keys=True).encode(), 0o644)
            verify(root, manifest['files'])
            require(installed(root) == manifest, 'Release marker mismatch')
            system.service('start')
            system.healthy(manifest)
            wait_idle(system,before,interrupt_import=interrupt_import)
            verify(root, manifest['files'])
            require(installed(root) == manifest, 'Release marker changed')
            safe_state(system.status(), system.mpd('status'), interrupt_import)
            unchanged(before, system.mpd('status'))
            require(system.pid() == mpd_pid, 'MPD process changed')
        except BaseException:
            if stopped:
                try:
                    system.service('stop')
                    restore(root, backup, info)
                    system.service('start')
                    system.old_healthy()
                    unchanged(before, system.mpd('status'))
                except BaseException:
                    raise Refused('Deployment failed; automatic rollback failed. Use private backup ID: ' + backup.name) from None
            raise Refused('Deployment failed; previous files restored. Backup ID: ' + backup.name) from None
    return {'ok': True, 'commit': manifest['commit'], 'backup_id': backup.name}


def rollback(root, backup_id, system):
    require(isinstance(backup_id, str) and re.fullmatch(r'deploy-[A-Za-z0-9_-]+', backup_id), 'Invalid backup ID')
    backup = root / 'backups' / backup_id
    require(not (root / 'backups').is_symlink() and not backup.is_symlink() and backup.is_dir(), 'Backup unavailable')
    meta = backup / 'backup.json'
    require(meta.is_file() and not meta.is_symlink(), 'Backup metadata unavailable')
    info = json.loads(meta.read_text())
    current_manifest=info.get('installed')
    if current_manifest is not None:manifest_valid(current_manifest)
    else:manifest_valid(info['old_manifest'])
    require(installed(root) == current_manifest, 'Rollback requires exact installed release')
    expected_current=info.get('current_files') if current_manifest is None else current_manifest['files']
    require(isinstance(expected_current,dict) and all(allowed(n) or n=='release.json' for n in expected_current),'Invalid historical safety backup')
    verify(root, expected_current)
    previous = info['previous']
    require(isinstance(previous, dict) and set(previous) == set(expected_current) | {'release.json'},
            'Invalid backup file set')
    for name, expected in previous.items():
        safe_path(root, name)
        require(expected is None or record(safe_path(backup / 'code', name)) == expected, 'Backup corrupt')
    if info.get('old_manifest') is not None:
        manifest_valid(info['old_manifest'])
        require(previous['release.json'] is not None, 'Old marker missing')
        require(json.loads((backup / 'code' / 'release.json').read_text()) == info['old_manifest'], 'Old marker mismatch')
    else:
        require(previous['release.json'] is None, 'Unexpected historical marker')
    system.verify_identity(root)
    before = system.mpd('status'); status=system.status(); safe_state(status, before)
    compatible_session(status, {name for name, entry in previous.items() if entry is not None})
    mpd_pid = system.pid()
    require(mpd_pid not in (b'', b'0', '', '0'), 'MPD process unknown')
    if before['state'] == 'pause':
        url = system.mpd('currentsong').get('file', '')
        require(re.fullmatch(re.escape(getattr(system,'audio_base_url','http://127.0.0.1:8080'))+r'/audio/[A-Za-z0-9_.-]+/[0-9]+', url),
                'Paused track is not a confirmed server route')
        system.head(url)
    # Back up current code before rollback overwrites or removes anything.
    redo = Path(tempfile.mkdtemp(prefix='deploy-', dir=root / 'backups')); redo.chmod(0o700)
    current = {name: record(safe_path(root, name)) for name in previous}
    redo_info = {'schema': 1, 'previous': current,
                 'installed': info.get('old_manifest'), 'old_manifest': info['installed'],
                 'current_files': info['previous']}
    for name, entry in current.items():
        if entry is not None:
            path = redo / 'code' / name; path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(safe_path(root, name), path)
            require(record(path) == entry, 'Rollback safety backup failed')
    atomic_write(redo / 'backup.json', json.dumps(redo_info).encode(), 0o600)
    require(json.loads((redo / 'backup.json').read_text()) == redo_info, 'Rollback metadata verification failed')
    require(installed(root) == current_manifest, 'Installed marker changed')
    verify(root, expected_current)
    safe_state(system.status(), system.mpd('status'))
    unchanged(before, system.mpd('status'))
    system.verify_identity(root)
    try:
        system.service('stop')
        unchanged(before, system.mpd('status'))
        restore(root, backup, info)
        system.service('start')
        if info.get('old_manifest') is None:
            system.old_healthy()
        else:
            system.healthy(info['old_manifest'])
        verify(root, previous)
        safe_state(system.status(), system.mpd('status'))
        unchanged(before, system.mpd('status'))
        require(system.pid() == mpd_pid, 'MPD process changed')
    except BaseException:
        try:
            system.service('stop'); restore(root, redo, redo_info); system.service('start')
            if info['installed'] is None:system.old_healthy()
            else:system.healthy(info['installed'])
            unchanged(before, system.mpd('status'))
        except BaseException:
            raise Refused('Rollback recovery failed. Safety backup ID: ' + redo.name) from None
        raise Refused('Rollback failed; current release restored. Safety backup ID: ' + redo.name) from None
    return {'ok': True, 'backup_id': redo.name,
            'commit': (info.get('old_manifest') or {}).get('commit'),
            'historical': info.get('old_manifest') is None}



def dispatch(request, system=None, root=ROOT):
    require(root.is_absolute() and root!=Path('/') and '..' not in root.parts, 'Invalid installation root')
    system = system or System(root)
    action = request.get('action')
    if action == 'inspect':
        try:system.verify_identity(root);identity=True
        except Exception:identity=False
        return {'ok': True, 'release': installed(root),'identity_matches':identity,
                'safe': identity and inspect_safe(system)}
    require(action in ('apply', 'assets', 'rollback'), 'Invalid action')
    # Only mutation paths create a lock. A plan/inspect never writes remotely.
    import fcntl
    require(not root.is_symlink(), 'Symlink root')
    lock = root / '.deployment.lock'
    require(not lock.is_symlink(), 'Symlink lock')
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused('Another deployment is running') from None
        if action == 'rollback':
            return rollback(root, request['backup_id'], system)
        manifest, content = validate_bundle(request['bundle'])
        if action == 'assets':return assets_transaction(root, manifest, content, system, request.get('baseline'))
        return transaction(root, manifest, content, system, request.get('baseline'), request.get('interrupt_import') is True)


def inspect_safe(system):
    try:
        safe_state(system.status(), system.mpd('status'))
        return True
    except Exception:
        return False


def main():
    import sys
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES * 2 + 1)
        require(len(raw) <= MAX_BYTES * 2, 'Request too large')
        request=json.loads(raw)
        result = dispatch(request,root=Path(request.get('root',str(ROOT))))
        print(json.dumps(result))
    except Refused as exc:
        print(json.dumps({'ok': False, 'error': str(exc)})); return 1
    except BaseException:
        print(json.dumps({'ok': False, 'error': 'Deployment failed; inspect private backup locally on Pi'})); return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

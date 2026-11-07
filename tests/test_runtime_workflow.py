"""Config, release, ownership and standard test boundary regressions."""
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
import tests as _isolated_test_state
import app
import optical_disc
from release_info import read_release
from runtime_owner import RuntimeOwner
from runtime_settings import Settings
from tools.configure import render
from tools.private_backup import create,verify
from tools.setup_environment import commands
import player_server

class SettingsTests(unittest.TestCase):
    def test_defaults_preserve_existing_installation(self):
        settings=Settings.load(environ={'CDSPELER_ROOT':'/tmp/player'})
        self.assertEqual(settings.mpd_port,6601);self.assertEqual(settings.audio_base_url,'http://127.0.0.1:8080')
    def test_reject_invalid_or_secret_config_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'settings.json'
            for row in [{'mpd_host':'192.0.2.1'},{'web_port':True},{'speaker_address':'not-a-mac'},{'token':'private'},{'web_threads':1}]:
                path.write_text(json.dumps(row))
                with self.assertRaises(ValueError):Settings.load(environ={'CDSPELER_ROOT':tmp,'CDSPELER_CONFIG':str(path)})
    def test_explicit_missing_config_is_error(self):
        with self.assertRaises(ValueError):Settings.load(environ={'CDSPELER_ROOT':'/tmp/player','CDSPELER_CONFIG':'/missing-installation.json'})
    def test_generated_units_and_mpd_use_one_root(self):
        settings=Settings(install_root=Path('/home/listener/player'),mpd_port=6602)
        result=render(settings,Path(__file__).resolve().parents[1]/'deploy/systemd',python='/home/listener/player/.venv-player/bin/python',production=True)
        self.assertIn('/home/listener/player/player_server.py',result['cdspeler-web.service'])
        self.assertIn('port "6602"',result['mpd.conf'])
        self.assertNotIn('cdspeler-superdrive-wake@.service',result)
        self.assertFalse(any('/home/tijmen' in text for text in result.values()))
    def test_deployment_transport_reads_validated_local_network_settings(self):
        from tools.deploy_remote import System,Refused
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data').mkdir()
            (root/'data/installation.json').write_text(json.dumps({'web_port':8081,'mpd_port':6602}))
            system=System(root)
            self.assertEqual(system.audio_base_url,'http://127.0.0.1:8081');self.assertEqual(system.mpd_port,6602)
            (root/'data/installation.json').write_text(json.dumps({'mpd_host':'192.0.2.1'}))
            with self.assertRaises(Refused):System(root)

    def test_renderer_rejects_systemd_path_expansion(self):
        with self.assertRaises(ValueError):render(Settings(Path('/tmp/player%h')),Path(__file__).resolve().parents[1]/'deploy/systemd')
    def test_setup_plans_do_not_start_services(self):
        for profile in ('pi','test'):
            plan=commands(profile,Path('/tmp/project'))
            self.assertFalse(any('systemctl' in arg or 'sudo'==arg for row in plan for arg in row))
        self.assertIn('--system-site-packages',commands('pi',Path('/tmp/project'))[1])

class ReleaseTests(unittest.TestCase):
    def test_marker_exposes_only_public_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            row={'schema':1,'component':'pi-player','commit':'a'*40,'built_at':'2026-11-07T12:00:00Z','token':'never return this','files':{'private':'hidden'}}
            Path(tmp,'release.json').write_text(json.dumps(row))
            result=read_release(tmp)
            self.assertTrue(result['installed']);self.assertNotIn('token',result);self.assertNotIn('files',result)
    def test_missing_invalid_and_linked_marker_are_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.assertFalse(read_release(root)['installed'])
            (root/'release.json').write_text('{bad')
            self.assertFalse(read_release(root)['installed'])
            (root/'release.json').unlink();(root/'target').write_text('{}');(root/'release.json').symlink_to(root/'target')
            self.assertFalse(read_release(root)['installed'])
    def test_health_does_not_probe_drive_or_wait_for_mpd(self):
        with patch.object(app,'mpd',side_effect=AssertionError('health must not block')),patch.object(app,'optical_device',side_effect=AssertionError('drive')):
            response=app.app.test_client().get('/health')
            self.assertEqual(response.status_code,200);self.assertTrue(response.json['ok'])
    def test_readiness_requires_started_live_workers(self):
        with patch.object(app,'runtime_threads',[]),patch.object(app,'runtime_stop',threading.Event()):
            self.assertEqual(app.app.test_client().get('/ready').status_code,503)
        with patch.object(app,'runtime_threads',[Mock(is_alive=lambda:True)]),patch.object(app,'runtime_stop',threading.Event()):
            self.assertEqual(app.app.test_client().get('/ready').status_code,200)
    def test_version_endpoint_returns_no_configuration(self):
        response=app.app.test_client().get('/api/version')
        self.assertEqual(response.status_code,200)
        self.assertEqual(set(response.json),{'schema','component','commit','built_at','installed'})

class RuntimeTests(unittest.TestCase):
    def test_second_process_owner_is_refused_until_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=RuntimeOwner(Path(tmp)/'owner');second=RuntimeOwner(Path(tmp)/'owner')
            first.acquire()
            try:
                with self.assertRaises(RuntimeError):second.acquire()
            finally:first.release()
            second.acquire();second.release()
    def test_native_disc_error_is_translated_through_injected_backend(self):
        class NativeError(Exception):pass
        backend=Mock(DiscError=NativeError);backend.read.side_effect=NativeError('read failed')
        try:
            optical_disc.configure_backend(backend)
            with self.assertRaises(optical_disc.DiscError):optical_disc.read('/dev/fake')
        finally:optical_disc.configure_backend(disabled=True)
    def test_optional_server_starts_and_stops_runtime_even_on_server_error(self):
        with patch.object(app,'start_runtime') as start,patch.object(app,'stop_runtime') as stop:
            with self.assertRaises(OSError):player_server.run(serve=Mock(side_effect=OSError('server')))
            start.assert_called_once();stop.assert_called_once()

class DiscoveryTests(unittest.TestCase):
    def test_both_discovery_forms_ignore_real_runtime_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data').mkdir()
            (root/'data/archive.json').write_text(json.dumps({'url':'https://archive.example.invalid','token':'sentinel'}))
            (root/'data/source').write_text('cd')
            before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            for suffix in ([],['-t','.']):
                env=dict(os.environ,CDSPELER_ROOT=str(root))
                command=[sys.executable,'-m','unittest','discover','-s','tests','-p','test_api.py']+suffix
                result=subprocess.run(command,cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,timeout=15)
                self.assertEqual(result.returncode,0,'Isolated child discovery failed')
                after={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
                self.assertEqual(after,before)
                self.assertEqual(sorted(p.name for p in (root/'data').iterdir()),['archive.json','source'])

class MaintenanceTests(unittest.TestCase):
    def test_web_actions_refused_while_deployment_holds_exclusive_lease(self):
        path=app.ROOT/'.deployment.lock'
        with path.open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            response=app.app.test_client().post('/api/action',json={'action':'play'},headers={'X-CDSpeler':'1'})
            self.assertEqual(response.status_code,409)
            self.assertEqual(app.app.test_client().get('/health').status_code,200)

class BackupTests(unittest.TestCase):
    def test_private_backup_roundtrip_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'project';(root/'.ssh').mkdir(parents=True)
            (root/'.ssh/pi_identity').write_bytes(b'synthetic sensitive contents')
            destination=Path(tmp)/'external/backup'
            self.assertEqual(create(destination,root),1);self.assertEqual(verify(destination),1)
            with (destination/'private.tar.gz').open('ab') as stream:stream.write(b'corrupt')
            with self.assertRaises(ValueError):verify(destination)
    def test_backup_inside_project_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):create(Path(tmp)/'backups/new',Path(tmp))
    def test_source_symlinks_are_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'project';(root/'.ssh').mkdir(parents=True)
            (root/'.ssh/link').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):create(Path(tmp)/'external',root)

if __name__=='__main__':unittest.main()

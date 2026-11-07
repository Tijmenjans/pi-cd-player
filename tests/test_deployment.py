"""Deployment contracts against temporary files and fake systems; never SSH."""
import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / (name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

remote = load('deploy_remote')
local = load('deployment')


def bundle(commit='b' * 40, names=None):
    content = names or {'app.py': b'pass\n', 'static/app.js': b'// next\n'}
    m = {'schema': 1, 'commit': commit, 'component': 'pi-player',
         'built_at': '2026-11-07T13:00:00+00:00',
         'files': {n: {'sha256': remote.digest(b), 'mode': 0o644} for n, b in content.items()}}
    return {'manifest': m, 'content': {n: base64.b64encode(b).decode() for n, b in content.items()}}


class Fake:
    def __init__(self, state='pause'):
        self.state = {'state': state, 'songid': '17', 'elapsed': '99.105'}
        self.calls = []; self.fail_health = False; self.fail_stop = False
        self.url = 'http://127.0.0.1:8080/audio/disc-ID-/13'
        self.status_value = {'source': 'cd', 'player': {'state': state},
                             'archive': {'stored': 1, 'total': 1, 'states': {'13': {'ready': True, 'storage': 'ready'}}},
                             'disc': {'tracks': [{'ready': True, 'storage': 'ready'}]}}
        self.status_count = 0
    def mpd(self, command):
        self.calls.append(command)
        if command == 'currentsong': return {'file': self.url}
        if command == 'status': return dict(self.state)
        raise AssertionError('No MPD mutations permitted')
    def status(self):
        self.status_count += 1
        return copy.deepcopy(self.status_value)
    def verify_identity(self,root):pass
    def pid(self): return b'123'
    def head(self, url): self.calls.append('HEAD')
    def service(self, action):
        self.calls.append(action)
        if action == 'stop' and self.fail_stop:
            self.fail_stop = False
            raise OSError('fake stop timeout')
    def healthy(self, manifest):
        self.calls.append('health')
        if self.fail_health: raise OSError('fake health failure')
    def old_healthy(self): self.calls.append('old_health')


class Transactions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.initial = bundle('a' * 40, {'app.py': b'# original\n', 'static/app.js': b'// original\n'})
        m, files = remote.validate_bundle(self.initial)
        for name, data in files.items():
            p = self.root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data); p.chmod(0o644)
        (self.root / 'release.json').write_text(json.dumps(m)); (self.root / 'release.json').chmod(0o644)
        (self.root / 'data').mkdir(); (self.root / 'data' / 'sentinel').write_text('do not touch')
        self.system = Fake()
    def apply(self, b=None, baseline=None):
        return remote.dispatch({'action': 'apply', 'bundle': b or bundle(), 'baseline': baseline}, self.system, self.root)
    def test_apply_and_rollback_preserve_position_data(self):
        result = self.apply()
        self.assertEqual(remote.installed(self.root), bundle()['manifest'])
        self.assertEqual(self.system.state['elapsed'], '99.105')
        self.assertEqual((self.root/'data/sentinel').read_text(), 'do not touch')
        self.assertEqual((self.root/'backups'/result['backup_id']).stat().st_mode & 0o777, 0o700)
        remote.dispatch({'action': 'rollback', 'backup_id': result['backup_id']}, self.system, self.root)
        self.assertEqual(remote.installed(self.root), self.initial['manifest'])
        self.assertNotIn('restart', self.system.calls)
        self.assertIn('HEAD', self.system.calls)
    def test_detached_album_refuses_incompatible_apply_before_stopping(self):
        self.system.status_value['disc']['ejected']=True
        with self.assertRaisesRegex(remote.Refused,'session-compatible'):self.apply()
        self.assertNotIn('stop',self.system.calls)

    def test_detached_album_refuses_rollback_to_pre_session_release(self):
        candidate=bundle(names={'app.py':b'pass\n','static/app.js':b'// next\n','cd_session.py':b'pass\n'})
        result=self.apply(candidate,baseline={'cd_session.py':None})
        self.system.calls.clear();self.system.status_value['disc']['ejected']=True
        with self.assertRaisesRegex(remote.Refused,'session-compatible'):
            remote.dispatch({'action':'rollback','backup_id':result['backup_id']},self.system,self.root)
        self.assertNotIn('stop',self.system.calls)
        self.assertEqual(remote.installed(self.root),candidate['manifest'])

    def asset_bundle(self):
        return bundle(names={'app.py':b'# original\n','static/app.js':b'// Christmas assets\n'})

    def assets(self,b=None):
        self.system.web_pid=lambda:b'456'
        return remote.dispatch({'action':'assets','bundle':b or self.asset_bundle()},self.system,self.root)

    def test_static_update_preserves_active_runtime_without_mpd_or_status_calls(self):
        self.system=Fake('play')
        self.system.mpd=lambda command: (_ for _ in ()).throw(AssertionError('MPD must not be contacted'))
        self.system.status=lambda: (_ for _ in ()).throw(AssertionError('Hardware status must not be queried'))
        result=self.assets()
        self.assertTrue(result['web_pid_unchanged']);self.assertFalse(result['services_restarted'])
        self.assertEqual(result['changed'],['static/app.js'])
        self.assertEqual(self.system.calls,['health','health'])
        self.assertEqual(remote.installed(self.root),self.asset_bundle()['manifest'])
        self.assertEqual((self.root/'app.py').read_bytes(),b'# original\n')

    def test_static_update_refuses_runtime_changes_and_new_paths(self):
        for candidate in (bundle(),bundle(names={'app.py':b'# original\n','static/app.js':b'// next\n','static/new.css':b'body{}'})):
            with self.subTest(candidate=candidate):
                with self.assertRaises(remote.Refused):self.assets(candidate)
                self.assertNotIn('stop',self.system.calls)
        self.assertFalse((self.root/'backups').exists())

    def test_static_update_refuses_unmarked_or_drifted_installation(self):
        (self.root/'static/app.js').write_text('// drift')
        with self.assertRaises(remote.Refused):self.assets()
        self.assertNotIn('stop',self.system.calls)
        (self.root/'release.json').unlink()
        with self.assertRaises(remote.Refused):self.assets()

    def test_static_failed_verification_restores_assets_without_restart(self):
        original=self.system.healthy;calls=[0]
        def healthy(manifest):
            calls[0]+=1
            if calls[0]==2:raise OSError('synthetic health failure')
            return original(manifest)
        self.system.healthy=healthy
        with self.assertRaisesRegex(remote.Refused,'previous assets restored'):self.assets()
        self.assertEqual(remote.installed(self.root),self.initial['manifest'])
        self.assertEqual((self.root/'static/app.js').read_bytes(),b'// original\n')
        self.assertNotIn('stop',self.system.calls);self.assertNotIn('start',self.system.calls)

    def test_static_partial_write_failure_restores_both_files_and_marker(self):
        real=remote.atomic_write;failed=[False]
        def write(path,data,mode):
            if path==self.root/'release.json' and not failed[0]:failed[0]=True;raise OSError('disk full')
            return real(path,data,mode)
        with patch.object(remote,'atomic_write',side_effect=write):
            with self.assertRaisesRegex(remote.Refused,'previous assets restored'):self.assets()
        self.assertEqual(remote.installed(self.root),self.initial['manifest'])
        self.assertEqual((self.root/'static/app.js').read_bytes(),b'// original\n')
        self.assertNotIn('stop',self.system.calls)

    def test_static_backup_can_use_existing_safe_rollback(self):
        result=self.assets()
        remote.dispatch({'action':'rollback','backup_id':result['backup_id']},self.system,self.root)
        self.assertEqual(remote.installed(self.root),self.initial['manifest'])

    def test_idle_empty_disc(self):
        self.system = Fake('stop')
        self.system.status_value['archive'].update(stored=0, total=0, states={})
        self.system.status_value['disc']['tracks'] = []
        self.apply()
    def test_initializing_archive_may_settle_without_restarting_mpd(self):
        original=self.system.status
        calls=[0]
        def status():
            calls[0]+=1
            row=original()
            if calls[0]==1:row['archive']['stored']=0
            return row
        self.system.status=status
        remote.wait_idle(self.system,self.system.state,timeout=1)
        self.assertEqual(calls[0],2);self.assertNotIn('stop',self.system.calls)

    def test_activity_and_unknown_refused_before_backup(self):
        for source, state in [('cd','play'), ('dvd','stop'), ('vinyl','stop'), ('spotify','pause'), ('plexamp','stop'), ('cd','unknown')]:
            with self.subTest(source=source, state=state):
                self.system = Fake(state); self.system.status_value['source'] = source
                with self.assertRaises(remote.Refused): self.apply()
                self.assertNotIn('stop', self.system.calls)
        self.assertFalse((self.root/'backups').exists())
    def test_pending_and_unknown_imports_refused(self):
        for state in ('ripping','uploading','retrying_upload','processing','pending','blocked','skipped','stored'):
            with self.subTest(storage=state):
                self.system = Fake(); self.system.status_value['archive']['states']['13']['storage'] = state
                with self.assertRaises(remote.Refused): self.apply()
        self.system = Fake(); del self.system.status_value['archive']
        with self.assertRaises(remote.Refused): self.apply()
    def test_local_pause_refused(self):
        self.system.url += '?local=stale'
        with self.assertRaises(remote.Refused): self.apply()
        self.assertNotIn('HEAD', self.system.calls)
        self.assertNotIn('stop', self.system.calls)
    def test_head_failure_never_stops(self):
        self.system.head = lambda url: (_ for _ in ()).throw(OSError())
        with self.assertRaises(OSError): self.apply()
        self.assertNotIn('stop', self.system.calls)
    def test_drift_refused(self):
        (self.root/'app.py').write_text('# drift\n')
        with self.assertRaises(remote.Refused): self.apply()
        self.assertFalse((self.root/'backups').exists())
    def test_historical_baseline_required_and_verified(self):
        (self.root/'release.json').unlink()
        with self.assertRaises(remote.Refused): self.apply()
        self.apply(baseline=self.initial['manifest']['files'])
    def test_new_files_require_explicit_absent_baseline(self):
        b = bundle(names={'app.py': b'pass\n', 'static/app.js': b'//next\n', 'new_runtime.py': b'pass\n'})
        with self.assertRaises(remote.Refused): self.apply(b)
        self.apply(b, {'new_runtime.py': None})
    def test_health_failure_auto_rollback(self):
        self.system.fail_health = True
        with self.assertRaisesRegex(remote.Refused, 'previous files restored'): self.apply()
        self.assertEqual((self.root/'app.py').read_bytes(), b'# original\n')
        self.assertEqual(remote.installed(self.root), self.initial['manifest'])
        self.assertIn('old_health', self.system.calls)
    def test_stop_failure_restores_and_starts(self):
        self.system.fail_stop = True
        with self.assertRaisesRegex(remote.Refused, 'previous files restored'): self.apply()
        self.assertEqual(self.system.calls[-3:], ['start','old_health','status'])
    def test_failed_install_removes_only_new_files(self):
        b = bundle(names={'app.py': b'pass\n', 'static/app.js': b'//next\n', 'new_runtime.py': b'pass\n'})
        self.system.fail_health = True
        with self.assertRaises(remote.Refused): self.apply(b, {'new_runtime.py': None})
        self.assertFalse((self.root/'new_runtime.py').exists())
        self.assertEqual((self.root/'data/sentinel').read_text(), 'do not touch')
    def test_recheck_before_stop_rejects_changed_position(self):
        orig = self.system.status
        def status():
            result = orig()
            if self.system.status_count == 2: self.system.state['elapsed'] = '100'
            return result
        self.system.status = status
        with self.assertRaises(remote.Refused): self.apply()
        self.assertNotIn('stop', self.system.calls)
    def test_rollback_traversal_and_drift(self):
        for backup_id in ('../data', '/tmp/backup', 'deploy-../secret'):
            with self.assertRaises(remote.Refused): remote.rollback(self.root, backup_id, self.system)
        result = self.apply(); (self.root/'app.py').write_text('# changed\n')
        with self.assertRaises(remote.Refused): remote.rollback(self.root, result['backup_id'], self.system)
    def test_corrupt_backup_prevents_rollback(self):
        result = self.apply()
        (self.root/'backups'/result['backup_id']/'code/app.py').write_text('corrupt')
        before = (self.root/'app.py').read_bytes()
        with self.assertRaises(remote.Refused): remote.rollback(self.root, result['backup_id'], self.system)
        self.assertEqual((self.root/'app.py').read_bytes(), before)
    def test_historical_explicit_rollback_removes_marker_and_new_file(self):
        (self.root/'release.json').unlink()
        baseline = dict(self.initial['manifest']['files'], **{'new_runtime.py': None})
        b = bundle(names={'app.py': b'pass\n', 'static/app.js': b'//next\n', 'new_runtime.py': b'pass\n'})
        result = self.apply(b, baseline)
        restored = remote.dispatch({'action': 'rollback', 'backup_id': result['backup_id']}, self.system, self.root)
        self.assertTrue(restored['historical'])
        self.assertFalse((self.root/'release.json').exists())
        self.assertFalse((self.root/'new_runtime.py').exists())
        self.assertEqual((self.root/'app.py').read_bytes(), b'# original\n')
    def test_historical_rollback_safety_backup_can_restore_newer_release(self):
        (self.root/'release.json').unlink()
        result=self.apply(baseline=self.initial['manifest']['files'])
        historical=remote.dispatch({'action':'rollback','backup_id':result['backup_id']},self.system,self.root)
        self.assertIsNone(remote.installed(self.root))
        remote.dispatch({'action':'rollback','backup_id':historical['backup_id']},self.system,self.root)
        self.assertEqual(remote.installed(self.root),bundle()['manifest'])

    def test_wrong_service_identity_refused_before_backup_or_stop(self):
        self.system.verify_identity=lambda root: (_ for _ in ()).throw(remote.Refused('wrong instance'))
        with self.assertRaises(remote.Refused):self.apply()
        self.assertNotIn('stop',self.system.calls);self.assertFalse((self.root/'backups').exists())

    def test_atomic_install_failure_restores_original(self):
        original_write = remote.atomic_write
        failed = False
        def write(path, data, mode):
            nonlocal failed
            if path == self.root/'static/app.js' and not failed:
                failed = True
                raise OSError('simulated storage failure')
            return original_write(path, data, mode)
        with patch.object(remote, 'atomic_write', side_effect=write):
            with self.assertRaisesRegex(remote.Refused, 'previous files restored'): self.apply()
        self.assertEqual((self.root/'app.py').read_bytes(), b'# original\n')
    def test_backup_corruption_prevents_any_restore_delete(self):
        result = self.apply()
        backup = self.root/'backups'/result['backup_id']
        info = json.loads((backup/'backup.json').read_text())
        info['previous']['new_runtime.py'] = None
        (self.root/'new_runtime.py').write_text('keep')
        (backup/'code/static/app.js').write_text('corrupt')
        with self.assertRaises(remote.Refused): remote.restore(self.root, backup, info)
        self.assertTrue((self.root/'new_runtime.py').exists())
        self.assertEqual((self.root/'app.py').read_bytes(), b'pass\n')
    def test_auto_rollback_failure_reports_backup_id(self):
        self.system.fail_health = True
        with patch.object(remote, 'restore', side_effect=OSError('fake backup failure')):
            with self.assertRaisesRegex(remote.Refused, 'automatic rollback failed.*deploy-'): self.apply()
    def test_backup_parent_symlink_refused(self):
        (self.root/'backups').symlink_to(self.root/'data', target_is_directory=True)
        with self.assertRaises(remote.Refused): self.apply()
        self.assertNotIn('stop', self.system.calls)
    def test_mode_drift_refused(self):
        (self.root/'app.py').chmod(0o755)
        with self.assertRaises(remote.Refused): self.apply()
    def test_removed_runtime_files_refused(self):
        with self.assertRaises(remote.Refused): self.apply(bundle(names={'app.py': b'pass\n'}))
    def test_symlink_destination_and_lock(self):
        (self.root/'app.py').unlink(); (self.root/'app.py').symlink_to(self.root/'data/sentinel')
        with self.assertRaises(remote.Refused): self.apply()
        (self.root/'.deployment.lock').unlink(); (self.root/'.deployment.lock').symlink_to(self.root/'data/sentinel')
        with self.assertRaises(remote.Refused): self.apply()
    def test_inspect_read_only(self):
        before = set(self.root.rglob('*'))
        result = remote.dispatch({'action':'inspect'}, self.system, self.root)
        self.assertTrue(result['safe']); self.assertEqual(before, set(self.root.rglob('*')))
    def test_inspect_wrong_instance_is_never_reported_safe(self):
        self.system.verify_identity=lambda root: (_ for _ in ()).throw(remote.Refused('wrong service'))
        result=remote.dispatch({'action':'inspect'},self.system,self.root)
        self.assertFalse(result['safe']);self.assertFalse(result['identity_matches'])
        self.assertFalse((self.root/'.deployment.lock').exists())

    def test_lock_excludes_second_deployer(self):
        import fcntl
        with (self.root/'.deployment.lock').open('w') as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(remote.Refused, 'Another deployment'): self.apply()


class Payload(unittest.TestCase):
    def test_traversal_and_secret_paths(self):
        for name in ('../app.py', '/app.py', 'static/../data/token.js', 'data/a.py', '.ssh/key.py',
                     'vendor/a.py', 'backups/a.py', 'static/.env.js', 'static//a.js', 'a\\b.py',
                     'deploy/systemd/app.service', 'static/a.wav', 'tools/pi-ssh', 'release.json'):
            with self.subTest(name=name):
                self.assertFalse(remote.allowed(name))
                with self.assertRaises(remote.Refused): remote.validate_bundle(bundle(names={'app.py':b'pass', name:b'x'}))
    def test_payload_tampering(self):
        b = bundle(); b['content']['app.py'] = base64.b64encode(b'bad').decode()
        with self.assertRaises(remote.Refused): remote.validate_bundle(b)
        b = bundle(); b['manifest']['files']['app.py']['mode'] = 0o777
        with self.assertRaises(remote.Refused): remote.validate_bundle(b)
    def test_manifest_invalid_schema_commit_timestamp_and_syntax(self):
        for key, value in [('schema',2), ('commit','bad'), ('built_at','bad'), ('component','vps')]:
            b = bundle(); b['manifest'][key] = value
            with self.assertRaises(remote.Refused): remote.validate_bundle(b)
        with self.assertRaises(SyntaxError): remote.validate_bundle(bundle(names={'app.py': b'not python !!!'}))
    def test_remote_failure_only_exposes_safe_backup_id(self):
        response = subprocess.CompletedProcess([], 1, b'{"ok":false,"error":"private-secret. Backup ID: deploy-safe123"}', b'private-secret')
        with patch.object(local.subprocess, 'run', return_value=response):
            with self.assertRaises(local.Refused) as caught:
                local.remote(TOOLS.parent, {'action': 'apply'})
        self.assertIn('deploy-safe123', str(caught.exception))
        self.assertNotIn('private-secret', str(caught.exception))
    def test_all_new_root_modules_allowed(self):
        for name in ('runtime_settings.py','optical_disc.py','release_info.py','player_server.py'):
            self.assertTrue(remote.allowed(name))
    def test_local_git_payload_and_clean_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args): return subprocess.check_output(['git','-C',tmp,*args], stderr=subprocess.DEVNULL)
            git('init','-q'); git('config','user.name','Test'); git('config','user.email','test@example.invalid')
            (root/'app.py').write_text('pass\n'); (root/'data').mkdir(); (root/'data/token').write_text('dummy')
            (root/'.gitignore').write_text('data/\n')
            git('add','.'); git('commit','-qm','fixture')
            b, _ = local.build(root)
            self.assertEqual(set(b['content']), {'app.py'})
            self.assertEqual(b['manifest']['commit'], git('rev-parse','HEAD').decode().strip())
            (root/'app.py').write_text('changed')
            with self.assertRaises(local.Refused): local.build(root)
    def test_cli_default_and_dry_run_never_ssh(self):
        with patch.object(local, 'build', return_value=(bundle(), None)), patch.object(local, 'remote') as ssh, patch('builtins.print'):
            self.assertEqual(local.main([]), 0)
            self.assertEqual(local.main(['apply','--dry-run']), 0)
            self.assertEqual(local.main(['rollback','--backup-id','deploy-test']), 0)
            ssh.assert_not_called()
    def test_transport_no_input_interpolation_or_stderr(self):
        response = subprocess.CompletedProcess([], 0, b'{"ok":true}', b'private')
        with patch.object(local.subprocess, 'run', return_value=response) as run:
            self.assertTrue(local.remote(TOOLS.parent, {'backup_id': '$(touch bad)'})['ok'])
            args, kwargs = run.call_args
            self.assertNotIn('$(touch bad)', args[0][1]); self.assertIn(b'$(touch bad)', kwargs['input'])
            self.assertEqual(kwargs['timeout'], 240)


if __name__ == '__main__':
    unittest.main()

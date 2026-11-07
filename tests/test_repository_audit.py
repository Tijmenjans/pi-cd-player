"""Synthetic credentials only; isolated temporary Git indexes, no live access."""
import contextlib
import importlib.util
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import check_repository as audit


class BlobAuditTests(unittest.TestCase):
    def test_private_paths(self):
        for name in ('data/status.json', '.ssh/arbitrary-name', 'backups/file.txt',
                     'vendor/lib/file', '.venv-vinyl/bin/python', 'music/track.flac',
                     'nested/.env.local', 'release.json', 'archive.json',
                     'Plex/Preferences.xml', 'node_modules/package/file', 'recording.vob'):
            with self.subTest(name=name):
                self.assertIn('excluded file category', audit.audit_blob(name, b'{}'))

    def test_safe_paths_and_examples(self):
        for name in ('tools/release_info.py', 'tools/pi-ssh', 'docs/access.md',
                     'config/examples/archive.example.json', 'archive-server/.env.example',
                     'config/examples/release.example.json', 'static/christmas-fire.jpg'):
            self.assertEqual(audit.audit_blob(name, b'{"token":"replace-me"}'), [])
        self.assertTrue(audit.path_is_private('elsewhere/archive.example.json'))

    def test_credentials_even_in_example(self):
        samples = [b'-----BEGIN ' + kind + b'PRIVATE KEY-----' for kind in
                   (b'', b'OPENSSH ', b'RSA ', b'EC ', b'DSA ', b'ENCRYPTED ')]
        samples += [b'gh' + b'p_' + b'A' * 36, b'github_' + b'pat_' + b'A' * 40,
                    b'AK' + b'IA' + b'A' * 16,
                    b'{"token":"' + b'z' * 32 + b'"}']
        for data in samples:
            self.assertIn('possible credential', audit.audit_blob('config/examples/archive.example.json', data))

    def test_size_and_binary(self):
        self.assertIn('larger than 2 MiB', audit.audit_blob('large.txt', b'x' * (audit.MAX_BYTES + 1)))
        self.assertIn('executable binary', audit.audit_blob('tool', b'\x7fELFsynthetic'))
        self.assertEqual(audit.audit_blob('normal.py', b'print("hello")'), [])

    def test_import_has_no_git_or_exit_side_effect(self):
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location('isolated_audit', audit.__file__)
        module = importlib.util.module_from_spec(spec)
        with patch('subprocess.check_output', side_effect=AssertionError('Git during import')):
            spec.loader.exec_module(module)


class IndexAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.DEVNULL)

    def stage(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.git('add', '--', name)

    def commit(self):
        self.git('-c', 'user.name=Offline Test', '-c', 'user.email=test@example.invalid',
                 '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture')

    def test_clean_index_still_scanned(self):
        self.stage('innocent.txt', b'-----BEGIN ' + b'OPENSSH PRIVATE KEY-----')
        self.commit()
        self.assertEqual(audit.audit_repository(self.root), (0, []))
        count, findings = audit.audit_repository(self.root, tracked=True)
        self.assertEqual(count, 1)
        self.assertEqual(findings, [('innocent.txt', 'possible credential')])

    def test_index_not_worktree_and_new_staged_files(self):
        self.stage('safe.txt', b'safe')
        (self.root / 'safe.txt').write_bytes(b'-----BEGIN ' + b'RSA PRIVATE KEY-----')
        self.assertEqual(audit.audit_repository(self.root, tracked=True), (1, []))
        self.stage('another name.txt', b'-----BEGIN ' + b'EC PRIVATE KEY-----')
        (self.root / 'another name.txt').write_bytes(b'safe now')
        self.assertEqual(audit.audit_repository(self.root)[1], [('another name.txt', 'possible credential')])

    def test_deletion_not_scanned(self):
        self.stage('safe.txt', b'safe')
        self.commit()
        self.git('rm', '-q', 'safe.txt')
        self.assertEqual(audit.audit_repository(self.root, tracked=True), (0, []))
        self.assertEqual(audit.audit_repository(self.root), (0, []))

    def test_cli_never_prints_blob_contents(self):
        from unittest.mock import patch
        secret = b'gh' + b'p_' + b'Z' * 36
        self.stage('odd\nname.txt', secret)
        output = io.StringIO()
        original = audit.audit_repository
        with patch.object(audit, 'audit_repository', side_effect=lambda **kw: original(self.root, **kw)):
            with contextlib.redirect_stdout(output):
                self.assertEqual(audit.main(['--tracked']), 1)
        self.assertNotIn(secret.decode(), output.getvalue())
        self.assertIn('odd\\nname.txt', output.getvalue())


if __name__ == '__main__':
    unittest.main()

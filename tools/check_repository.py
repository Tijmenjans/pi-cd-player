"""Audit Git index blobs without printing their contents. Import has no side effects."""
import argparse
import json
import re
import subprocess
from pathlib import PurePosixPath

MAX_BYTES = 2 * 1024 * 1024
PATTERNS = (
    re.compile(rb'-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----'),
    re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16})\b'),
    re.compile(rb'''(?i)["']?(?:token|password|secret|api_key|ARCHIVE_TOKEN|SOLOIST_API_KEY|X-Plex-Token)["']?\s*[:=]\s*["'][A-Za-z0-9_+/=-]{24,}["']'''),
)


def path_is_private(name):
    """Only narrow example exceptions; these still undergo content inspection."""
    path = PurePosixPath(name)
    parts = [p.lower() for p in path.parts]
    base = parts[-1]
    if any(p in {'data', 'vendor', 'backups', '.ssh', '__pycache__', 'node_modules',
                  'music', 'logs', 'credentials', '.aws', '.venv', 'venv'}
           or p.startswith('.venv-') for p in parts):
        return True
    if base in {'archive.example.json', 'release.example.json'}:
        return name not in {'config/examples/archive.example.json', 'config/examples/release.example.json'}
    if base == '.env.example':
        return name != 'archive-server/.env.example'
    return (base in {'archive.json', 'release.json', 'soloist.env', 'preferences.json',
                     'preferences.xml', '.env', 'credentials.json', 'secrets.json'}
            or base.startswith('.env.') or base.startswith('id_')
            or path.suffix.lower() in {'.wav', '.flac', '.mkv', '.vob', '.mp3', '.mp4',
                                      '.pem', '.key', '.p12', '.pfx', '.log', '.deb',
                                      '.gz', '.zip', '.tar', '.7z', '.pyc', '.so', '.dylib', '.exe'})


def audit_blob(name, data):
    """Return reasons only; never return matching credential values."""
    reasons = []
    if path_is_private(name):
        reasons.append('excluded file category')
    if len(data) > MAX_BYTES:
        reasons.append('larger than 2 MiB')
    if any(pattern.search(data) for pattern in PATTERNS):
        reasons.append('possible credential')
    if data.startswith((b'\x7fELF', b'MZ', b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf')):
        reasons.append('executable binary')
    return reasons


def git_bytes(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL)


def audit_repository(root='.', tracked=False):
    """Read names and contents from index, including new staged files, not worktree."""
    if tracked:
        raw = git_bytes(root, 'ls-files', '--cached', '-z')
    else:
        raw = git_bytes(root, 'diff', '--cached', '--name-only', '--diff-filter=ACMRT', '-z')
    names = sorted(set(n for n in raw.split(b'\0') if n))
    findings = []
    for raw_name in names:
        name = raw_name.decode('utf-8', errors='surrogateescape')
        try:
            data = git_bytes(root, 'show', ':' + name)
        except subprocess.CalledProcessError:
            findings.append((name, 'cannot read index blob (unmerged or non-blob entry)'))
            continue
        findings.extend((name, reason) for reason in audit_blob(name, data))
    return len(names), findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--staged', action='store_true', help='changed index blobs (default)')
    modes.add_argument('--tracked', action='store_true', help='all index blobs, also in clean CI checkout')
    args = parser.parse_args(argv)
    try:
        count, findings = audit_repository(tracked=args.tracked)
    except subprocess.CalledProcessError:
        print('Repository audit failed: cannot read Git index.')
        return 2
    for name, reason in findings:
        print(f'{json.dumps(name, ensure_ascii=True)}: {reason}')
    print(f'Checked {count} index files; {len(findings)} findings. Pattern scan requires manual review.')
    return int(bool(findings))


if __name__ == '__main__':
    raise SystemExit(main())

"""Build immutable Pi payloads from Git; SSH transport is a separate explicit step."""
import argparse
import base64
import datetime
import json
import re
from pathlib import Path
import shlex
import subprocess
import sys

# Support both direct script execution and import by unittest discovery.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_remote import (MAX_BYTES, Refused, allowed, digest, manifest_valid,
                           require, validate_bundle)

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL = '70eb61f3eb78510ca9c161799fd7c97883033776'


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], timeout=30,
                                   stderr=subprocess.DEVNULL)


def tree(root, commit):
    entries = {}
    for row in git(root, 'ls-tree', '-rz', commit).split(b'\0'):
        if not row:
            continue
        meta, raw_name = row.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        name = raw_name.decode('utf-8')
        if allowed(name):
            require(kind == 'blob' and mode in ('100644', '100755'), 'Symlink/nonregular payload entry')
            data = git(root, 'cat-file', 'blob', oid)
            entries[name] = (data, int(mode, 8) & 0o777)
    return entries


def clean_commit(root, revision):
    require(not git(root, 'status', '--porcelain', '--untracked-files=normal').strip(),
            'Working tree must be clean, including untracked files')
    commit = git(root, 'rev-parse', '--verify', revision + '^{commit}').decode().strip()
    require(len(commit) == 40 and all(c in '0123456789abcdef' for c in commit), 'Invalid commit')
    return commit


def build(root, revision='HEAD', baseline=None):
    commit = clean_commit(root, revision)
    entries = tree(root, commit)
    require(sum(len(data) for data, _ in entries.values()) <= MAX_BYTES, 'Payload too large')
    manifest = {'schema': 1, 'commit': commit,
                'built_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'component': 'pi-player',
                'files': {name: {'sha256': digest(data), 'mode': mode}
                          for name, (data, mode) in sorted(entries.items())}}
    bundle = {'manifest': manifest,
              'content': {name: base64.b64encode(data).decode('ascii')
                          for name, (data, _) in entries.items()}}
    validate_bundle(bundle)
    previous = None
    if baseline:
        baseline_commit = git(root, 'rev-parse', '--verify', baseline + '^{commit}').decode().strip()
        base = tree(root, baseline_commit)
        previous = {name: ({'sha256': digest(base[name][0]), 'mode': base[name][1]} if name in base else None)
                    for name in set(base) | set(entries)}
    return bundle, previous


def remote(root, request):
    # The remote command consists exclusively of reviewed code; all user input
    # travels through stdin JSON. Never interpolate paths/IDs into shell code.
    code = git(root, 'show', request.get('bundle',{}).get('manifest',{}).get('commit','HEAD') + ':tools/deploy_remote.py').decode()
    command = 'python3 -c ' + shlex.quote(code)
    try:
        result = subprocess.run([str(root / 'tools' / 'pi-ssh'), command],
                                input=json.dumps(request).encode(), capture_output=True,
                                timeout=240, check=False)
    except subprocess.TimeoutExpired:
        raise Refused('SSH timed out; transaction may still run. Inspect Pi before retrying') from None
    # Never relay SSH stderr or arbitrary remote output: it may contain secrets.
    try:
        answer = json.loads(result.stdout)
        if not isinstance(answer, dict) or answer.get('ok') is not True or result.returncode != 0:
            backup = re.search(r'backup ID: (deploy-[A-Za-z0-9_-]+)', str(answer.get('error', '')) if isinstance(answer, dict) else '', re.IGNORECASE)
            suffix = (' Safety backup ID: ' + backup.group(1)) if backup else ''
            raise Refused('Remote operation refused/failed; inspect state before retrying.' + suffix)
    except (ValueError, TypeError):
        raise Refused('Invalid remote response; inspect state before retrying') from None
    return answer


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', choices=('plan', 'apply', 'rollback', 'inspect'), default='plan')
    parser.add_argument('--root',default='/home/tijmen/cdspeler',help='Explicit remote installation root')
    parser.add_argument('--commit', default='HEAD', help='Git commit/tag to package')
    parser.add_argument('--baseline-commit', help='Explicit reviewed installed baseline; first Pi installation: ' + HISTORICAL)
    parser.add_argument('--apply', action='store_true', help='Permit remote writes (apply or rollback only)')
    parser.add_argument('--backup-id', help='Exact private backup ID for rollback')
    parser.add_argument('--dry-run', action='store_true', help='Local read-only plan, never remote writes')
    args = parser.parse_args(argv)
    try:
        require(not (args.apply and args.dry_run), 'Choose --apply or --dry-run')
        require(not args.apply or args.command in ('apply', 'rollback'), '--apply needs apply/rollback command')
        if args.command == 'inspect':
            require(not args.dry_run, 'Use plan for an offline dry run')
            print(json.dumps(remote(ROOT, {'action': 'inspect','root':args.root}), indent=2)); return 0
        if args.command == 'rollback':
            require(args.backup_id is not None, 'Rollback requires --backup-id')
            if not args.apply:
                print(json.dumps({'action': 'rollback', 'backup_id': args.backup_id,
                                  'remote_writes': False, 'note': 'Use --apply to execute; backup not inspected'})); return 0
            print(json.dumps(remote(ROOT, {'action': 'rollback', 'backup_id': args.backup_id,'root':args.root}), indent=2)); return 0
        require(args.backup_id is None, '--backup-id is only for rollback')
        bundle, baseline = build(ROOT, args.commit, args.baseline_commit)
        if args.command == 'apply' and args.apply:
            result = remote(ROOT, {'action': 'apply', 'bundle': bundle, 'baseline': baseline,'root':args.root})
        else:
            result = {'action': 'plan', 'remote_writes': False, 'remote_contact': False,
                      'root':args.root,'manifest': bundle['manifest'], 'baseline_provided': baseline is not None,
                      'expected_files': baseline}
        print(json.dumps(result, indent=2)); return 0
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (subprocess.CalledProcessError, OSError, ValueError):
        print('Deployment refused/failed. Check clean commit, reviewed baseline, safe player state and private backup.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

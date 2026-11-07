"""Create/verify a private off-project backup, without displaying secret contents."""
import argparse
import hashlib
import json
from pathlib import Path,PurePosixPath
import tarfile

ROOT=Path(__file__).resolve().parents[1]

def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def safe_name(name):
    path=PurePosixPath(name)
    return not path.is_absolute() and bool(path.parts) and '..' not in path.parts and path.parts[0] in ('.ssh','backups')

def verify(folder):
    folder=Path(folder);manifest=json.loads((folder/'manifest.json').read_text())
    archive=folder/'private.tar.gz'
    if manifest.get('schema')!=1 or digest(archive)!=manifest.get('archive_sha256'):raise ValueError('Backupchecksum klopt niet')
    expected=manifest['files'];seen=set()
    with tarfile.open(archive,'r:gz') as tar:
        for member in tar:
            name=member.name
            if not safe_name(name) or name in seen or not member.isfile() or name not in expected:raise ValueError('Ongeldig archieflid')
            with tar.extractfile(member) as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
            if actual!=expected[name]['sha256'] or member.size!=expected[name]['bytes']:raise ValueError('Bestandscontrole mislukt')
            seen.add(name)
    if seen!=set(expected):raise ValueError('Backup is onvolledig')
    return len(seen)

def create(destination,root=ROOT):
    root=Path(root).resolve();destination=Path(destination).resolve()
    if destination==root or root in destination.parents:raise ValueError('Kies een backupbestemming buiten het project')
    paths=[]
    for name in ('.ssh','backups'):
        base=root/name
        if base.is_symlink():raise ValueError('Private bronmap mag geen symlink zijn')
        if not base.exists():continue
        for path in sorted(base.rglob('*')):
            if path.is_symlink():raise ValueError('Symlinks in private backup eerst expliciet beoordelen')
            if path.is_file():paths.append(path)
    if not paths:raise ValueError('Geen private projectbestanden gevonden')
    destination.mkdir(mode=0o700,parents=True,exist_ok=False)
    expected={str(path.relative_to(root)):{'sha256':digest(path),'bytes':path.stat().st_size} for path in paths}
    archive=destination/'private.tar.gz'
    archive.touch(mode=0o600,exist_ok=False)
    with tarfile.open(archive,'w:gz') as tar:
        for path in paths:tar.add(path,arcname=str(path.relative_to(root)),recursive=False)
    manifest={'schema':1,'archive_sha256':digest(archive),'files':expected}
    path=destination/'manifest.json';path.touch(mode=0o600,exist_ok=False);path.write_text(json.dumps(manifest,indent=2)+'\n')
    verify(destination)
    return len(paths)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['create','verify'])
    parser.add_argument('destination',type=Path)
    args=parser.parse_args(argv)
    count=create(args.destination) if args.action=='create' else verify(args.destination)
    print(f'Private backup geverifieerd: {count} bestanden. Geen inhoud afgedrukt.')

if __name__=='__main__':main()

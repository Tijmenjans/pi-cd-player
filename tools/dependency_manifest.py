"""Inventory explicitly selected third-party binaries, without config or secrets.

Run manually on a quiescent Pi. Does not install, probe hardware or start services.
The resulting private backup manifest should be reviewed before sharing.
"""
import argparse
import hashlib
import json
import platform
import subprocess
from pathlib import Path


def manifest(root,caldera=None):
    root=Path(root).resolve();files=[]
    bases=[root/'vendor/dvd/usr',root/'vendor/ripping/usr',root/'vendor/soloist',root/'vendor/caldera-audio/usr']
    if caldera:bases.extend([Path(caldera).resolve()/'bin',Path(caldera).resolve()/'lib'])
    for base in bases:
        if not base.is_dir():continue
        for path in sorted(base.rglob('*')):
            # Hash only executable/library assets. Never traverse private configs.
            if path.is_symlink() or not path.is_file():continue
            if not (path.stat().st_mode & 0o111 or '.so' in path.name):continue
            if any(part.startswith('.') for part in path.relative_to(base).parts):continue
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            files.append({'base':str(base),'file':str(path.relative_to(base)),'bytes':path.stat().st_size,'sha256':digest})
    packages='unavailable'
    try:
        result=subprocess.run(['dpkg-query','-W','-f=${Package}\t${Version}\n','python3-flask','python3-libdiscid','python3-websocket','mpd','pipewire','bluez','wireplumber','sg3-utils','eject'],capture_output=True,text=True,timeout=10)
        packages=result.stdout
    except (OSError,subprocess.TimeoutExpired):pass
    return {'architecture':platform.machine(),'system':platform.system(),'packages':packages,'binaries':files,
            'provenance_required':'Record package download URLs/versions and source-build options in the reviewed backup manifest; hashes alone are not a rebuild recipe.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--caldera',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    with args.output.open('x') as stream:json.dump(manifest(args.root,args.caldera),stream,indent=2);stream.write('\n')

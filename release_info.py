"""Public, non-secret release identification; no Git or hardware calls at runtime."""
from datetime import datetime
import json
from pathlib import Path
import re


def read_release(root,component='pi-player'):
    unknown={'schema':1,'component':component,'commit':None,'built_at':None,'installed':False}
    path=Path(root)/'release.json'
    try:
        if path.is_symlink() or path.stat().st_size>256_000:return unknown
        row=json.loads(path.read_text())
        if not isinstance(row,dict) or row.get('schema')!=1 or row.get('component')!=component:return unknown
        if not isinstance(row.get('commit'),str) or not re.fullmatch(r'[0-9a-f]{40}',row['commit']):return unknown
        built=row.get('built_at')
        if not isinstance(built,str) or len(built)>40:return unknown
        if datetime.fromisoformat(built.replace('Z','+00:00')).tzinfo is None:return unknown
        return dict(unknown,commit=row['commit'],built_at=built,installed=True)
    except (OSError,ValueError,TypeError):return unknown

"""Offline suite; libdiscid is deliberately simulated, never reads a drive."""
import shutil
import tempfile
import os
import json
import sys
import types
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sandbox = tempfile.TemporaryDirectory(prefix='cdspeler-tests-')
ORIGINAL = ROOT
ROOT = Path(sandbox.name)
for source in ORIGINAL.glob('*.py'):
    shutil.copy2(source, ROOT/source.name)
for name in ('tests', 'static', 'catalogue'):
    shutil.copytree(ORIGINAL/name, ROOT/name)
(ROOT/'data').mkdir()
(ROOT/'data/archive.json').write_text(json.dumps({'url':'https://archive.example.invalid','token':'offline-test','rip_speed':4}))
os.chdir(ROOT)
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
class DiscError(Exception):
    pass
def no_drive(*args, **kwargs):
    raise DiscError('Optical hardware disabled in offline tests')
sys.modules['libdiscid'] = types.SimpleNamespace(DiscError=DiscError, FEATURE_READ=1, read=no_drive)
import app
app.optical_device = lambda: '/dev/offline-test'
suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())

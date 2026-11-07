"""Standard unittest bootstrap: isolated state, explicit disabled optical backend."""
import atexit
import json
import os
from pathlib import Path
import sys
import tempfile

_workspace=tempfile.TemporaryDirectory(prefix='cdspeler-tests-')
atexit.register(_workspace.cleanup)
_test_root=Path(_workspace.name)
(_test_root/'data').mkdir()
(_test_root/'data/archive.json').write_text(json.dumps({'url':'https://archive.example.invalid','token':'offline-test','rip_speed':4}))
os.environ['CDSPELER_ROOT']=str(_test_root)
os.environ.pop('CDSPELER_CONFIG',None)
# Existing isolated tests import sibling helpers; no replacement modules in sys.modules.
sys.path.insert(0,str(Path(__file__).resolve().parent))
import optical_disc
optical_disc.configure_backend(disabled=True)

import optical_device
optical_device.configure_device_provider(lambda:'/dev/offline-test')

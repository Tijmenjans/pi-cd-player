"""Conservative staged-content audit; reports paths only, never secret values."""
import re
import subprocess
import sys
from pathlib import Path
names = subprocess.check_output(['git','diff','--cached','--name-only','--diff-filter=ACMR','-z']).decode().split('\0')
if not any(names):
    raise SystemExit('No staged files: nothing audited')
failures=[]
patterns=[
 re.compile(rb'-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----'),
 re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16})\b'),
 re.compile(rb'(?i)["\']?(?:token|password|secret|api_key|ARCHIVE_TOKEN|SOLOIST_API_KEY)["\']?\s*[:=]\s*["\'][A-Za-z0-9_+/=-]{24,}["\']'),
]
for name in filter(None,names):
 p=Path(name)
 if any(part in {'data','vendor','backups','.ssh','__pycache__'} or part.startswith('.venv') for part in p.parts) or p.suffix.lower() in {'.wav','.flac','.mkv','.vob','.pem','.key','.log','.deb','.gz','.zip'} or p.name in {'.env','archive.json','soloist.env','preferences.json'}:
  failures.append((name,'excluded file category'))
 data=subprocess.check_output(['git','show',':'+name])
 if len(data)>2*1024*1024:failures.append((name,'larger than 2 MiB'))
 if any(pattern.search(data) for pattern in patterns):failures.append((name,'possible credential'))
for name,reason in failures:print(f'{name}: {reason}')
print(f'Checked {len(list(filter(None,names)))} staged files; {len(failures)} findings. Pattern scan does not replace manual review.')
sys.exit(bool(failures))

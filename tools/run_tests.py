"""Standard isolated unittest; --runtime-only omits Git-dependent tooling tests."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-only',action='store_true',help='Pi staging profile without Git-dependent developer-tool tests')
    args=parser.parse_args(argv)
    if args.runtime_only:
        omitted={'test_deployment','test_repository_audit'}
        modules=['tests.'+p.stem for p in sorted((ROOT/'tests').glob('test_*.py')) if p.stem not in omitted]
        command=[sys.executable,'-m','unittest','-v',*modules]
    else:command=[sys.executable,'-m','unittest','discover','-s','tests','-t','.', '-v']
    return subprocess.call(command,cwd=ROOT)

if __name__=='__main__':raise SystemExit(main())

"""Run standard, isolated unittest discovery. Integration tests are opt-in."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    raise SystemExit(subprocess.call([sys.executable,'-m','unittest','discover','-s','tests','-t','.', '-v'],cwd=ROOT))

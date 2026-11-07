"""Review an environment setup; downloads/writes require explicit --install."""
import argparse
from pathlib import Path
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def commands(profile,root=ROOT,python=sys.executable):
    if profile=='test':
        venv=root/'.venv'
        return [[python,'-m','venv',str(venv)],
                [str(venv/'bin/python'),'-m','pip','install','-r',str(root/'requirements-test.lock')]]
    if profile=='pi':
        venv=root/'.venv-player'
        return [[python,'-c','import flask,libdiscid,websocket'],
                [python,'-m','venv','--system-site-packages',str(venv)],
                [str(venv/'bin/python'),'-m','pip','install','-r',str(root/'requirements.txt'),'-r',str(root/'requirements-server.txt')]]
    raise ValueError('Onbekend installatieprofiel')

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',choices=['test','pi'],default='test')
    parser.add_argument('--install',action='store_true')
    args=parser.parse_args(argv)
    for command in commands(args.profile):
        print(shlex.join(command),flush=True)
        if args.install:subprocess.run(command,cwd=ROOT,check=True)
    if not args.install:print('Alleen plan; gebruik --install om de omgeving daadwerkelijk aan te maken.')

if __name__=='__main__':main()

"""Validate settings and render reviewable units. Never installs or restarts them."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime_settings import Settings


def render(settings,templates,*,python='/usr/bin/python3',production=False,home=None):
    root=str(settings.install_root)
    home=str(home or settings.install_root.parent)
    # systemd expands percent and dollar; keep generated command paths simple.
    for value in (root,home,str(python)):
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+',value) or '..' in Path(value).parts:
            raise ValueError('Gebruik absolute installatiepaden zonder spaties of uitbreidingen')
    result={}
    for path in sorted(Path(templates).glob('*.service')):
        if '@' in path.name:continue  # System wake unit is never a user-unit proposal.
        text=path.read_text().replace('/home/tijmen/cdspeler',root).replace('%h/cdspeler',root)
        text=text.replace('/home/tijmen',home).replace('%h/caldera-music',home+'/caldera-music').replace('%h/.config',home+'/.config')
        text=text.replace('/usr/bin/python3',str(python))
        if path.name=='cdspeler-web.service' and production:text=text.replace(root+'/app.py',root+'/player_server.py')
        # All Python helpers consume the same root/configuration.
        if '[Service]' in text:
            text=text.replace('[Service]','[Service]\nEnvironment=CDSPELER_ROOT='+root,1)
        result[path.name]=text
    for path in sorted(Path(templates).glob('*.timer')):result[path.name]=path.read_text()
    config_dir=Path(templates).parent/'config'
    text=(config_dir/'mpd.conf').read_text().replace('/home/tijmen/cdspeler',root)
    text=text.replace('port "6601"',f'port "{settings.mpd_port}"')
    text=text.replace('bind_to_address "127.0.0.1"',f'bind_to_address "{settings.mpd_host}"')
    result['mpd.conf']=text
    result['caldera-alsa.conf']=(config_dir/'caldera-alsa.conf').read_text()
    result['stop-timeout.conf']=(Path(templates)/'cdspeler-web-stop-timeout.conf').read_text()
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--python',default='/usr/bin/python3')
    parser.add_argument('--home',type=Path)
    parser.add_argument('--production',action='store_true')
    args=parser.parse_args(argv)
    settings=Settings.load(environ={'CDSPELER_ROOT':str(args.root),'CDSPELER_CONFIG':str(args.config)})
    outputs=render(settings,Path(__file__).resolve().parents[1]/'deploy/systemd',python=args.python,production=args.production,home=args.home)
    # A fresh output directory avoids overwriting previous or installed settings.
    args.output.mkdir(mode=0o700,parents=True,exist_ok=False)
    for name,text in outputs.items():(args.output/name).write_text(text)
    data=asdict(settings);data.pop('install_root')
    (args.output/'installation.json').write_text(json.dumps(data,indent=2)+'\n')
    print('Configuratie gevalideerd; '+str(len(outputs))+' unitvoorstellen geschreven. Niets geïnstalleerd of herstart.')

if __name__=='__main__':main()

"""Discover the connected optical drive rather than assuming /dev/sr0."""
import os
from pathlib import Path

class OpticalDeviceError(RuntimeError):pass

def optical_device(dev_root=Path('/dev'),sys_root=Path('/sys/class/block')):
    candidates=[]
    for node in sorted(Path(sys_root).glob('sr[0-9]*')):
        device=node/'device'
        try:
            if (device/'type').read_text().strip()!='5':continue
            if (device/'state').read_text().strip()!='running':continue
            model=(device/'model').read_text().strip().lower()
            path=Path(dev_root)/node.name
            if path.exists():candidates.append((model,path))
        except OSError:continue
    preferred=[path for model,path in candidates if 'superdrive' in model]
    paths=preferred or [path for _,path in candidates]
    if not paths:raise OpticalDeviceError('Geen aangesloten cd/dvd-drive gevonden.')
    if len(paths)!=1:raise OpticalDeviceError('Meerdere cd/dvd-drives gevonden; sluit één drive aan.')
    path=paths[0]
    if not os.access(path,os.R_OK|os.W_OK):
        raise OpticalDeviceError('De drive is aangesloten, maar Linux heeft de toegangsrechten nog niet vrijgegeven. De SuperDrive-systeemregel moet worden hersteld.')
    return str(path)

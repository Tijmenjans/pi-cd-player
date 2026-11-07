from optical_device import optical_device, OpticalDeviceError
"""Read-only CD-Text/track probe, scheduled before playback; never executes CD files."""
import copy
import ctypes as C
import ctypes.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path


VERSION=1


def cdio_library():
    name=ctypes.util.find_library('cdio')
    if not name:raise OSError('CD-Text-bibliotheek ontbreekt')
    return C.CDLL(name)


def decode_cdtext(raw,last_track):
    if len(raw)==4:return {'status':'absent','album':{},'tracks':{}}
    lib=cdio_library()
    lib.cdtext_init.argtypes=[];lib.cdtext_init.restype=C.c_void_p
    lib.cdtext_destroy.argtypes=[C.c_void_p];lib.cdtext_destroy.restype=None
    lib.cdtext_data_init.argtypes=[C.c_void_p,C.c_void_p,C.c_size_t];lib.cdtext_data_init.restype=C.c_int
    lib.cdtext_get_const.argtypes=[C.c_void_p,C.c_int,C.c_ubyte];lib.cdtext_get_const.restype=C.c_char_p
    text=lib.cdtext_init()
    if not text:raise OSError('CD-Text kon niet worden ingelezen')
    try:
        packs=C.create_string_buffer(raw[4:])
        if lib.cdtext_data_init(text,packs,len(raw)-4):raise ValueError('Ongeldige CD-Text')
        fields={}
        for number in range(last_track+1):
            values={}
            for key,field in [('title',0),('artist',1)]:
                value=lib.cdtext_get_const(text,field,number)
                if value:
                    value=' '.join(value.decode('utf-8',errors='replace').split())[:512]
                    if value:values[key]=value
            if values:fields[number]=values
        return {'status':'present','album':fields.pop(0,{}),
                'tracks':{str(n):v for n,v in fields.items()}}
    finally:lib.cdtext_destroy(text)


def probe(device=None):
    device=device or optical_device()
    # libcdio uses the drive's normal command timeout. An artificially short
    # SG_IO timeout triggers slow USB recovery on this SuperDrive.
    started=time.monotonic()
    lib=cdio_library()
    lib.cdio_open.argtypes=[C.c_char_p,C.c_int];lib.cdio_open.restype=C.c_void_p
    lib.cdio_destroy.argtypes=[C.c_void_p];lib.cdio_destroy.restype=None
    lib.cdio_get_cdtext_raw.argtypes=[C.c_void_p];lib.cdio_get_cdtext_raw.restype=C.c_void_p
    lib.cdio_free.argtypes=[C.c_void_p];lib.cdio_free.restype=None
    for name in ('cdio_get_first_track_num','cdio_get_last_track_num'):
        fn=getattr(lib,name);fn.argtypes=[C.c_void_p];fn.restype=C.c_ubyte
    lib.cdio_get_track_format.argtypes=[C.c_void_p,C.c_ubyte]
    lib.cdio_get_track_format.restype=C.c_int
    result={'version':VERSION,'cd_text':{'status':'unavailable','album':{},'tracks':{}},
            'toc_status':'unavailable','data_tracks':[]}
    handle=lib.cdio_open(os.fsencode(device),0)
    if not handle:raise OSError('De cd-drive kan niet worden geopend')
    try:
        first=lib.cdio_get_first_track_num(handle);last=lib.cdio_get_last_track_num(handle)
        if not 1<=first<=last<=99:raise ValueError('Ongeldige tracklijst')
        tracks={n:lib.cdio_get_track_format(handle,n) for n in range(first,last+1)}
        if any(fmt not in range(5) for fmt in tracks.values()):raise ValueError('Onleesbare tracksoort')
        result.update(toc_status='read',first_track=first,last_track=last,
                      audio_tracks=[n for n,fmt in tracks.items() if fmt==0],
                      data_tracks=[{'number':n} for n,fmt in tracks.items() if fmt!=0])
        raw=lib.cdio_get_cdtext_raw(handle)
        if raw:
            try:
                size=int.from_bytes(C.string_at(raw,2),'big')+2
                if not 4<=size<=65535:raise ValueError('Ongeldige CD-Text-lengte')
                result['cd_text']=decode_cdtext(C.string_at(raw,size),last)
                result['cd_text']['raw_bytes']=size
            except ValueError:result['cd_text']['status']='unreadable'
            finally:lib.cdio_free(raw)
    finally:lib.cdio_destroy(handle)
    result['cover_files_status']='no_data_track' if not result['data_tracks'] else 'not_examined'
    result['seconds']=round(time.monotonic()-started,3)
    return result


def read_cache(snapshot,directory):
    path=Path(directory)/(snapshot['id']+'-disc-media.json')
    try:
        cached=json.loads(path.read_text())
        if (cached.get('version')==VERSION and cached.get('toc')==snapshot['toc']
                and cached.get('id')==snapshot['id']
                and cached.get('cd_text',{}).get('status') in ('present','absent')
                and cached.get('toc_status')=='read'):
            return cached
    except (OSError,ValueError):pass
    return None


def cached_probe(snapshot,directory,device=None):
    path=Path(directory)/(snapshot['id']+'-disc-media.json')
    cached=read_cache(snapshot,directory)
    if cached:return cached
    try:
        device=device or optical_device()
        run=subprocess.run([sys.executable,str(Path(__file__).resolve()),device],
                           check=True,capture_output=True,text=True,timeout=45)
        result=json.loads(run.stdout)
    except (OSError,ValueError,subprocess.SubprocessError):
        result={'version':VERSION,'cd_text':{'status':'unavailable','album':{},'tracks':{}},
                'toc_status':'unavailable','data_tracks':[],'cover_files_status':'not_examined'}
    result.update(id=snapshot['id'],toc=snapshot['toc'])
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(result));temp.replace(path)
    return result


def apply_text(snapshot,media):
    """CD-Text wins where present; online metadata can fill the remaining fields."""
    result=copy.deepcopy(snapshot)
    text=media.get('cd_text',{})
    if text.get('status')!='present':return result
    album=text.get('album',{});tracks=text.get('tracks',{})
    supplied=False
    for field in ['title','artist']:
        if album.get(field):
            result[field]=album[field];supplied=True
    # Some discs contain titles but no PERFORMER fields. A loading message is
    # UI state, never an album artist to write into filenames or Plex tags.
    if result.get('artist')=='Album wordt opgezocht…':result['artist']='Onbekende artiest'
    if result.get('artist','').casefold() in ('various','various artists','diverse artiesten'):
        result['artist']='Various Artists'
    for track in result.get('tracks',[]):
        own=dict(tracks.get(str(track['number']),{}))
        # Some authoring tools put performer and title together in TITLE.
        # Only split a spaced separator when CD-Text has no separate PERFORMER.
        # Split once, preserving hyphens inside either name and the rest of a title.
        if own.get('title') and not own.get('artist','').strip():
            parts=own['title'].split(' - ',1)
            if len(parts)==2 and all(part.strip() for part in parts):
                own.update(artist=parts[0].strip(),title=parts[1].strip())
        for field in ['title','artist']:
            if own.get(field):track[field]=own[field];supplied=True
        if not track.get('artist') and album.get('artist') and result['artist']!='Various Artists':
            track['artist']=album['artist']
    if supplied:
        result.update(metadata_status='found',metadata_source='cdtext')
    return result


if __name__=='__main__':
    device=sys.argv[1] if len(sys.argv)>1 else optical_device()
    if device!=optical_device():raise ValueError('Alleen de ingestelde cd-drive mag worden gelezen')
    print(json.dumps(probe(device)),flush=True)

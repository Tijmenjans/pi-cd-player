"""Fetch exact-edition artwork independently of the upload/playback path."""
import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import server

UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z')
DISCOGS = re.compile(r'discogs-([1-9][0-9]{0,11})\Z')
USER_AGENT = 'CDspelerArchive/1.0 (https://music.app.tijmenjans.nl)'
MAX_IMAGE = 4_000_000


def image_type(data):
    if data.startswith(b'\xff\xd8\xff'): return 'image/jpeg', '.jpg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png', '.png'
    raise ValueError('Cover is geen JPEG of PNG')


def get_cover(release,folder):
    discogs=DISCOGS.fullmatch(release)
    if not UUID.fullmatch(release) and not discogs: raise ValueError('Geen geldige albumuitgave')
    for ext in ['.jpg','.png']:
        p=folder/('cover'+ext)
        if p.exists() and p.stat().st_size<=MAX_IMAGE:
            data=p.read_bytes();image_type(data)
            return p,data
    if discogs:
        req=urllib.request.Request('https://api.discogs.com/releases/'+discogs[1],headers={'User-Agent':USER_AGENT})
        with urllib.request.urlopen(req,timeout=20) as response:entry=json.load(response)
        url=next((i['uri'] for i in entry.get('images',[]) if i.get('type')=='primary'),None)
        if not url:raise FileNotFoundError('Geen albumcover gevonden')
        if not url.startswith('https://i.discogs.com/'):raise ValueError('Ongeldige coverbron')
        req=urllib.request.Request(url,headers={'User-Agent':USER_AGENT})
        with urllib.request.urlopen(req,timeout=20) as response:data=response.read(MAX_IMAGE+1)
        if len(data)>MAX_IMAGE:raise ValueError('Cover is te groot')
        _,ext=image_type(data)
        p=folder/('cover'+ext);tmp=p.with_suffix('.partial')
        tmp.write_bytes(data);tmp.chmod(0o644);tmp.replace(p)
        return p,data
    for size in [1200,500]:
        try:
            req=urllib.request.Request(f'https://coverartarchive.org/release/{release}/front-{size}',
                                       headers={'User-Agent':USER_AGENT})
            with urllib.request.urlopen(req,timeout=20) as response:
                data=response.read(MAX_IMAGE+1)
            if len(data)>MAX_IMAGE: raise ValueError('Cover is te groot')
            _,ext=image_type(data)
            p=folder/('cover'+ext);tmp=p.with_suffix('.partial')
            tmp.write_bytes(data);tmp.chmod(0o644);tmp.replace(p)
            return p,data
        except urllib.error.HTTPError as exc:
            if exc.code!=404: raise
    # A MusicBrainz edition may have no CAA artwork while its explicitly
    # linked Discogs edition does. Never search by title or guess an edition.
    req=urllib.request.Request(
        f'https://musicbrainz.org/ws/2/release/{release}?inc=url-rels&fmt=json',
        headers={'User-Agent':USER_AGENT})
    with urllib.request.urlopen(req,timeout=20) as response:entry=json.load(response)
    for relation in entry.get('relations',[]):
        if relation.get('type')!='discogs':continue
        target=urllib.parse.urlsplit(relation.get('url',{}).get('resource',''))
        matched=re.fullmatch(r'/release/([1-9][0-9]{0,11})(?:-[^/]+)?/?',target.path)
        if target.scheme!='https' or target.hostname not in ['discogs.com','www.discogs.com'] or not matched:continue
        discogs_id=matched[1]
        path,data=get_cover('discogs-'+discogs_id,folder)
        source={'musicbrainz_release':release,'discogs_release':discogs_id,
                'method':'explicit MusicBrainz edition link','retrieved_at':time.time()}
        tmp=folder/'cover-source.json.partial'
        tmp.write_text(json.dumps(source));tmp.chmod(0o644);tmp.replace(folder/'cover-source.json')
        return path,data
    raise FileNotFoundError('Geen cover voor deze uitgave gevonden')


def matching_albums(manifest,cached=None):
    release=manifest['release']
    albums=[]
    track=next((t for t in manifest['tracks'] if server.publishable(manifest,t['number'])),None)
    if track is None:return []
    expected=server.destination(manifest,track['number']).parent
    expected_plex='/music/'+str(expected.relative_to(server.MUSIC))
    if cached:
        try:
            found=[]
            for key in cached:
                if not str(key).isdecimal():raise ValueError('Ongeldige Plex-ID')
                container=server.plex_request('/library/metadata/'+str(key))
                album=next(iter(container))
                if album.get('type')!='album':raise ValueError('Geen album')
                tracks=server.plex_request('/library/metadata/'+str(key)+'/children')
                if not any(str(Path(p.get('file','')).parent)==expected_plex for p in tracks.findall('.//Part')):
                    raise ValueError('Albumverwijzing is veranderd')
                found.append(album)
            if found:return found
        except urllib.error.HTTPError as exc:
            if exc.code!=404:raise
        except (ValueError,StopIteration,TypeError):pass
    for section in server.plex_request('/library/sections'):
        if section.get('type')!='artist' or not any(x.get('path')=='/music' for x in section): continue
        for album in server.plex_request('/library/sections/'+section.get('key')+'/all',
                                         {'type':9,'includeGuids':1}):
            exact=any(g.get('id')=='mbid://'+release for g in album.findall('Guid'))
            if not exact:
                # Unknown/unmatched albums can still be identified by the real media folder.
                tracks=server.plex_request('/library/metadata/'+album.get('ratingKey')+'/children')
                exact=any(str(Path(p.get('file','')).parent)==expected_plex
                          for p in tracks.findall('.//Part'))
            if exact:albums.append(album)
    return albums


def upload_poster(key,data):
    token=ET.parse(server.PREFS).getroot().get('PlexOnlineToken')
    content_type,_=image_type(data)
    req=urllib.request.Request(server.PLEX+'/library/metadata/'+key+'/posters',data=data,
               method='POST',headers={'X-Plex-Token':token,'Content-Type':content_type})
    with urllib.request.urlopen(req,timeout=20) as response:response.read()
    current=list(server.plex_request('/library/metadata/'+key))[0]
    if not current.get('thumb','').startswith('/library/metadata/'+key+'/thumb/'):
        raise RuntimeError('Plex heeft de albumcover nog niet bevestigd')


def process(manifest,state):
    release=manifest.get('release','')
    if not (UUID.fullmatch(release) or DISCOGS.fullmatch(release)) or not manifest.get('tracks'):return False
    track=next((t for t in manifest['tracks'] if server.publishable(manifest,t['number'])),None)
    if track is None:return False
    folder=server.destination(manifest,track['number']).parent
    if not folder.exists() or not any(folder.glob('*.flac')):return False
    key=str(folder)
    old=state.get(key,{})
    if old.get('release')==release and time.time()<old.get('retry_at',0):return False
    if old.get('release')==release and old.get('status')=='applied':
        if any((folder/('cover'+e)).exists() for e in ['.jpg','.png']):return False
    albums=[]
    try:
        path,data=get_cover(release,folder)
        albums=matching_albums(manifest,old.get('albums'))
        if not albums:raise RuntimeError('Album wordt nog door Plex geïndexeerd')
        digest=hashlib.sha256(data).hexdigest()
        for album in albums:upload_poster(album.get('ratingKey'),data)
        state[key]={'release':release,'status':'applied','at':time.time(),
                    'sha256':digest,'albums':[a.get('ratingKey') for a in albums]}
        logging.info('Albumcover toegevoegd: %s',manifest.get('title',''))
    except Exception as exc:
        interval=21600 if isinstance(exc,FileNotFoundError) else 120
        state[key]={'release':release,'status':'retry','retry_at':time.time()+interval,
                    'error':type(exc).__name__,'albums':[a.get('ratingKey') for a in albums] or old.get('albums',[])}
        logging.warning('Albumcover opnieuw proberen: %s',type(exc).__name__)
    return True


def run_once():
    statefile=server.ROOT/'artwork-state.json'
    try:state=json.loads(statefile.read_text())
    except (OSError,ValueError):state={}
    with server.connect() as db:
        manifests=[json.loads(r[0]) for r in db.execute('SELECT manifest FROM discs')]
    changed=False
    for manifest in manifests:changed=process(manifest,state) or changed
    if changed:
        temp=statefile.with_suffix('.tmp');temp.write_text(json.dumps(state));temp.replace(statefile)


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    while True:
        try:run_once()
        except Exception:logging.exception('Albumcovercontrole tijdelijk niet beschikbaar')
        time.sleep(15)

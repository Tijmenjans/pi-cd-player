"""MusicBrainz disc lookup with a conservative original-TOC fallback."""
import math
import urllib.error
import urllib.parse

LOOKUP_VERSION=1


def artist_credit(credits):
    return ''.join(a.get('name',a.get('artist',{}).get('name',''))+
                   a.get('joinphrase','') for a in credits)


def lengths_match(tracks,original):
    if len(tracks)!=len(original) or len(tracks)<4:return False
    try:
        lengths=[t.get('length') or t.get('recording',{}).get('length') for t in tracks]
        return all(type(length) in (int,float) and math.isfinite(length) and length>0
                   and abs(length/1000-own['sectors']/75)<=1.5
                   for length,own in zip(lengths,original))
    except (KeyError,TypeError,ValueError):return False


def release_metadata(payload,snapshot,allow_toc=False):
    metadata={'releases':[],'version':3,'lookup_version':LOOKUP_VERSION,
              'match_kind':'toc' if allow_toc else 'exact'}
    seen=set()
    for release in payload.get('releases',[]):
        media=release.get('media',[])
        for medium in media:
            tracks=medium.get('tracks',[])
            if len(tracks)!=len(snapshot['tracks']):continue
            if allow_toc:
                if not lengths_match(tracks,snapshot['tracks']):continue
            elif snapshot['id'] not in [d['id'] for d in medium.get('discs',[])]:continue
            position=int(medium.get('position',1))
            key=(release['id'],position)
            if key in seen:continue
            seen.add(key)
            artist=artist_credit(release.get('artist-credit',[]))
            metadata['releases'].append({
                'id':release['id'],'title':release['title'],'artist':artist,
                'disc_number':position,'disc_total':len(media),
                'country':release.get('country',''),'date':release.get('date',''),
                'tracks':[t.get('title',t.get('recording',{}).get('title','')) for t in tracks],
                'track_artists':[artist_credit(t.get('artist-credit') or
                    t.get('recording',{}).get('artist-credit') or []) or
                    (artist if artist!='Various Artists' else 'Onbekende artiest') for t in tracks]})
    # A multi-CD release with two fitting media cannot be selected by release ID
    # alone. Leave that release out rather than silently assigning the wrong disc.
    counts={}
    for release in metadata['releases']:counts[release['id']]=counts.get(release['id'],0)+1
    metadata['releases']=[r for r in metadata['releases'] if counts[r['id']]==1]
    return metadata


def lookup(snapshot,fetch):
    base='https://musicbrainz.org/ws/2/discid/'+snapshot['id']
    params={'inc':'recordings+artist-credits','fmt':'json','cdstubs':'no'}
    def query(query_params):
        try:return fetch(base+'?'+urllib.parse.urlencode(query_params))
        except urllib.error.HTTPError as exc:
            if exc.code!=404:raise
            return {'releases':[]}
    exact=release_metadata(query(params),snapshot)
    if exact['releases'] or not snapshot.get('toc'):return exact
    return release_metadata(query({**params,'toc':snapshot['toc']}),snapshot,allow_toc=True)


def normalise_barcode(value):
    value=str(value).replace(' ','').replace('-','')
    if not value.isascii() or not value.isdigit() or len(value) not in (8,12,13) or not value.strip('0'):
        raise ValueError('Gebruik de 8, 12 of 13 cijfers van de barcode.')
    check=sum(int(n)*(3 if index%2==0 else 1) for index,n in enumerate(reversed(value[:-1])))
    if (-check)%10!=int(value[-1]):raise ValueError('De barcode klopt niet. Controleer de cijfers op het doosje.')
    return value


def lookup_barcode(snapshot,barcode,fetch):
    """Barcode narrows candidates; measured track count and lengths still decide."""
    barcode=normalise_barcode(barcode)
    url='https://musicbrainz.org/ws/2/release/?'+urllib.parse.urlencode({'query':'barcode:'+barcode,'fmt':'json','limit':5})
    search=fetch(url);releases=[]
    import re
    for candidate in search.get('releases',[])[:5]:
        identity=candidate.get('id','')
        if not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',identity):continue
        try:full=fetch('https://musicbrainz.org/ws/2/release/'+identity+'?inc=recordings+artist-credits+discids&fmt=json')
        except urllib.error.HTTPError as exc:
            if exc.code==404:continue
            raise
        if str(full.get('barcode','')).replace(' ','').lstrip('0')!=barcode.lstrip('0'):continue
        releases.append(full)
    result=release_metadata({'releases':releases},snapshot,allow_toc=True)
    result['lookup_barcode']=barcode
    return result

"""Validated catalogue entries; measured TOC lengths always remain authoritative."""
import json
import math
from pathlib import Path


def validated(data):
    if not isinstance(data,dict):raise ValueError('Catalogusentry is geen object')
    for field in ('id','title','artist'):
        if not isinstance(data.get(field),str) or not data[field].strip():raise ValueError('Catalogusveld ontbreekt')
    if not isinstance(data.get('media'),list) or not data['media']:raise ValueError('Media ontbreken')
    if type(data.get('disc_total',len(data['media']))) is not int or not 1<=data.get('disc_total',len(data['media']))<=99:raise ValueError('Ongeldig aantal media')
    for medium in data['media']:
        if not isinstance(medium,dict) or type(medium.get('number')) is not int or not 1<=medium['number']<=99:raise ValueError('Ongeldig medium')
        ids=medium.get('disc_ids',[])
        if not isinstance(ids,list) or any(not isinstance(i,str) or not i.strip() for i in ids):raise ValueError('Ongeldige cd-IDs')
        tracks=medium.get('tracks')
        if not isinstance(tracks,list) or not 1<=len(tracks)<=99:raise ValueError('Tracks ontbreken')
        for track in tracks:
            if not isinstance(track,dict):raise ValueError('Ongeldige track')
            for field in ('title','artist'):
                if not isinstance(track.get(field),str) or not track[field].strip():raise ValueError('Trackmetadata ontbreekt')
            seconds=track.get('seconds')
            if type(seconds) not in (int,float) or not math.isfinite(seconds) or not 0<seconds<=6000:raise ValueError('Ongeldige duur')
    return data


def lookup(snapshot,directory):
    tracks=snapshot.get('tracks',[])
    if len(tracks)<4:return None
    exact=[];fallback=[]
    for path in sorted(Path(directory).glob('*.json')):
        try:data=validated(json.loads(path.read_text()))
        except (OSError,ValueError,TypeError):continue
        for medium in data['media']:
            candidates=medium['tracks'];ids=medium.get('disc_ids',[])
            if ids and snapshot.get('id') not in ids:continue
            if len(candidates)!=len(tracks):continue
            try:differences=[abs(t['sectors']/75-c['seconds']) for t,c in zip(tracks,candidates)]
            except (KeyError,TypeError):continue
            if max(differences)>1.5:continue
            match={'id':data['id'],'title':data['title'],'artist':data['artist'],
                   'date':data.get('date',''),'country':data.get('country',''),
                   'disc_number':medium['number'],'disc_total':data.get('disc_total',len(data['media'])),
                   'tracks':[t['title'] for t in candidates],
                   'track_artists':[t['artist'] for t in candidates]}
            (exact if ids else fallback).append(match)
    matches=exact or fallback
    if len(matches)!=1:return None
    return {'version':3,'selected':matches[0]['id'],'releases':matches}

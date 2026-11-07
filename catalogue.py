"""Verified alternate catalogue entries, matched by every track's original CD length."""
import json
from pathlib import Path


def lookup(snapshot, directory):
    tracks=snapshot.get('tracks',[])
    if len(tracks)<4:return None
    matches=[]
    for path in sorted(Path(directory).glob('*.json')):
        try:data=json.loads(path.read_text())
        except (OSError,ValueError):continue
        media=data.get('media',[])
        for medium in media:
            candidates=medium.get('tracks',[])
            if len(candidates)!=len(tracks):continue
            differences=[abs(t['sectors']/75-c['seconds']) for t,c in zip(tracks,candidates)]
            if max(differences)>1.5:continue
            matches.append({'id':data['id'],'title':data['title'],'artist':data['artist'],
                'date':data.get('date',''),'country':data.get('country',''),
                'disc_number':medium['number'],'disc_total':len(media),
                'tracks':[t['title'] for t in candidates],
                'track_artists':[t['artist'] for t in candidates]})
    if len(matches)!=1:return None  # Ambiguous matches require a deliberate choice.
    return {'version':3,'selected':matches[0]['id'],'releases':matches}

"""Turn a saved Discogs release response into a reviewable catalogue proposal.

No network, token, live drive or catalogue changes. Explicit position mapping is
required; source durations never replace the supplied measured TOC.
"""
import argparse
import json
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from catalogue import validated


def artist_name(items):
    return ''.join(str(a.get('name',''))+str(a.get('join','') and ' '+a['join']+' ') for a in items).strip()


def proposal(release_url,entry,snapshot,positions,disc_number,disc_total,confirmed=False):
    match=re.fullmatch(r'https://(?:www\.)?discogs.com/release/([1-9][0-9]*)(?:-[^/?#]+)?/?',release_url)
    if not match or entry.get('id')!=int(match[1]):raise ValueError('Release-URL en JSON-ID moeten overeenkomen')
    tracks=snapshot.get('tracks',[])
    if not tracks or len(positions)!=len(tracks) or len(set(positions))!=len(positions):raise ValueError('Geef één unieke Discogs-positie per TOC-track')
    indexed={}
    def collect(rows):
        for row in rows:
            if row.get('sub_tracks'):collect(row['sub_tracks']);continue
            if row.get('type_','track')!='track':continue
            position=row.get('position','')
            if position in indexed:raise ValueError('Dubbele Discogs-positie')
            indexed[position]=row
    collect(entry.get('tracklist',[]))
    album_artist=artist_name(entry.get('artists',[]))
    converted=[];corrections=[]
    for track,position in zip(tracks,positions):
        row=indexed[position]
        if type(track.get('sectors')) is not int:raise ValueError('Gemeten TOC-sectoren ontbreken')
        seconds=track['sectors']/75
        converted.append({'title':row['title'],'artist':artist_name(row.get('artists',[])) or album_artist,'seconds':seconds})
        corrections.append({'track':track.get('number'),'discogs_position':position,'discogs_duration':row.get('duration'),'measured_seconds':seconds})
    if not 1<=disc_number<=disc_total<=99:raise ValueError('Ongeldige mediumselectie')
    medium={'number':disc_number,'tracks':converted}
    if confirmed:
        if not snapshot.get('id'):raise ValueError('Bevestigde cd-ID ontbreekt')
        medium['disc_ids']=[snapshot['id']]
    result={'id':'discogs-'+match[1],'title':entry['title'],'artist':album_artist,
            'date':str(entry.get('year','')),'disc_total':disc_total,'source':release_url,
            'notes':'Handmatig positievoorstel; TOC-duur behouden. Controleer titels/artiesten vóór opname.',
            'provenance':corrections,'media':[medium]}
    return validated(result)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release_url');parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--toc',type=Path,required=True)
    parser.add_argument('--positions',required=True,help='Discogs-posities in TOC-volgorde, gescheiden door komma’s')
    parser.add_argument('--disc-number',type=int,required=True);parser.add_argument('--disc-total',type=int,required=True)
    parser.add_argument('--confirmed',action='store_true',help='Koppel het na eigen controle bevestigde cd-ID')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=proposal(args.release_url,json.loads(args.input.read_text()),json.loads(args.toc.read_text()),
                    args.positions.split(','),args.disc_number,args.disc_total,args.confirmed)
    catalogue_dir=Path(__file__).resolve().parents[1]/'catalogue'
    if args.output.resolve().is_relative_to(catalogue_dir):parser.error('Schrijf eerst een voorstel buiten catalogue/; controleer het vóór opname.')
    # Never overwrite a catalogue entry or existing proposal.
    with args.output.open('x') as stream:json.dump(result,stream,ensure_ascii=False,indent=2);stream.write('\n')

if __name__=='__main__':main()

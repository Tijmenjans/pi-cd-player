"""Conservative, sample-accurate edge trimming. Internal pauses are never removed."""
import json
import math
import re
import subprocess
from fractions import Fraction

POLICY = 'edges-v1:-60dB:300ms:100ms-padding'
MIN_SILENCE = .3
PADDING = .1


def probe(path):
    result=subprocess.run(['ffprobe','-v','error','-select_streams','a:0',
        '-show_entries','stream=sample_rate,channels,duration_ts,time_base,bits_per_raw_sample',
        '-of','json',str(path)],check=True,capture_output=True,text=True,timeout=30)
    stream=json.loads(result.stdout)['streams'][0]
    rate=int(stream['sample_rate'])
    frames=round(int(stream['duration_ts'])*Fraction(stream['time_base'])*rate)
    if rate!=44100 or int(stream['channels'])!=2 or frames<1:
        raise ValueError('Geen geldige stereo-cd-audio')
    return rate,frames


def bounds(stderr,rate,frames):
    duration=frames/rate
    segments=[]
    start=None
    for line in stderr.splitlines():
        m=re.search(r'silence_start:\s*(-?[0-9.]+)',line)
        if m:start=max(0,float(m[1]))
        m=re.search(r'silence_end:\s*([0-9.]+)',line)
        if m and start is not None:
            segments.append((start,min(duration,float(m[1]))));start=None
    first,last=0,frames
    if segments and segments[0][0]<=2/rate:
        first=max(0,math.floor((segments[0][1]-PADDING)*rate))
    if segments and segments[-1][1]>=duration-2/rate:
        last=min(frames,math.ceil((segments[-1][0]+PADDING)*rate))
    # Keep wholly silent tracks intact rather than creating an empty or invalid song.
    if last-first<max(1,round(.1*rate)):
        first,last=0,frames
    return {'sample_rate':rate,'source_samples':frames,'start_sample':first,'end_sample':last,
            'removed_start_samples':first,'removed_end_samples':frames-last,
            'duration_seconds':(last-first)/rate}


def analyze(path):
    rate,frames=probe(path)
    result=subprocess.run(['ffmpeg','-nostdin','-hide_banner','-nostats','-i',str(path),
        '-map','0:a:0','-af',f'silencedetect=noise=-60dB:d={MIN_SILENCE}',
        '-f','null','-'],check=True,capture_output=True,text=True,timeout=180)
    return bounds(result.stderr,rate,frames)


def audio_filter(plan):
    if not plan['removed_start_samples'] and not plan['removed_end_samples']:return None
    return f'atrim=start_sample={plan["start_sample"]}:end_sample={plan["end_sample"]},asetpts=PTS-STARTPTS'

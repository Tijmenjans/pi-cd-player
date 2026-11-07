"""DVD-aware remuxing: preserve palettes/languages and prefer Dutch subtitles."""
import json,subprocess
DUTCH={'nl','nld','dut'}

def dutch_subtitle(streams):
 subtitles=[s for s in streams if s.get('codec_type')=='subtitle']
 return next((i for i,s in enumerate(subtitles) if s.get('tags',{}).get('language','').lower() in DUTCH),None)

def remux_command(binary,device,title,streams,output='pipe:1',seconds=None):
 cmd=[str(binary),'-hide_banner','-loglevel','error','-nostdin','-f','dvdvideo','-title',str(title),'-i',str(device),'-map','0:v:0','-map','0:a?','-c','copy']
 selected=dutch_subtitle(streams)
 if selected is not None:
  cmd += ['-map',f'0:s:{selected}','-disposition:s:0','default','-metadata:s:s:0','language=nld','-metadata:s:s:0','title=Nederlands']
 else:cmd+=['-sn']
 if seconds is not None:cmd+=['-t',str(seconds)]
 return cmd+['-f','matroska','-cluster_time_limit','1000',str(output)]

def inspect(binary,device,title,env,pass_fds=()):
 cmd=[str(binary),'-v','error','-f','dvdvideo','-title',str(title),'-i',str(device),'-show_entries','stream=index,codec_name,codec_type:stream_tags=language','-of','json']
 p=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=35,pass_fds=pass_fds)
 if p.returncode:raise RuntimeError('De dvd-sporen konden niet worden gelezen')
 return json.loads(p.stdout)['streams']

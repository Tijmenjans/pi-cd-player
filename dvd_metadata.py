"""Small, cached public IMDb lookups. Never block the optical reader or status API."""
import hashlib,json,re,threading,time,unicodedata,urllib.parse,urllib.request
from pathlib import Path

def normalized(title):
 s=unicodedata.normalize('NFKD',str(title).replace('&',' and '))
 return ' '.join(re.sub(r'[^a-z0-9]+',' ',s.encode('ascii','ignore').decode().lower()).split())

def select_result(title,items):
 query=normalized(title);year=None
 match=re.search(r'\b((?:19|20)[0-9]{2})$',query)
 if match:year=int(match[1]);query=query[:match.start()].strip()
 query=re.sub(r'\s+(?:dvd|disc|disk)(?:\s*[0-9]+)?$','',query)
 if query in ('','dvd','dvd video','video ts','movie'):return None
 candidates=[r for r in items if r.get('qid') in ('movie','tvMovie','video') and re.fullmatch(r'tt[0-9]+',str(r.get('id',''))) and normalized(r.get('l',''))==query and (not year or r.get('y')==year)]
 if len({r['id'] for r in candidates})!=1:return None
 r=candidates[0]
 return {'id':r['id'],'title':r['l'],'year':r.get('y'),'cast':str(r.get('s',''))[:300],'url':'https://www.imdb.com/title/'+r['id']+'/','source':'IMDb','poster_url':r.get('i',{}).get('imageUrl')}

class MovieMetadata:
 def __init__(self,root):
  self.root=Path(root)/'data/dvd-metadata';self.root.mkdir(parents=True,exist_ok=True)
  self.lock=threading.Lock();self.cache={};self.pending=set()
 def key(self,media):return hashlib.sha256((media.get('disc_id','')+'|'+media['title']+'|'+str(media.get('seconds',''))).encode()).hexdigest()[:32]
 def get(self,media):
  key=self.key(media)
  with self.lock:
   if key not in self.cache:
    try:self.cache[key]=json.loads((self.root/(key+'.json')).read_text())
    except (OSError,ValueError):self.cache[key]={'at':0,'movie':None}
   row=self.cache[key]
   age=time.time()-row['at'];ttl=30*86400 if row.get('movie') else 86400
   if age>ttl and key not in self.pending and len(self.pending)<2:
    self.pending.add(key);threading.Thread(target=self.fetch,args=(key,media['title']),daemon=True).start()
   return row.get('movie')
 def fetch(self,key,title):
  try:
   query=normalized(title)
   url='https://v3.sg.media-imdb.com/suggestion/'+(query[:1] or 'x')+'/'+urllib.parse.quote(query)+'.json'
   req=urllib.request.Request(url,headers={'User-Agent':'DVD-player/1.0','Accept':'application/json'})
   with urllib.request.urlopen(req,timeout=12) as response:payload=json.loads(response.read(1000000))
   movie=select_result(title,payload.get('d',[]))
   if movie:
    poster=movie.pop('poster_url',None)
    if poster and urllib.parse.urlsplit(poster).scheme=='https' and urllib.parse.urlsplit(poster).hostname=='m.media-amazon.com':
     try:
      with urllib.request.urlopen(poster,timeout=15) as response:image=response.read(5_000_001)
      if len(image)<=5_000_000 and image.startswith(b'\xff\xd8\xff'):
       target=self.root/(key+'.jpg');tmp=target.with_suffix('.partial');tmp.write_bytes(image);tmp.replace(target)
       movie['cover']='/dvd/art/'+key+'.jpg'
     except Exception:pass
   row={'at':time.time(),'movie':movie};tmp=self.root/(key+'.tmp');tmp.write_text(json.dumps(row));tmp.replace(self.root/(key+'.json'))
   with self.lock:self.cache[key]=row
  except Exception:
   # Retry transient network errors later, without creating a negative match for a day.
   with self.lock:self.cache[key]={'at':time.time()-86400+300,'movie':None}
  finally:
   with self.lock:self.pending.discard(key)

import ast,types,unittest
from pathlib import Path
class Done(BaseException):pass
class ScanTest(unittest.TestCase):
 def run_scan(self,ids,changes):
  tree=ast.parse((Path(__file__).resolve().parents[1]/'app.py').read_text())
  fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='scan_loop')
  reads=iter(ids);flags=iter(changes);accepted=[]
  def read(*a,**k):
   try:identity=next(reads)
   except StopIteration:raise Done()
   return types.SimpleNamespace(id=identity,toc='toc',first_track=1,track_lengths=[750])
  env={'media_revision':0,'transition_lock':__import__('threading').RLock(),'runtime_stop':types.SimpleNamespace(is_set=lambda:False),'transition':{'active':False},'DriveBusy':type('DriveBusy',(Exception,),{}),'source':'cd','dvd':types.SimpleNamespace(busy=lambda:False),'optical_device':lambda:'/dev/fake','OpticalDeviceError':type('OpticalDeviceError',(Exception,),{}),'disc':{},'time':types.SimpleNamespace(sleep=lambda _:None),'archive':types.SimpleNamespace(reading=lambda:False,cancel=lambda:None,optical=types.SimpleNamespace(acquire=__import__('contextlib').nullcontext)),'media_changed':lambda:next(flags,True),'libdiscid':types.SimpleNamespace(read=read,FEATURE_READ=1,DiscError=OSError),'prepare_disc':lambda s:s,'accept_disc':lambda s,autoplay:accepted.append((s['id'],autoplay)),'lock':__import__('threading').RLock(),'threading':types.SimpleNamespace(Thread=lambda **k:types.SimpleNamespace(start=lambda:None)),'enrich':lambda s:None}
  exec(compile(ast.Module(body=[fn],type_ignores=[]),'scan','exec'),env)
  try:env['scan_loop']()
  except Done:pass
  return accepted
 def test_late_media_changed_does_not_restart_same_cd(self):
  self.assertEqual(self.run_scan(['A','A','A'],[True,True,True]),[('A',False)])
 def test_different_cd_still_autoplays(self):
  self.assertEqual(self.run_scan(['A','B'],[True,True]),[('A',False),('B',True)])
if __name__ == '__main__': unittest.main()

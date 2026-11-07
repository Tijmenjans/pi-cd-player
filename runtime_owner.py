"""One runtime owner per installation; webworker count cannot duplicate readers."""
import fcntl
import os
from pathlib import Path

class RuntimeOwner:
    def __init__(self,path):self.path=Path(path);self.handle=None
    def acquire(self):
        if self.handle is not None:return
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR,0o600)
        handle=os.fdopen(fd,'r+')
        try:fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close();raise RuntimeError('Een andere speler-runtime gebruikt deze installatie al')
        self.handle=handle
    def release(self):
        if self.handle is not None:self.handle.close();self.handle=None

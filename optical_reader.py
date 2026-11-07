"""Progress watchdog and process-lifetime optical lease (also survives web restarts)."""
import fcntl,os,subprocess,time
from pathlib import Path

class ReadFailure(RuntimeError):pass
class DriveBusy(ReadFailure):pass

class ProgressWatchdog:
    def __init__(self,seconds,speed,clock=time.monotonic,stall=45):
        self.clock=clock;self.started=clock();self.changed=self.started;self.bytes=0;self.stall=stall
        self.deadline=self.started+max(120,min(1800,seconds/max(speed or 4,1)*4+45))
    def check(self,size):
        now=self.clock()
        if size>self.bytes:self.bytes=size;self.changed=now
        if now-self.changed>=self.stall:raise ReadFailure('De cd-drive levert geen nieuwe data; herstel bij lagere snelheid')
        if now>=self.deadline:raise ReadFailure('De cd-drive leest te langzaam; herstel bij lagere snelheid')
        return max(0,int(now-self.changed))

def stop_process(proc):
    if proc is None or proc.poll() is not None:return True
    for signal in ('terminate','kill'):
        try:getattr(proc,signal)();proc.wait(timeout=2);return True
        except subprocess.TimeoutExpired:pass
        except ProcessLookupError:return True
    return proc.poll() is not None

class OpticalLease:
    def __init__(self,path,binary):self.path=Path(path);self.binary=os.fsencode(str(binary))
    def legacy_readers(self):
        # Covers older readers which predate the inherited flock lease.
        result=[]
        if not Path('/proc').exists():return result
        try:entries=Path('/proc').iterdir()
        except OSError:return result
        for entry in entries:
            if not entry.name.isdigit():continue
            try:
                args=(entry/'cmdline').read_bytes().split(b'\0')
                if args and args[0]==self.binary and b'-d' in args:result.append(int(entry.name))
            except OSError:continue
        return result
    def acquire(self):
        handle=self.path.open('a+b')
        try:
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            if self.legacy_readers():raise DriveBusy('De USB-cd-drive is nog bezig met een eerdere opdracht')
            return handle
        except (BlockingIOError,DriveBusy):
            handle.close();raise DriveBusy('De USB-cd-drive reageert niet op stoppen. Sluit de drive opnieuw aan; opgeslagen nummers blijven bewaard.')
    def busy(self):
        try:handle=self.acquire()
        except DriveBusy:return True
        handle.close();return False

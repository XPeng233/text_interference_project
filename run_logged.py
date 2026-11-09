"""Run a Python project script with UTF-8 logs and native console progress."""
import sys,runpy,traceback
from pathlib import Path
class Tee:
    def __init__(self,console,file): self.console,self.file=console,file
    def write(self,s):
        self.file.write(s);self.file.flush()
        try: self.console.write(s);self.console.flush()
        except UnicodeEncodeError: self.console.write(s.encode('ascii','replace').decode())
        return len(s)
    def flush(self): self.file.flush();self.console.flush()
    def isatty(self): return False
if len(sys.argv)<3: raise SystemExit('Usage: python run_logged.py logfile script.py [arguments]')
log,script,*args=sys.argv[1:];Path(log).parent.mkdir(parents=True,exist_ok=True)
with open(log,'w',encoding='utf-8') as f:
    stdout,stderr=sys.stdout,sys.stderr
    sys.stdout,sys.stderr=Tee(stdout,f),Tee(stderr,f)
    sys.argv=[script,*args]
    try:runpy.run_path(script,run_name='__main__')
    except Exception:
        traceback.print_exc();raise SystemExit(1)
    finally:sys.stdout,sys.stderr=stdout,stderr

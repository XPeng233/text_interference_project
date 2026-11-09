"""Download official CIFAR-10 archive with streaming and MD5 verification."""
from pathlib import Path
import urllib.request, hashlib, time
p=Path('cache/data'); p.mkdir(parents=True,exist_ok=True)
target=p/'cifar-10-python.tar.gz'
expected='c58f30108f718f92721af3b95e74349a'
def check(path):
    return path.exists() and hashlib.md5(path.read_bytes()).hexdigest()==expected
if not check(target):
    url='https://cave.cs.toronto.edu/kriz/cifar-10-python.tar.gz'
    print('Downloading',url,flush=True)
    partial=target.with_suffix('.partial')
    with urllib.request.urlopen(url,timeout=90) as src, partial.open('wb') as out:
        n=0; t=time.time()
        while True:
            b=src.read(1024*1024)
            if not b: break
            out.write(b); n+=len(b)
            if n%(20*1024*1024)==0: print(f'{n/1024/1024:.0f} MiB, {time.time()-t:.1f}s',flush=True)
    if not check(partial): raise RuntimeError('Official archive MD5 mismatch')
    partial.replace(target)
print('Verified',target,expected,flush=True)

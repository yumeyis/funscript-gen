"""Compare the dominant frequency of the output and the hand-made script in 5 s windows (both with a clear peak): how often
the output keeps another tempo than the hand-made script.

  uv run python scripts/tempo_windows.py RUN CONFIG
"""

import sys

import numpy as np

from scipy.signal import periodogram
from funscript_gen.validate import clips, load_manifest
from funscript_gen.export.funscript import Funscript
m=load_manifest(); run=sys.argv[1]; cfg=sys.argv[2]; W=5000
def dom(acts,lo,hi):
    t=np.array([a.at for a in acts]);p=np.array([a.pos for a in acts],float)
    g=np.arange(lo,hi,1000/30); y=np.interp(g,t,p); y-=y.mean()
    if y.std()<2: return None
    f,P=periodogram(y,fs=30,window='hann',nfft=4096); k=(f>0.5)&(f<6); i=np.argmax(P*k)
    s=P[(f>f[i]-0.25)&(f<f[i]+0.25)].sum()/P[k].sum()
    return f[i],s
rows=[];total=0
for c in clips(m,'dev,test'):
    ref=Funscript.load(c.reference).actions; pred=Funscript.load(f'out/runs/{run}/{cfg}/{c.name}.funscript').actions
    end=min(ref[-1].at,pred[-1].at)
    for lo in range(0,int(end)-W,W):
        total+=1
        r=dom(ref,lo,lo+W); o=dom(pred,lo,lo+W)
        if r and o and r[1]>=0.4 and o[1]>=0.4: rows.append((c.name,lo/1000,round(r[0],2),round(o[0],2),round(o[0]/r[0],2)))
ratio=np.array([r[4] for r in rows])
print('windows',total,'both clear',len(rows))
print('match (0.85-1.18):',round(float(np.mean((ratio>0.85)&(ratio<1.18))),2),'mismatch (<0.77 or >1.3):',round(float(np.mean((ratio<0.77)|(ratio>1.3))),2))
bad=[r for r in rows if r[4]<0.77 or r[4]>1.3]
from collections import Counter
print('mismatching windows per clip:',Counter(r[0] for r in bad).most_common())
for r in bad[:30]: print(*r)

import sys,wave,importlib.util
import numpy as np
spec=importlib.util.spec_from_file_location('tt',__import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)),'tone_test.py'));tt=importlib.util.module_from_spec(spec);spec.loader.exec_module(tt)
x=tt.load(sys.argv[1]);SR=48000;h=tt.h
print('sec | rms | 500Hz amp | in-band rms(/190) | peak')
for s in range(0,len(x)//SR,3):
    w=x[s*SR:(s+3)*SR].astype(float)
    if len(w)<SR: break
    n=np.arange(len(w)); a=2*abs(np.mean(w*np.exp(-2j*np.pi*500*n/SR)))
    y=np.convolve(w,h[::-1],'valid')
    print(s,round(np.sqrt(np.mean(w*w))),round(a),round(np.sqrt(np.mean(y*y))/190,1),int(abs(w).max()))
f=np.abs(np.fft.rfft(x*np.hanning(len(x))));fr=np.fft.rfftfreq(len(x),1/SR);m=f/f.max()
for lo,hi in [(0,300),(300,700),(700,2000),(2000,6000),(6000,12000),(12000,16000),(16000,24000)]:
    b=(fr>=lo)&(fr<hi);print(lo,hi,'band power dB',round(10*np.log10(np.sum(m[b]**2)+1e-20),1))
# real noise + digital tone: what amplitude would this room need? (tone fitted out over 2 s pieces)
n=np.arange(len(x));r=x.astype(float).copy()
L=SR
for i in range(0,len(x),L):
    seg=r[i:i+L];k=np.arange(i,i+len(seg));e=np.exp(2j*np.pi*500*k/SR);c=np.mean(seg*np.conj(e));r[i:i+L]=seg-2*np.real(c*e)
print('residual rms',round(np.sqrt(np.mean(r*r)),1))
codes=list(tt.codes(16));spots=np.linspace(SR,len(x)-tt.NP-SR,10).astype(int)
for amp in [500,2000,5000,10000,20000,32000]:
    t=np.clip(np.round(r+amp*np.sin(2*np.pi*500*n/SR)),-32768,32767).astype(np.int64)
    ok=tot=0
    for cI,cQ in codes:
        for o in spots:
            ok+=tt.passes(t[o:o+tt.NP],cI,cQ)[0];tot+=1
    print('tone amp',amp,'on this recording residual:',ok,'/',tot)

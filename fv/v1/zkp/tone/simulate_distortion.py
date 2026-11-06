import sys,glob,os,importlib.util
import numpy as np
spec=importlib.util.spec_from_file_location('tt',__import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)),'tone_test.py'));tt=importlib.util.module_from_spec(spec);spec.loader.exec_module(tt)
SR=48000
x=tt.load(sys.argv[1]);n=np.arange(len(x));r=x.astype(float).copy()
for i in range(0,len(x),SR):
    seg=r[i:i+SR];k=np.arange(i,i+len(seg));e=np.exp(2j*np.pi*500*k/SR);c=np.mean(seg*np.conj(e));r[i:i+SR]=seg-2*np.real(c*e)
rng=np.random.default_rng(3)
codes=list(tt.codes(16));spots=np.linspace(SR,len(x)-tt.NP-SR,10).astype(int)
def rate(amp,db,noise=True):
    s=amp*np.sin(2*np.pi*500*n/SR)
    if db is not None:
        for m in range(2,13):  # harmonics fall off with order: db at 2nd, -6 dB per order after
            s=s+amp*10**((db-6*(m-2))/20)*np.sin(2*np.pi*500*m*n/SR+rng.uniform(0,6.28))
    t=np.clip(np.round(s+(r if noise else 0)),-32768,32767).astype(np.int64)
    ok=0
    for cI,cQ in codes:
        for o in spots: ok+=tt.passes(t[o:o+tt.NP],cI,cQ)[0]
    return ok
print('amp 10000, room noise from the recording; passes out of 160')
for db in [None,-80,-70,-60,-50,-40,-30]:
    print('2nd harmonic',db,'dB:',rate(10000,db))
print('amp 20000');
for db in [None,-60,-50,-40]: print(db,rate(20000,db))

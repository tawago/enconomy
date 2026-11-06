import numpy as np, wave
n=np.arange(48000*12); r=np.random.default_rng(1)
for name,x in [('noisy.wav',10000*np.sin(2*np.pi*500*n/48000)+r.normal(0,30,len(n))),('noise.wav',r.normal(0,1000,len(n)))]:
    with wave.open(name,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000);w.writeframes(np.round(x).astype('<i2').tobytes())

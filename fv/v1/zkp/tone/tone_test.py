#!/usr/bin/env python3
"""Does a blind tone, played through a real speaker into a real mic, pass the partner check (lib.nr 441-472)?

  make [HZ]        write tone_<HZ>hz.wav, 60 s, 48 kHz, to play on the speaker
  score REC.wav    run the circuit's exact integer test on the recording against fresh codes

The codes are generated after the recording exists, so the tone can't know them.
Needs a mono or stereo 16-bit 48 kHz WAV. Only the arithmetic rule is replayed here: no signature, Merkle or proof.
Run: server/.venv/bin/python fv/v1/zkp/tone/tone_test.py ...
"""
import hashlib, os, sys, wave
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "server"))
from pop import jbl250, popt2  # noqa: E402

SR, L, HM, NP, BAR = 48000, 12000, 31, 12062, 4474747
h = np.array(popt2.RATES[SR]["h"], dtype=np.int64)
assert popt2.RATES[SR]["B"] == BAR


def make(hz):
    n = np.arange(SR * 60)
    x = np.round(20000 * np.sin(2 * np.pi * hz * n / SR)).astype("<i2")
    name = f"tone_{hz}hz.wav"
    with wave.open(name, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(x.tobytes())
    print("wrote", name)


def load(path):
    with wave.open(path, "rb") as w:
        if w.getframerate() != SR or w.getsampwidth() != 2:
            sys.exit(f"need 16-bit {SR} Hz, got {w.getsampwidth() * 8}-bit {w.getframerate()} Hz. Don't resample: "
                     "that changes the test. Record at 48 kHz.")
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.int64)
        return x[:: w.getnchannels()]  # first channel


def codes(n):
    for i in range(n):
        seed = hashlib.sha256(b"tone%d" % i).hexdigest()
        role = "AB"[i % 2]
        ci, cq = popt2.code(jbl250.bed_key(seed, role, 0), role, SR)
        yield np.frombuffer(ci, dtype=np.int8).astype(np.int64), np.frombuffer(cq, dtype=np.int8).astype(np.int64)


def passes(w, cI, cQ):
    """partner_side: BAR * (I^2 + Q^2) - E * cn2 >= 0, in exact integers."""
    y = np.convolve(w, h[::-1], "valid")[:L]  # FIR output, y[m] = sum h[t] w[m + t]
    assert len(y) == L
    e = sum(int(v) * int(v) for v in y)
    seg = w[HM:HM + L]
    i, q = int(cI @ seg), int(cQ @ seg)
    return BAR * (i * i + q * q) - e * int(cI @ cI) >= 0, e


def score(path, ncodes=40, nspots=20):
    x = load(path)
    x = x[SR:-SR] if len(x) > 3 * SR + NP else x  # drop the first and last second (taps, start-up)
    if len(x) < NP * 2:
        sys.exit("recording too short, need at least 5 s")
    peak, rms = int(abs(x).max()), float(np.sqrt(np.mean(x.astype(float) ** 2)))
    f = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    fr = np.fft.rfftfreq(len(x), 1 / SR)
    top = float(fr[np.argmax(f[1:]) + 1])
    y = np.convolve(x[:SR * 2], h[::-1], "valid")
    print(f"samples {len(x)}  peak {peak}  rms {rms:.1f}  loudest frequency {top:.0f} Hz")
    print(f"filter output rms / 190 (in-band level, in samples): {np.sqrt(np.mean(y.astype(float) ** 2)) / 190:.1f}")
    n = np.arange(len(x))
    amp = [2 * abs(np.mean(x[i:i + SR] * np.exp(-2j * np.pi * top * n[i:i + SR] / SR))) for i in range(0, len(x) - SR, SR)]
    print(f"tone amplitude per second: median {np.median(amp):.0f}  min {min(amp):.0f}  max {max(amp):.0f}")
    if np.median(amp) < 5000:
        print("WARNING: tone amplitude under 5000. A 0 here doesn't rule the tone out: get closer or turn it up.")
    if peak >= 32767:
        print("WARNING: clipping. Turn the speaker down and record again.")
    spots = np.linspace(0, len(x) - NP - 1, nspots).astype(int)
    ok = tot = 0
    for cI, cQ in codes(ncodes):
        for o in spots:
            ok += passes(x[o:o + NP], cI, cQ)[0]
            tot += 1
    print(f"RESULT: {ok}/{tot} pass ({ncodes} fresh codes x {nspots} spots)")
    return ok, tot


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "make":
        make(int(sys.argv[2]) if len(sys.argv) > 2 else 500)
    elif len(sys.argv) == 3 and sys.argv[1] == "score":
        score(sys.argv[2])
    else:
        sys.exit(__doc__)

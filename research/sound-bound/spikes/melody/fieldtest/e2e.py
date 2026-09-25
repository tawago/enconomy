"""End-to-end test: two fake phones drive the real server over socket.io + HTTPS.

  python e2e.py --dist-cm 30 [--sr-a 48000 --sr-b 48000] [--room small] [--url https://127.0.0.1:5004]

Each phone joins, fetches its probes (the session's schedule order) from the server at its own rate, arms,
gets `start`, then the recordings are built with synth_field's room model from
the SERVER's probe audio (the client never sees the seed), uploaded as float32
WAV + meta, and the broadcast `result` is checked.  Exit 0 when every probe's
decision matches the label (<=30 NEAR, >=100 FAR).
"""

from __future__ import annotations

import argparse
import io
import json
import ssl
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf
import socketio
from scipy.signal import fftconvolve

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import synth_field as sfd  # noqa: E402
import fieldprobes as fp   # noqa: E402  plays() only (public schedule logic)

CTX = ssl._create_unverified_context()
RESULT_TIMEOUT_S = 180


def http(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
        return r.status, dict(r.headers), r.read()


def multipart(fields):
    b = uuid.uuid4().hex
    out = io.BytesIO()
    for name, (fname, body, ctype) in fields.items():
        out.write(f"--{b}\r\n".encode())
        disp = f'form-data; name="{name}"' + (f'; filename="{fname}"' if fname else "")
        out.write(f"Content-Disposition: {disp}\r\nContent-Type: {ctype}\r\n\r\n".encode())
        out.write(body if isinstance(body, bytes) else body.encode())
        out.write(b"\r\n")
    out.write(f"--{b}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={b}"


class Phone:
    def __init__(self, url, name, prefer, labels):
        self.url, self.name, self.prefer, self.labels = url, name, prefer, labels
        self.ev = {k: threading.Event() for k in ("joined_both", "start", "analyzing", "result")}
        self.data = {}
        self.sio = socketio.Client(ssl_verify=False)
        s = self.sio

        @s.on("joined")
        def _j(d):
            self.data["joined"] = d
            if d.get("partner_present"):
                self.ev["joined_both"].set()

        @s.on("start")
        def _s(d):
            self.data["start"] = d; self.ev["start"].set()

        @s.on("analyzing")
        def _a(d):
            self.ev["analyzing"].set()

        @s.on("result")
        def _r(d):
            self.data["result"] = d; self.ev["result"].set()

        @s.on("error_msg")
        def _e(d):
            print(f"[{name}] error_msg {d}", flush=True)

    def connect(self):
        self.sio.connect(self.url, transports=["websocket"], wait_timeout=10)
        self.sio.emit("join", {**self.labels, "prefer_role": self.prefer, "user_agent": f"e2e-{self.name}"})


def build_recordings(sid, roles_sr, codes, sched, dist_cm, room, noise, rng):
    """synth_field.simulate's model, but emitting the server-served codes."""
    ppm = {r: float(rng.uniform(-sfd.PPM_MAX, sfd.PPM_MAX)) for r in fp.ROLES}
    lat_out = {r: float(rng.uniform(*sfd.LAT_S)) for r in fp.ROLES}
    lat_in = {r: float(rng.uniform(*sfd.LAT_S)) for r in fp.ROLES}
    resid = {r: float(rng.uniform(-sfd.RESID_S, sfd.RESID_S)) for r in fp.ROLES}
    dist_m = sfd.TOUCH_M if dist_cm <= 0 else dist_cm / 100.0
    lead = sched["lead_s"]
    recs = {}
    for L in fp.ROLES:
        sr = roles_sr[L]
        n = int(round(sched["record_total_s"] * sr))
        buf = np.zeros(n)
        mic = sfd.color_fir(sfd._rng(sid, "mic", L, sr), sr)
        for E in fp.ROLES:
            spk = sfd.color_fir(sfd._rng(sid, "spk", E, sr), sr)
            r = sfd.SELF_M if E == L else dist_m
            h = sfd.rir(sfd._rng(sid, "rir", E, L), sfd.ROOMS[room], r, sr)
            path = fftconvolve(h, np.convolve(spk, mic))
            eps = 0.0 if E == L else (1 + ppm[L] * 1e-6) / (1 + ppm[E] * 1e-6) - 1
            cache = {}
            for pl in fp.plays(sched, E):
                p = pl["probe"]
                if p not in cache:
                    # E's code as E played it (E's rate), heard at L's rate: resample if rates differ
                    code = codes[E][p].astype(np.float64)
                    if roles_sr[E] != sr:
                        from scipy.signal import resample_poly
                        g = np.gcd(sr, roles_sr[E])
                        code = resample_poly(code, sr // g, roles_sr[E] // g)
                    cache[p] = fftconvolve(sfd.warp(sfd.mp.speaker(code, sr), eps), path)
                t = (lead + pl["offset_s"] + lat_out[E] + lat_in[L] + resid[E] - resid[L]
                     + r / sfd.C_M_S) * (1 + ppm[L] * 1e-6)
                sfd.add_delayed(buf, cache[p], t, sr)
        own = codes[L]["N1s"].astype(np.float64)
        ref = np.convolve(sfd.mp.speaker(own, sr), np.convolve(sfd.color_fir(sfd._rng(sid, "spk", L, sr), sr), mic))
        buf += sfd._noise(noise, n, sr, sfd._rng(sid, "noise", L), float(np.sqrt(np.mean(ref ** 2))))
        recs[L] = (buf * sfd.MIC_GAIN).astype(np.float32)
    return recs, {"ppm": ppm, "lat_out": lat_out, "lat_in": lat_in, "resid": resid}


def guard_sessions_dir(url):
    """Refuse to write fake-phone sessions next to field runs."""
    try:
        st, _, body = http(f"{url}/api/info")
        info = json.loads(body)
    except Exception as exc:
        raise SystemExit(f"e2e: {url}/api/info unavailable ({exc}); refusing (old server?)")
    if info.get("default_sessions_dir", True):
        raise SystemExit(f"e2e: server writes to {info.get('sessions_dir')} (field data); "
                         "start it with FIELD_SESSIONS_DIR=data/e2e, or use ./run.sh e2e")
    return info["sessions_dir"]


def run(url, dist_cm, sr_a, sr_b, room, noise):
    print(f"e2e sessions dir: {guard_sessions_dir(url)}")
    labels = {"label_cm": dist_cm, "room": room, "pose": "table", "noise": noise, "note": "e2e"}
    A, B = Phone(url, "A", "A", labels), Phone(url, "B", "B", labels)
    A.connect(); time.sleep(0.3); B.connect()
    for ph in (A, B):
        assert ph.ev["joined_both"].wait(10), f"{ph.name}: no pair"
    sid = A.data["joined"]["session_id"]
    roles = {ph.name: ph.data["joined"]["role"] for ph in (A, B)}
    assert roles == {"A": "A", "B": "B"}, roles
    assert B.data["joined"]["labels"]["label_cm"] == dist_cm
    rates = {"A": sr_a, "B": sr_b}
    codes = {}
    for r in fp.ROLES:
        codes[r] = {}
        for p in A.data["joined"]["probes"]:
            st, hd, body = http(f"{url}/api/probe/{sid}/{r}/{p}.f32?sr={rates[r]}")
            x = np.frombuffer(body, dtype="<f4")
            assert st == 200 and int(hd["X-Samples"]) == len(x) and int(hd["X-Sample-Rate"]) == rates[r]
            codes[r][p] = x
    for ph in (A, B):
        ph.sio.emit("arm", {"session_id": sid, "sample_rate": rates[ph.name]})
    for ph in (A, B):
        assert ph.ev["start"].wait(10), f"{ph.name}: no start"
    sched = A.data["start"]["schedule"]
    recs, scene = build_recordings(sid, rates, codes, sched, dist_cm, room, noise,
                                   np.random.default_rng(int(sid[:8], 16)))
    for ph in (A, B):
        r, sr = ph.name, rates[ph.name]
        start_ctx = 3.0 + (0.4 if r == "B" else 0.0)
        n = len(recs[r])
        meta = {
            "role": r, "sample_rate": sr, "capture_start_ctx_s": start_ctx - sched["lead_s"],
            "capture_frames": n, "start_ctx_s": start_ctx,
            "plays": [{"probe": d["probe"], "k": d["k"], "ctx_s": start_ctx + d["offset_s"], "clamped": False}
                      for d in fp.plays(sched, r)],
            "clock": {"server_offset_ms": scene["resid"][r] * 1000, "rtt_ms_min": 5.0, "samples": 10},
            "context": {"base_latency_s": None, "output_latency_s": None, "state": "running"},
            "track_settings": {"echoCancellation": False, "noiseSuppression": False,
                               "autoGainControl": False, "sampleRate": sr, "channelCount": 1},
            "blocks": {"count": n // 128, "frames": n, "discontinuities": 0, "missing_frames": 0},
            "probes_loaded": {p: {"n": len(codes[r][p]), "sr": sr} for p in codes[r]},
            "user_agent": f"e2e-{r}", "events": [],
        }
        wav = io.BytesIO()
        sf.write(wav, recs[r], sr, format="WAV", subtype="FLOAT")
        body, ctype = multipart({"wav": ("recording.wav", wav.getvalue(), "audio/wav"),
                                 "meta": (None, json.dumps(meta), "application/json")})
        st, _, resp = http(f"{url}/api/upload/{sid}/{r}", body, {"Content-Type": ctype})
        assert st == 200, resp
    t0 = time.time()
    for ph in (A, B):
        assert ph.ev["analyzing"].wait(10), f"{ph.name}: no analyzing"
    for ph in (A, B):
        assert ph.ev["result"].wait(RESULT_TIMEOUT_S), f"{ph.name}: no result"
    wall = time.time() - t0
    res = A.data["result"]["result"]
    st, _, body = http(f"{url}/api/result/{sid}")
    disk = json.loads(body)
    assert st == 200 and disk.get("session_id") == sid
    for ph in (A, B):
        ph.sio.disconnect()
    want = "NEAR" if dist_cm <= 30 else "FAR" if dist_cm >= 100 else None
    truth = dist_cm - 12 if dist_cm > 0 else 2 - 12
    ok = res.get("status") == "ok"
    print(f"session {sid}  {dist_cm} cm {room}/{noise}  sr A {sr_a} B {sr_b}  "
          f"ppm A {scene['ppm']['A']:+.0f} B {scene['ppm']['B']:+.0f}  status {res.get('status')} "
          f"analysis {res.get('runtime_s')} s, wall {wall:.1f} s  reasons {res.get('reasons')}")
    f1 = lambda v: "-" if v is None else f"{v:.1f}"
    for p in sched["order"]:
        pr = (res.get("probes") or {}).get(p) or {}
        for tag, d, s in (("first", pr.get("decision") or {}, pr.get("summary") or {}),
                          ("ownwalk", pr.get("decision_ownwalk") or {}, pr.get("summary_ownwalk") or {})):
            fm = s.get("flight_median")
            err = f"{fm - truth:+.1f}" if fm is not None else "-"
            good = want is None or d.get("label") == want
            ok &= good
            print(f"  {p:4s} {tag:7s} {d.get('label','?'):9s} flight {f1(fm)} (err {err})  spread {f1(s.get('spread'))}  "
                  f"usable {s.get('usable_rounds')}/{s.get('total_rounds')}  right% {f1(s.get('right_pct_median'))}  "
                  f"T {f1(pr.get('summary', {}).get('null_T_median'))}  minmargin {f1(s.get('min_margin_db'))} dB  "
                  f"{'OK' if good else 'WRONG'}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://127.0.0.1:5004")
    ap.add_argument("--dist-cm", type=float, default=30)
    ap.add_argument("--sr-a", type=int, default=48000)
    ap.add_argument("--sr-b", type=int, default=48000)
    ap.add_argument("--room", default="small")
    ap.add_argument("--noise", default="quiet")
    a = ap.parse_args()
    return 0 if run(a.url, a.dist_cm, a.sr_a, a.sr_b, a.room, a.noise) else 1


if __name__ == "__main__":
    sys.exit(main())

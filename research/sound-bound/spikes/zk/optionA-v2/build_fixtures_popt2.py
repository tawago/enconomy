"""POPT v2 fixtures (docs/pop-transcript-v2.md, 311 B) from the 12 JBL250 field sessions, signed by the
Secure Enclave keys of this Mac (../enclave/sesign), for the option A circuits.

  $PY build_fixtures_popt2.py [s8 ...]     # -> ../fixtures/popt_v2/<s8>_<mode>.json, build/popt2/*
  PY = research/proximity-echo/.venv/bin/python3

Modes: 48k (both phones 48 kHz) and mix (A 48 kHz, B 44.1 kHz: B's capture resampled, see ../enclave/emulate.py).
Per role, what the v2 app would do on its own int16 capture (2.5 s from t0 - 0.5 s):
  rec_root    rectree.py (Poseidon7, 4-ary, depth 4) over the int16 capture
  a_self      earliest lag with score >= 9 % (oa_rate twin at the phone's sr, own bed template) in the
              self search window; the window is the fieldtest's (expected -150 / +250 ms)
  a_partner   same with the partner template in the partner window; half = A: a_partner - a_self,
              B: a_self - a_partner
  p_partner   schedule-expected partner arrival (fieldtest "expected", contract §4.4 expected_partner)
  self_os_delta EMULATED, uniform in [-1 ms, +1 ms]; p_self = a_self - self_os_delta (no native timestamps)
  delta       DELTA_MS * sr / 1000 (2 ms)
  code_commit SHA-256("pop-code-v2" | int8 cI_self | cQ_self | cI_partner | cQ_partner) at the phone's sr
  commit      POPC v2 = "POPC" | 0x02 | role | attempt | nonce | rec_root, signed by the SE key
Credential: SBcred3 = "SBcred3" | X||Y | expiry u64 | Poseidon7(TAG_HOLD; holder secret) (dev issuer, openssl).
Tamper fixtures (signed for real): 180ca04b_48k_sodfar (B signs self_os_delta = 2,401 frames = 50.02 ms, over
the server tolerance) and 180ca04b_48k_sodwide (B signs 97 frames = 2.02 ms: inside the server's 50 ms but
outside the circuit's 2 ms self window, i.e. a completeness gap, not an attack).
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import random
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ZK = HERE.parent
sys.path.insert(0, str(ZK / "enclave"))
sys.path.insert(0, str(HERE / "poseidon7"))
import emulate as em  # noqa: E402
import popt  # noqa: E402
import p7  # noqa: E402
import oa_rate as R  # noqa: E402
import rectree  # noqa: E402
from build_popt_fixtures import dev_keys, issuer_pub, issuer_sign, sesign, verdict_exact, flight  # noqa: E402

OUT = ZK / "fixtures" / "popt_v2"
BUILD = HERE / "build" / "popt2"
ATTEMPT = 0
CRED_TTL_S = 30 * 86400
MODES = {"48k": {"A": 48_000, "B": 48_000}, "mix": {"A": 48_000, "B": 44_100}}


def holder_secret(sid, role):
    return int.from_bytes(hashlib.sha256(b"SBholder-dev|" + sid.encode() + role.encode()).digest()[:31], "big")


def dev_salt(nonce, role):
    return int.from_bytes(hashlib.sha256(b"POPsalt-dev|" + nonce + role.encode()).digest()[:31], "big")


def cred3(pub65, expiry, hold):
    return b"SBcred3" + pub65[1:] + struct.pack(">Q", expiry) + hold.to_bytes(32, "big")


def b64(b):
    return base64.b64encode(b).decode()


def analyse(d, s8, mode, r, sr, seed):
    """Capture + twin + tree for one listener. Cached in build/popt2."""
    o = "B" if r == "A" else "A"
    stem = BUILD / f"{s8}_{mode}_{r}"
    cap, cap_s, s48 = em.capture(d, r, sr)
    if (stem.with_suffix(".tree.json")).exists():
        lv = rectree.load(json.loads(stem.with_suffix(".tree.json").read_text()))
    else:
        lv = rectree.build(cap)
        stem.with_suffix(".tree.json").write_text(json.dumps(rectree.dump(lv)))
    np.save(stem.with_suffix(".npy"), cap.astype(np.int16))
    _, res = em.load(d)
    arr = res["probes"]["JBL250"]["rounds"][0]["arrivals"]
    P = R.params(sr)
    out = {"cap_s": cap_s, "s48": s48, "root": rectree.root(lv), "n": int(len(cap))}
    for kind, em_ in (("self", r), ("partner", o)):
        e = float(arr[f"{em_}_at_{r}"]["expected"]) - cap_s
        lo, hi = int(round((e - 0.150) * sr)), int(round((e + 0.250) * sr))
        cI, cQ = R.templates(seed, em_, sr)
        a, sc, *_ = R.earliest(cap, cI, cQ, lo, hi, sr)
        assert a is not None, (s8, mode, r, kind)
        out[kind] = {"a": a, "score": sc, "lo": lo, "hi": hi, "expected": int(round(e * sr))}
    assert out["partner"]["expected"] - P["WPRE"] <= out["partner"]["a"] <= out["partner"]["expected"] + P["WPOST"]
    return out


def build_one(d, mode, dev, iss, sod_override=None, tag=None):
    session, res = em.load(d)
    sid, seed = session["session_id"], session["seed_hex"]
    s8 = sid[:8]
    srs = MODES[mode]
    nonce = em.dev_nonce(sid + (f"|{tag}" if tag else ""), "v2-" + mode)
    expiry = int(dt.datetime.fromisoformat(session["created_at"]).timestamp()) + CRED_TTL_S
    rec = {"proto": "pop-v1+popt2", "session_id": hashlib.sha256(nonce).hexdigest()[:32], "field_session_id": sid,
           "seed_hex": seed, "label_cm": session["labels"]["label_cm"], "mode": mode, "session_nonce": nonce.hex(),
           "attempt": ATTEMPT, "issuer": {"pub_x": iss[0], "pub_y": iss[1]}, "roles": {}}
    halves = {}
    for r in "AB":
        o = "B" if r == "A" else "A"
        sr = srs[r]
        P = R.params(sr)
        an = analyse(d, s8, mode, r, sr, seed)
        a_self, a_part = an["self"]["a"], an["partner"]["a"]
        tol1 = int(round(0.001 * sr))
        sod = random.Random(f"pop-sod-v2|{sid}|{r}|{mode}").randint(-tol1, tol1)
        if sod_override is not None and r == "B":
            sod = sod_override
        p_self = a_self - sod
        # honest a_self must be the first crossing in [p_self - delta, a_self): the search window starts earlier
        assert an["self"]["lo"] <= p_self - P["DELTA"] or sod_override is not None
        h = em.half(r, a_self, a_part)
        halves[r] = h
        ts = em.timestamps(sid, r, "v2-" + mode, sr, an["cap_s"], a_self, sod=sod)
        tI, tQ = R.templates(seed, r, sr)
        pI, pQ = R.templates(seed, o, sr)
        cc = R.code_commit(tI, tQ, pI, pQ)
        root_b = an["root"].to_bytes(32, "big")
        commit = popt.popc(2, r, ATTEMPT, nonce, root_b)
        csig = sesign(dev[r]["blob"], commit)
        t = {"role": r, "attempt": ATTEMPT, "nonce": nonce, "pk_self": dev[r]["pub"], "pk_partner": dev[o]["pub"],
             "sample_rate": sr, "half": h, "rec": root_b, "commit_hash": hashlib.sha256(commit).digest(),
             **{k: ts[k] for k in ("play_frame_position", "play_nano_time", "rec_frame0_nano_time", "self_os_delta")},
             "a_self": a_self, "p_partner": an["partner"]["expected"], "delta": P["DELTA"], "code_commit": cc}
        raw = popt.encode(t, 2)
        dec = popt.decode(raw)
        assert len(raw) == popt.V2_LEN and dec["p_self"] == p_self and dec["a_partner"] == a_part
        sig = sesign(dev[r]["blob"], raw)
        hs = holder_secret(sid, r)
        hold = p7.sponge16(p7.TAG_HOLD, [hs])
        cred = cred3(dev[r]["pub"], expiry, hold)
        cr, cs = issuer_sign(cred)
        rec["roles"][r] = {
            "sample_rate": sr, "pubkey": dev[r]["pub"].hex(), "key_kind": dev[r]["key_kind"],
            "transcript_b64": b64(raw), "sig_b64": b64(sig), "commit_b64": b64(commit), "commit_sig_b64": b64(csig),
            "half": h, "a_self": a_self, "a_partner": a_part, "p_self": p_self, "p_partner": an["partner"]["expected"],
            "self_os_delta": sod, "delta": P["DELTA"], "rec_root": hex(an["root"]), "code_commit": cc.hex(),
            "score_self": an["self"]["score"], "score_partner": an["partner"]["score"],
            "search_self": [an["self"]["lo"], an["self"]["hi"]], "search_partner": [an["partner"]["lo"], an["partner"]["hi"]],
            "capture_frames": an["n"], "capture_start_s_in_file": an["cap_s"],
            "cred_hex": cred.hex(), "cred_expiry_unix": expiry, "cred_sig_r_hex": f"{cr:064x}",
            "cred_sig_s_hex": f"{cs:064x}", "holder_secret_dev": hex(hs), "holder_commit": hex(hold),
            "salt_dev": hex(dev_salt(nonce, r)), "capture_npy": f"optionA-v2/build/popt2/{s8}_{mode}_{r}.npy",
            "tree_json": f"optionA-v2/build/popt2/{s8}_{mode}_{r}.tree.json"}
    v, why = verdict_exact(halves["A"], srs["A"], halves["B"], srs["B"])
    rec["expect"] = {"flight_cm": round(flight(halves["A"], srs["A"], halves["B"], srs["B"]), 2), "verdict": v,
                     "reason": why}
    for r in "AB":
        x = rec["roles"][r]
        if abs(x["self_os_delta"]) * 1000 > 50 * x["sample_rate"]:
            rec["expect"].update({"verdict": None, "reason": "self_timestamp_mismatch"})
    rec["expect"]["zk_provable_pair"] = rec["expect"]["verdict"] == "NEAR" and all(
        abs(rec["roles"][r]["self_os_delta"]) <= rec["roles"][r]["delta"] for r in "AB")
    name = f"{s8}_{mode}" + (f"_{tag}" if tag else "")
    rec["name"] = name
    rec["notes"] = ("dev fixture: real audio (48 kHz field file; B resampled to 44.1 kHz in 'mix'), twin arrivals, "
                    "real Secure Enclave signatures; nonce/attempt/timestamps emulated (enclave/emulate.py)")
    (OUT / f"{name}.json").write_text(json.dumps(rec, indent=1))
    return rec


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    dev, iss = dev_keys(), issuer_pub()
    only = sys.argv[1:]
    for d in em.sessions():
        if only and d.name[:8] not in only:
            continue
        for mode in MODES:
            rec = build_one(d, mode, dev, iss)
            ra, rb = rec["roles"]["A"], rec["roles"]["B"]
            print(f"{rec['name']:14} label {rec['label_cm']:5.0f} sr {ra['sample_rate']}/{rb['sample_rate']} "
                  f"half {ra['half']:6d} {rb['half']:6d} flight {rec['expect']['flight_cm']:7.2f} "
                  f"{rec['expect']['verdict']} scores {ra['score_self']:.3f}/{ra['score_partner']:.3f} "
                  f"{rb['score_self']:.3f}/{rb['score_partner']:.3f}", flush=True)
    if not only or "180ca04b" in only:
        d = em.session_dir("180ca04b")
        for sod, tag in ((50 * 48 + 1, "sodfar"), (97, "sodwide")):
            rec = build_one(d, "48k", dev, iss, sod_override=sod, tag=tag)
            print(rec["name"], rec["expect"], flush=True)


if __name__ == "__main__":
    main()

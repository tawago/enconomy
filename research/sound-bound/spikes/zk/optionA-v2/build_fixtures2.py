"""Hardware-signed SBv2 fixtures (transcript v2) from the 12 JBL250 sessions, round 0.

  $PY build_fixtures2.py            # -> fixtures/<sess8>.json, build/trees/<sess8>_<R>.json

Per session and role R, and per delta in {1, 2, 5} ms (delta is signed, so one transcript per delta):
  rec_root   4-ary Poseidon7 Merkle root over the int16 recording (1,024-sample leaves)
  a_self     twin arrival of R's own sound in R's file (earliest score >= 9 % in the web window)
  a_partner  twin arrival of the partner's sound in R's file
  p_self     EMULATED: a_self - off, off uniform in [-delta, delta] (seeded per session/role/delta);
             the app would take it from native OS output timestamps (not available yet)
  p_partner  schedule-derived: start of the web search window + 150 ms (the window fieldanalysis uses)
  half       A: a_partner - a_self;  B: a_self - a_partner
  code_commit SHA-256("SBcode2" | int8 cI_self | cQ_self | cI_partner | cQ_partner)
Device signatures: the Secure Enclave keys of ../enclave (keys/A.seblob, keys/B.seblob) via ../enclave/sesign.
Credential: SBcred3 (Poseidon7 holder commitment), re-issued with the throwaway dev issuer key
(../enclave/keys/issuer_dev.pem) through the openssl CLI.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

from common2 import (DELTAS_MS, HERE, SR, WPRE, ZK, code_commit, cred_v3, delta_samples, flight_cm, low_s,
                     transcript_v2, verdict)
import p7
import twin2

ENC = ZK / "enclave"
FIX = HERE / "fixtures"
TREES = HERE / "build" / "trees"
ATTEMPT = 0
CRED_TTL_S = 30 * 86400


def sesign(blob, data: bytes):
    out = subprocess.run([str(ENC / "sesign"), "sign", str(blob), data.hex()], check=True, capture_output=True,
                         text=True).stdout
    return json.loads(out)


def der_rs(der: bytes):
    assert der[0] == 0x30
    i = 2 if der[1] < 0x80 else 2 + (der[1] & 0x7F)
    out = []
    for _ in range(2):
        assert der[i] == 0x02
        n = der[i + 1]
        out.append(int.from_bytes(der[i + 2: i + 2 + n], "big"))
        i += 2 + n
    return out


def issuer_sign(msg: bytes):
    der = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(ENC / "keys" / "issuer_dev.pem"), "-binary"],
                         input=msg, check=True, capture_output=True).stdout
    return der_rs(der)


def issuer_pub():
    pem = subprocess.run(["openssl", "ec", "-in", str(ENC / "keys" / "issuer_dev.pem"), "-pubout", "-outform", "DER"],
                         check=True, capture_output=True).stdout
    pt = pem[-65:]
    assert pt[0] == 4
    return pt[1:33].hex(), pt[33:].hex()


def holder_secret(sid, role):
    return int.from_bytes(hashlib.sha256(b"SBholder-dev|" + sid.encode() + role.encode()).digest()[:31], "big")


def dev_salt(sid, role):
    return int.from_bytes(hashlib.sha256(b"SBsalt-dev|" + sid.encode() + role.encode()).digest()[:31], "big")


def tree(sess8, role, x):
    TREES.mkdir(parents=True, exist_ok=True)
    f = TREES / f"{sess8}_{role}.json"
    if f.exists():
        d = json.loads(f.read_text())
        return [{int(k): int(v, 16) for k, v in lvl.items()} for lvl in d["levels"]]
    levels = p7.build_tree(x, procs=4)
    f.write_text(json.dumps({"n_samples": len(x), "levels": [{k: hex(v) for k, v in lvl.items()} for lvl in levels]}))
    return levels


def main():
    FIX.mkdir(exist_ok=True)
    dev = {r: json.loads((ENC / "keys" / f"{r}.seblob.json").read_text()) for r in "AB"}
    pubs = {r: bytes.fromhex(dev[r]["pub_x"] + dev[r]["pub_y"]) for r in "AB"}
    ix, iy = issuer_pub()
    rows = []
    for d in twin2.tw1.sessions():
        s8 = d.name[:8]
        _, session, res, rec, x, tpl = twin2.load(s8)
        sid = session["session_id"]
        arr = twin2.arrivals(s8, 0)
        nonce = hashlib.sha256(b"SBnonce1" + sid.encode()).digest()
        created = dt.datetime.fromisoformat(session["created_at"])
        expiry = int(created.timestamp()) + CRED_TTL_S
        sch = session["schedule"]
        pr = sch["probes"]["JBL250"]
        base_ns = int(round(sch["start_server_ms"] * 1e6))
        play_s = {"A": sch["lead_s"] + pr["start_s"]}
        play_s["B"] = play_s["A"] + pr["b_offset_s"]
        roots = {}
        for r in "AB":
            lv = tree(s8, r, x[r])
            roots[r] = p7.root(lv)
        fx = {"session_id": sid, "label_cm": session["labels"]["label_cm"], "sr": SR, "probe": "JBL250", "round": 0,
              "nonce_hex": nonce.hex(), "attempt": ATTEMPT, "issuer": {"pub_x": ix, "pub_y": iy},
              "note": "p_self emulated (twin self arrival - uniform offset in [-delta, delta]); p_partner = web "
                      "window start + 150 ms (schedule); os_ts placeholder",
              "deltas": {}}
        for dms in DELTAS_MS:
            dl = delta_samples(dms)
            fx["deltas"][str(dms)] = {}
            halves = {}
            for r in "AB":
                o = "B" if r == "A" else "A"
                a_self = arr[f"{r}_at_{r}"]["n"]
                a_part = arr[f"{o}_at_{r}"]["n"]
                p_part = arr[f"{o}_at_{r}"]["lo"] + WPRE
                rng = random.Random(f"{sid}|{r}|{dl}")
                off = rng.randint(-dl, dl)
                p_self = a_self - off
                half = a_part - a_self if r == "A" else a_self - a_part
                halves[r] = half
                cc = code_commit(*tpl[r], *tpl[o])
                ts = [base_ns + int(round(play_s[r] * 1e9))]
                tr = transcript_v2(nonce, ATTEMPT, r, pubs[r], pubs[o], SR, half, roots[r], p_self, p_part, dl,
                                   a_self, a_part, cc, ts)
                assert len(tr) == 265
                sg = sesign(ENC / "keys" / f"{r}.seblob", tr)
                assert sg["digest"] == hashlib.sha256(tr).hexdigest()
                R_, S_, fl = low_s(int(sg["r"], 16), int(sg["s"], 16))
                hs = holder_secret(sid, r)
                hcm = p7.sponge16(p7.TAG_HOLD, [hs])
                cred = cred_v3(pubs[r], expiry, hcm)
                cr, cs = issuer_sign(cred)
                cr, cs, cfl = low_s(cr, cs)
                fx["deltas"][str(dms)][r] = {
                    "device_pub_x": dev[r]["pub_x"], "device_pub_y": dev[r]["pub_y"], "key_kind": dev[r]["key_kind"],
                    "half": half, "rec_root": hex(roots[r]), "p_self": p_self, "p_self_offset": off,
                    "p_partner": p_part, "delta": dl, "a_self": a_self, "a_partner": a_part,
                    "code_commit": cc.hex(), "os_ts": ts, "transcript_hex": tr.hex(),
                    "digest_hex": sg["digest"], "sig_r_hex": f"{R_:064x}", "sig_s_hex": f"{S_:064x}",
                    "sig_low_s_normalized": fl, "cred_hex": cred.hex(), "cred_expiry_unix": expiry,
                    "cred_sig_r_hex": f"{cr:064x}", "cred_sig_s_hex": f"{cs:064x}",
                    "holder_secret_dev": hex(hs), "holder_commit": hex(hcm), "salt_dev": hex(dev_salt(sid, r)),
                }
            fl_ = flight_cm(halves["A"], halves["B"])
            fx["deltas"][str(dms)]["flight_cm"] = fl_
            fx["deltas"][str(dms)]["verdict"] = verdict(fl_)
        (FIX / f"{s8}.json").write_text(json.dumps(fx, indent=1))
        f1 = fx["deltas"]["1"]
        rows.append((s8, fx["label_cm"], f1["A"]["half"], f1["B"]["half"], f1["flight_cm"], f1["verdict"]))
        print(f"{s8} label {fx['label_cm']:5.0f} halfA {f1['A']['half']} halfB {f1['B']['half']} "
              f"flight {f1['flight_cm']:7.2f} {f1['verdict']}  rootA {hex(roots['A'])[:12]}..", flush=True)


if __name__ == "__main__":
    main()

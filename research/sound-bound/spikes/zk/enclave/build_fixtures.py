"""Build hardware-signed SBv1 fixtures from real JBL250 fieldtest sessions.

Usage: .venv/bin/python build_fixtures.py [--software] [--new-keys]

Device keys A and B: Secure Enclave P-256 on this Mac via ./sesign (SE-wrapped handles in
keys/*.seblob, useless off this machine). Issuer: throwaway software P-256 in keys/issuer_dev.pem.
"""
import datetime as dt
import glob
import hashlib
import json
import os
import subprocess
import sys

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from common import credential, flight_cm, low_s, transcript, verdict

HERE = os.path.dirname(os.path.abspath(__file__))
ZK = os.path.dirname(HERE)
SESSIONS = os.path.join(ZK, "..", "melody", "fieldtest", "data", "sessions")
OUT = os.path.join(ZK, "fixtures")
KEYS = os.path.join(HERE, "keys")
SESIGN = os.path.join(HERE, "sesign")
PROBE = "JBL250"
ROUND = 0
ATTEMPT = 0
CRED_TTL_S = 30 * 86400

software = "--software" in sys.argv
new_keys = "--new-keys" in sys.argv
flag = ["--software"] if software else []


def sesign(*a) -> dict:
    return json.loads(subprocess.run([SESIGN, *flag, *a], check=True, capture_output=True, text=True).stdout)


def device_key(role: str) -> dict:
    blob = os.path.join(KEYS, f"{role}.{'swkey' if software else 'seblob'}")
    meta = blob + ".json"
    if new_keys or not os.path.exists(meta):
        info = sesign("keygen", blob)
        json.dump(info, open(meta, "w"))
    info = json.load(open(meta))
    info["blob"] = blob
    return info


def issuer_key() -> ec.EllipticCurvePrivateKey:
    p = os.path.join(KEYS, "issuer_dev.pem")
    if new_keys or not os.path.exists(p):
        k = ec.generate_private_key(ec.SECP256R1())
        open(p, "wb").write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()))
    return serialization.load_pem_private_key(open(p, "rb").read(), None)


def xy(pub_x: str, pub_y: str) -> bytes:
    return bytes.fromhex(pub_x) + bytes.fromhex(pub_y)


def to_samples(t: float, sr: int) -> int:
    v = t * sr
    assert abs(v - round(v)) < 1e-3, f"arrival {t} s not on the sample grid ({v})"
    return round(v)


def main():
    os.makedirs(KEYS, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    dev = {r: device_key(r) for r in "AB"}
    iss = issuer_key()
    iss_nums = iss.public_key().public_numbers()
    iss_pub = {"pub_x": f"{iss_nums.x:064x}", "pub_y": f"{iss_nums.y:064x}"}
    pubs = {r: xy(dev[r]["pub_x"], dev[r]["pub_y"]) for r in "AB"}

    rows = []
    for d in sorted(glob.glob(os.path.join(SESSIONS, "*"))):
        rp = os.path.join(d, "result.json")
        if not os.path.exists(rp):
            continue
        res = json.load(open(rp))
        if PROBE not in res.get("probes", {}):
            continue
        ses = json.load(open(os.path.join(d, "session.json")))
        sid = ses["session_id"]
        sr = int(res["quality"]["A"]["sample_rate"])
        assert sr == int(res["quality"]["B"]["sample_rate"])
        rd = res["probes"][PROBE]["rounds"][ROUND]
        a = rd["arrivals"]
        # Each phone's half from its own file only.
        half = {"A": to_samples(a["B_at_A"]["t"], sr) - to_samples(a["A_at_A"]["t"], sr),
                "B": to_samples(a["B_at_B"]["t"], sr) - to_samples(a["A_at_B"]["t"], sr)}
        fl = flight_cm(half["A"], half["B"], sr)
        ver = verdict(fl)

        # Dev nonce: deterministic from the session id (real one comes from the server).
        nonce = hashlib.sha256(b"SBnonce1" + sid.encode()).digest()
        # Placeholder OS output timestamps (ns): server start + scheduled play offset.
        sch = ses["schedule"]
        pr = sch["probes"][PROBE]
        base_ns = int(round(sch["start_server_ms"] * 1e6))
        play_s = {"A": sch["lead_s"] + pr["start_s"] + ROUND * pr["period_s"]}
        play_s["B"] = play_s["A"] + pr["b_offset_s"]
        created = dt.datetime.fromisoformat(ses["created_at"])
        expiry = int(created.timestamp()) + CRED_TTL_S

        roles = {}
        for r in "AB":
            p = "B" if r == "A" else "A"
            wav = os.path.join(d, f"recording_{r}.wav")
            rec_hash = hashlib.sha256(open(wav, "rb").read()).digest()
            ts = [base_ns + int(round(play_s[r] * 1e9))]
            tr = transcript(nonce, ATTEMPT, r, pubs[r], pubs[p], sr, half[r], rec_hash, ts)
            digest = hashlib.sha256(tr).digest()
            sg = sesign("sign", dev[r]["blob"], tr.hex())
            assert sg["digest"] == digest.hex()
            R, S, flipped = low_s(int(sg["r"], 16), int(sg["s"], 16))

            cred = credential(pubs[r], expiry)
            cred_digest = hashlib.sha256(cred).digest()
            cr, cs = decode_dss_signature(iss.sign(cred, ec.ECDSA(hashes.SHA256())))
            cr, cs, cflipped = low_s(cr, cs)

            roles[r] = {
                "device_pub_x": dev[r]["pub_x"], "device_pub_y": dev[r]["pub_y"],
                "key_kind": dev[r]["key_kind"],
                "half_samples": half[r], "rec_hash_hex": rec_hash.hex(), "os_ts": ts,
                "os_ts_note": "placeholder: start_server_ms + scheduled play offset, not a real OS timestamp",
                "transcript_hex": tr.hex(), "digest_hex": digest.hex(),
                "sig_r_hex": f"{R:064x}", "sig_s_hex": f"{S:064x}", "sig_low_s_normalized": flipped,
                "cred_hex": cred.hex(), "cred_expiry_unix": expiry, "cred_digest_hex": cred_digest.hex(),
                "cred_sig_r_hex": f"{cr:064x}", "cred_sig_s_hex": f"{cs:064x}", "cred_sig_low_s_normalized": cflipped,
            }

        fx = {
            "session_id": sid, "label_cm": ses["labels"]["label_cm"], "sr": sr,
            "probe": PROBE, "round": ROUND,
            "nonce_hex": nonce.hex(), "nonce_note": "dev: sha256('SBnonce1'||session_id)",
            "attempt": ATTEMPT, "issuer": iss_pub, "roles": roles,
            "flight_cm": fl, "verdict": ver,
            "result_json_flight_cm": rd["flight_cm"], "result_json_flight_raw_cm": rd["flight_raw_cm"],
            "result_json_drift_cm": rd["drift_cm"], "result_json_usable": rd["usable"],
        }
        path = os.path.join(OUT, f"{sid[:8]}.json")
        json.dump(fx, open(path, "w"), indent=1)
        rows.append((sid[:8], ses["labels"]["label_cm"], half["A"], half["B"], fl, ver,
                     rd["flight_cm"], rd["flight_raw_cm"], rd["usable"],
                     roles["A"]["sig_low_s_normalized"], roles["B"]["sig_low_s_normalized"]))

    print(f"key_kind A={dev['A']['key_kind']} B={dev['B']['key_kind']}  fixtures={len(rows)}")
    print(f"{'sess':8} {'label':>5} {'halfA':>6} {'halfB':>6} {'flight':>8} {'verdict':8} {'res':>8} {'raw':>8} "
          f"{'|d|':>7} {'|draw|':>7} usable lowS(A,B)")
    for s, lab, ha, hb, fl, v, rf, rr, u, fa, fb in rows:
        print(f"{s:8} {lab:5.0f} {ha:6d} {hb:6d} {fl:8.3f} {v:8} {rf:8.3f} {rr:8.3f} "
              f"{abs(fl - rf):7.4f} {abs(fl - rr):7.4f} {u!s:6} {fa},{fb}")
    print(f"max |flight - result.flight_cm|     = {max(abs(r[4] - r[6]) for r in rows):.6f} cm")
    print(f"max |flight - result.flight_raw_cm| = {max(abs(r[4] - r[7]) for r in rows):.6f} cm")


if __name__ == "__main__":
    main()

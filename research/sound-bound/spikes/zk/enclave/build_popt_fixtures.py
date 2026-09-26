"""POPT v1 fixtures (docs/pop-contract.md §7.1, 269 B) from the 12 JBL250 field sessions, signed by the
Secure Enclave keys of this Mac (./sesign, keys/A.seblob, keys/B.seblob).

  research/proximity-echo/.venv/bin/python3 build_popt_fixtures.py      # -> ../fixtures/popt_v1/*.json

Modes per session:
  48k   both phones at 48,000 Hz (the field sample rate)
  mix   A at 48,000 Hz, B at 44,100 Hz: B's capture is resampled, B's arrivals mapped to 44.1 kHz frames
See emulate.py for what is real (audio, arrival times) and what is emulated (timestamps, nonce, attempt).

Each file is a contract §8.4 result record (+ "commits", which server/pop/verdict.verify_record reads)
plus what the ZK side needs: SBcred1 credentials from the dev issuer (keys/issuer_dev.pem, via the
openssl CLI) and the emulation diagnostics. The SE signatures are kept exactly as the enclave returned
them (raw r||s, not low-S normalized: the contract does not require low-S).

Extra tamper fixtures (signed for real, for the reject tests):
  180ca04b_48k_selfpair   one SE key (A's) signs both roles, pk_self == pk_partner
  180ca04b_48k_sodfar     B signs self_os_delta = SELF_OS_TOL_MS*sr/1000 + 1 frames (over tolerance)
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

import emulate as em
import popt

HERE = Path(__file__).resolve().parent
OUT = em.ZK / "fixtures" / "popt_v1"
KEYS = HERE / "keys"
ATTEMPT = 0
CRED_TTL_S = 30 * 86400
MODES = {"48k": {"A": 48_000, "B": 48_000}, "mix": {"A": 48_000, "B": 44_100}}
C_CM_S, NEAR_CM, IMPOSSIBLE_CM, SELF_OS_TOL_MS = 34300, 60, -20, 50   # server/pop/constants.py (checked in tests)


def sesign(blob: Path, data: bytes) -> bytes:
    o = json.loads(subprocess.run([str(HERE / "sesign"), "sign", str(blob), data.hex()], check=True,
                                  capture_output=True, text=True).stdout)
    assert o["digest"] == hashlib.sha256(data).hexdigest()
    return bytes.fromhex(o["r"]) + bytes.fromhex(o["s"])


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
    der = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(KEYS / "issuer_dev.pem"), "-binary"],
                         input=msg, check=True, capture_output=True).stdout
    return der_rs(der)


def issuer_pub():
    der = subprocess.run(["openssl", "ec", "-in", str(KEYS / "issuer_dev.pem"), "-pubout", "-outform", "DER"],
                         check=True, capture_output=True).stdout
    pt = der[-65:]
    assert pt[0] == 4
    return pt[1:33].hex(), pt[33:].hex()


def dev_keys():
    k = {r: json.loads((KEYS / f"{r}.seblob.json").read_text()) for r in "AB"}
    return {r: {"blob": KEYS / f"{r}.seblob", "pub": popt.pub65(k[r]["pub_x"], k[r]["pub_y"]),
                "key_kind": k[r]["key_kind"]} for r in "AB"}


def credential(pub65: bytes, expiry: int) -> bytes:
    return b"SBcred1" + pub65[1:] + struct.pack(">Q", expiry)


def flight(ha, sa, hb, sb):
    return C_CM_S / 2 * (ha / sa - hb / sb)


def verdict_exact(ha, sa, hb, sb):
    """Integer form of server decide(): NEAR iff -20 < flight < 60 (flight <= -20: impossible_flight)."""
    n, s = ha * sb - hb * sa, sa * sb
    if C_CM_S * n <= 2 * IMPOSSIBLE_CM * s:
        return None, "impossible_flight"
    if C_CM_S * n >= 2 * NEAR_CM * s:
        return "NOT_NEAR", "too_far"
    return "NEAR", None


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def build_one(d: Path, mode: str, dev, iss, *, selfpair=False, sod_override=None, tag=None):
    session, res = em.load(d)
    sid = session["session_id"]
    s8 = sid[:8]
    srs = MODES[mode]
    nonce = em.dev_nonce(sid + (f"|{tag}" if tag else ""), mode)
    created = dt.datetime.fromisoformat(session["created_at"])
    expiry = int(created.timestamp()) + CRED_TTL_S
    keys = {r: (dev["A"] if selfpair else dev[r]) for r in "AB"}
    rec = {"proto": "pop-v1", "session_id": hashlib.sha256(nonce).hexdigest()[:32],
           "field_session_id": sid, "label_cm": session["labels"]["label_cm"], "mode": mode,
           "session_nonce": nonce.hex(), "attempt": ATTEMPT, "devices": {}, "transcripts": {}, "commits": {},
           "credentials": {}, "issuer": {"pub_x": iss[0], "pub_y": iss[1]}, "emulation": {}}
    for r in "AB":
        o = "B" if r == "A" else "A"
        sr = srs[r]
        cap, cap_s, s48 = em.capture(d, r, sr)
        rec_sha = hashlib.sha256(cap.astype("<i2").tobytes()).digest()
        arr = em.field_arrivals(d, r, sr, cap_s)
        h = em.half(r, arr["self"], arr["partner"])
        ts = em.timestamps(sid, r, mode, sr, cap_s, arr["self"],
                           sod=sod_override if (sod_override is not None and r == "B") else None)
        commit = popt.popc(1, r, ATTEMPT, nonce, rec_sha)
        csig = sesign(keys[r]["blob"], commit)
        t = {"role": r, "attempt": ATTEMPT, "nonce": nonce, "pk_self": keys[r]["pub"], "pk_partner": keys[o]["pub"],
             "sample_rate": sr, "half": h, "rec": rec_sha, "commit_hash": hashlib.sha256(commit).digest(),
             **{k: ts[k] for k in ("play_frame_position", "play_nano_time", "rec_frame0_nano_time", "self_os_delta")}}
        raw = popt.encode(t, 1)
        assert len(raw) == popt.V1_LEN and popt.decode(raw)["half"] == h
        sig = sesign(keys[r]["blob"], raw)
        cred = credential(keys[r]["pub"], expiry)
        cr, cs = issuer_sign(cred)
        pub = keys[r]["pub"]
        rec["devices"][r] = {"device_id": hashlib.sha256(pub).hexdigest()[:32], "pubkey": pub.hex(),
                             "key_kind": keys[r]["key_kind"], "sample_rate": sr, "half": h}
        rec["transcripts"][r] = {"transcript_b64": b64(raw), "sig_b64": b64(sig),
                                 "sha256": hashlib.sha256(raw).hexdigest()}
        rec["commits"][r] = {"commit_b64": b64(commit), "sig_b64": b64(csig)}
        rec["credentials"][r] = {"cred_hex": cred.hex(), "expiry": expiry, "sig_r_hex": f"{cr:064x}",
                                 "sig_s_hex": f"{cs:064x}"}
        rec["emulation"][r] = {"sr": sr, "capture_start_s_in_file": cap_s, "capture_start_frame48": s48,
                               "capture_frames": int(len(cap)), "t_self": arr["self"], "t_partner": arr["partner"],
                               "expected_self": ts["expected_self"], "self_os_delta": ts["self_os_delta"],
                               "clock_base_ns": ts["clock_base_ns"],
                               "sig_low_s": popt.low_s(int.from_bytes(sig[32:], "big"))}
    ha, hb = rec["devices"]["A"]["half"], rec["devices"]["B"]["half"]
    sa, sb = srs["A"], srs["B"]
    v, why = verdict_exact(ha, sa, hb, sb)
    tol_ok = all(abs(rec["emulation"][r]["self_os_delta"]) * 1000 <= SELF_OS_TOL_MS * srs[r] for r in "AB")
    rec["expect"] = {"flight_cm": round(flight(ha, sa, hb, sb), 2),
                     "verdict": v if tol_ok else None, "reason": why if tol_ok else "self_timestamp_mismatch",
                     "near": v == "NEAR" and tol_ok and not selfpair}
    if selfpair:
        rec["expect"]["note"] = "self-pair: server combine() rejects (transcript_mismatch: pk_self equal)"
    name = f"{s8}_{mode}" + (f"_{tag}" if tag else "")
    rec["name"] = name
    rec["notes"] = ("dev fixture: real audio + real Secure Enclave signatures; nonce = sha256('POPnonce-dev|' "
                    "session|mode), attempt 0, timestamps emulated (enclave/emulate.py)")
    (OUT / f"{name}.json").write_text(json.dumps(rec, indent=1))
    return rec


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dev = dev_keys()
    iss = issuer_pub()
    rows = []
    for d in em.sessions():
        for mode in MODES:
            rec = build_one(d, mode, dev, iss)
            rows.append(rec)
            e = rec["expect"]
            print(f"{rec['name']:14} label {rec['label_cm']:5.0f}  sr {rec['devices']['A']['sample_rate']}/"
                  f"{rec['devices']['B']['sample_rate']}  half {rec['devices']['A']['half']:6d} "
                  f"{rec['devices']['B']['half']:6d}  flight {e['flight_cm']:7.2f}  {e['verdict']} {e['reason']}",
                  flush=True)
    d = em.session_dir("180ca04b")
    tol = SELF_OS_TOL_MS * 48_000 // 1000
    for kw in ({"selfpair": True, "tag": "selfpair"}, {"sod_override": tol + 1, "tag": "sodfar"},
               {"sod_override": tol, "tag": "sodedge"}):
        rec = build_one(d, "48k", dev, iss, **kw)
        print(f"{rec['name']:22} {rec['expect']}", flush=True)
    print(f"{len(rows)} fixtures + 3 tamper fixtures in {OUT}")


if __name__ == "__main__":
    sys.exit(main())

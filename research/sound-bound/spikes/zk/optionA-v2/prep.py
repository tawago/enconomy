"""Fixture v2 -> circuit input JSON + expected public values (circom order: outputs, then public inputs
in declaration order).

  $PY prep.py <sess8> <delta_ms> <A|B> <sig|audio> [--tamper NAME] [--win w400] [--out inputs]
  $PY prep.py pair <sess8> <delta_ms>                     # pair statement input from the two fixtures

Tamper modes (the expected public values stay the honest ones):
  late_self      claim a_self at p_self + delta (latest the window allows); half adjusted
  echo_self      claim a_self at the strongest peak after the true arrival inside the window
  early_partner  claim a_partner 100 samples (2.1 ms) earlier, no peak there; half adjusted
  score          one claimed self score I_j + 1
  sample         one opened sample + 1 (self region, inside the used span)
  sample_range   one opened sample set to 40000 (outside int16)
  path           one off-path child in a Merkle path changed
  leafidx        self region claimed one leaf later (samples and paths of the next leaf)
  swap_role      roleB flipped (sign convention) with the same signed data
  template       own and partner templates (and code_commit) from another session
  pself          p_self differs from the signed value by +200 samples (window start moved later)
  aself_outside  a_self = p_self + delta + 1 with the curve widened (audio variant only)
  resign_late    compromised app: late_self signed by the Secure Enclave (valid signature)
  resign_early   compromised app: early_partner signed by the Secure Enclave (valid signature)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np

from common2 import (HERE, HM, L, N_ORDER, P, PARTNER_WINDOWS_MS, SR, code_commit, delta_samples, geometry,
                     transcript_v2)
import p7
import twin2

FIX = HERE / "fixtures"
TREES = HERE / "build" / "trees"
VALID_AT = 1790000000
TAMPERS = ["none", "late_self", "echo_self", "early_partner", "score", "sample", "sample_range", "path",
           "leafidx", "swap_role", "template", "pself", "aself_outside", "resign_late", "resign_early"]
_trees = {}


def levels(s8, r):
    if (s8, r) not in _trees:
        d = json.loads((TREES / f"{s8}_{r}.json").read_text())
        _trees[(s8, r)] = [{int(k): int(v, 16) for k, v in lvl.items()} for lvl in d["levels"]]
    return _trees[(s8, r)]


def fe(v):
    return str(int(v) % P)


def sinv(s):
    return str(pow(s % N_ORDER, -1, N_ORDER))


def open_region(x, lv, first, nl):
    xs, ch = [], []
    for i in range(nl):
        a = (first + i) * 1024
        seg = [int(v) for v in x[a: a + 1024]]
        seg += [0] * (1024 - len(seg))
        xs.append(seg)
        ch.append(p7.path(lv, first + i))
    return xs, ch


def self_curve(x, cI, cQ, p_self, delta, K):
    lo = p_self - delta
    return twin2.curve(x[lo - HM: lo + K + L - 1 + HM], cI, cQ, K)


def resign(fr, r, fields):
    """Compromised-app model: the enclave signs whatever transcript the app builds."""
    import build_fixtures2 as bf
    from common2 import ZK
    nonce = bytes.fromhex(fr["_nonce"])
    tr = transcript_v2(nonce, fr["_attempt"], r, bytes.fromhex(fr["device_pub_x"] + fr["device_pub_y"]),
                       bytes.fromhex(fr["_partner_pub"]), SR, fields["half"], int(fr["rec_root"], 16),
                       fields["p_self"], fr["p_partner"], fr["delta"], fields["a_self"], fields["a_partner"],
                       bytes.fromhex(fr["code_commit"]), fr["os_ts"])
    sg = bf.sesign(ZK / "enclave" / "keys" / f"{r}.seblob", tr)
    from common2 import low_s
    R_, S_, _ = low_s(int(sg["r"], 16), int(sg["s"], 16))
    return R_, S_


def build(s8, dms, role, variant, tamper="none", win="w400"):
    fx = json.loads((FIX / f"{s8}.json").read_text())
    fr = dict(fx["deltas"][str(dms)][role])
    other = "B" if role == "A" else "A"
    fr["_nonce"], fr["_attempt"] = fx["nonce_hex"], fx["attempt"]
    fr["_partner_pub"] = fx["deltas"][str(dms)][other]["device_pub_x"] + fx["deltas"][str(dms)][other]["device_pub_y"]
    delta = delta_samples(dms)
    g = geometry(delta)
    K, NLS, NLP = g["K"], g["NLS"], g["NLP"]
    _, session, res, rec, xall, tpl = twin2.load(s8)
    x = xall[role]
    lv = levels(s8, role)
    root = p7.root(lv)
    assert hex(root) == fr["rec_root"]
    cIs, cQs = tpl[role]
    cIp, cQp = tpl[other]
    roleB = 1 if role == "B" else 0
    p_self, p_part, a_self, a_part = fr["p_self"], fr["p_partner"], fr["a_self"], fr["a_partner"]
    half = fr["half"]
    nonce = bytes.fromhex(fx["nonce_hex"])
    nh, nl = int.from_bytes(nonce[:16], "big"), int.from_bytes(nonce[16:], "big")
    cc = bytes.fromhex(fr["code_commit"])
    salt = int(fr["salt_dev"], 16)
    sig_r, sig_s = int(fr["sig_r_hex"], 16), int(fr["sig_s_hex"], 16)
    info = {"session": s8, "label_cm": fx["label_cm"], "delta_ms": dms, "role": role, "variant": variant,
            "tamper": tamper, "honest_half": half}

    # ---- honest witness pieces, then tamper
    sig_p_self = p_self                       # what the transcript bytes carry
    I, Q, E = self_curve(x, cIs, cQs, p_self, delta, K)
    cn2 = int(np.dot(cIs, cIs))
    ok = twin2.passes(I, Q, E, cn2)
    j_true = a_self - (p_self - delta)
    assert 0 <= j_true < K and ok[j_true] and not any(ok[:j_true]), "honest self arrival not first in window"
    claim_self, claim_part = a_self, a_part
    if tamper in ("late_self", "resign_late"):
        claim_self = p_self + delta
    elif tamper == "echo_self":
        later = [j for j in range(j_true + 1, K) if ok[j]]
        sc = twin2.score(I, Q, E, cn2)
        jbest = max(later, key=lambda j: sc[j]) if later else K - 1
        claim_self = p_self - delta + jbest
        info["echo_lag_after_arrival"] = jbest - j_true
        info["echo_score"] = sc[jbest]
    elif tamper in ("early_partner", "resign_early"):
        claim_part = a_part - 100
    elif tamper == "aself_outside":
        claim_self = p_self + delta + 1
    if claim_self != a_self or claim_part != a_part:
        half = claim_part - claim_self if role == "A" else claim_self - claim_part
        info["claimed_half"] = half
    if tamper in ("resign_late", "resign_early"):
        sig_r, sig_s = resign(fr, role, {"half": half, "p_self": p_self, "a_self": claim_self, "a_partner": claim_part})
    ja = claim_self - (p_self - delta)
    u = [1 if j < ja else 0 for j in range(K)]

    leafS = (p_self - delta - HM) // 1024
    leafP = (claim_part - HM) // 1024
    xs, chS = open_region(x, lv, leafS, NLS)
    xp, chP = open_region(x, lv, leafP, NLP)
    if tamper == "leafidx":
        leafS += 1
        xs, chS = open_region(x, lv, leafS, NLS)
    if tamper == "score":
        I = list(I)
        I[max(j_true - 3, 0)] += 1
    if tamper == "sample":
        xs[1][500] += 1
    if tamper == "sample_range":
        xs[1][500] = 40000
    if tamper == "path":
        chS[2][3][(leafS + 2) // 4 ** 3 % 4 ^ 1] += 1
    if tamper == "pself":
        p_self = p_self + 200                 # prover's window start; the signature covers sig_p_self
        leafS = (p_self - delta - HM) // 1024
        xs, chS = open_region(x, lv, leafS, NLS)
        I, Q, E = self_curve(x, cIs, cQs, p_self, delta, K)
        okp = twin2.passes(I, Q, E, cn2)
        # the window now starts after the true arrival: pick the first crossing inside the moved window
        jp = next((j for j in range(K) if okp[j]), K - 1)
        claim_self = p_self - delta + jp
        u = [1 if j < jp else 0 for j in range(K)]
        half = claim_part - claim_self if role == "A" else claim_self - claim_part
        info["claimed_half"] = half
        if variant == "audio":
            sig_p_self = p_self               # audio variant: pSelf is public, the verifier pins it
    if tamper == "swap_role":
        roleB = 1 - roleB
    if tamper == "template":
        other_s8 = "2940913c" if s8 != "2940913c" else "180ca04b"
        _, _, _, _, _, tpl2 = twin2.load(other_s8)
        cIs, cQs = tpl2[role]
        cIp, cQp = tpl2[other]
        cc = code_commit(cIs, cQs, cIp, cQp)
        I, Q, E = self_curve(x, cIs, cQs, p_self, delta, K)
        info["other_session"] = other_s8

    code_hi, code_lo = int.from_bytes(cc[:16], "big"), int.from_bytes(cc[16:], "big")
    inp = {
        "nonceHi": str(nh), "nonceLo": str(nl), "attempt": str(fx["attempt"]), "roleB": str(roleB),
        "codeHi": str(code_hi), "codeLo": str(code_lo),
        "cIs": [fe(v) for v in cIs], "cQs": [fe(v) for v in cQs], "cIp": [fe(v) for v in cIp], "cQp": [fe(v) for v in cQp],
        "salt": str(salt),
        "xs": [[fe(v) for v in row] for row in xs], "chS": [[[str(c) for c in lvl] for lvl in pth] for pth in chS],
        "leafS": str(leafS),
        "xp": [[fe(v) for v in row] for row in xp], "chP": [[[str(c) for c in lvl] for lvl in pth] for pth in chP],
        "leafP": str(leafP),
        "I": [fe(v) for v in I], "Q": [fe(v) for v in Q], "u": [str(v) for v in u],
    }
    # honest public values (what the verifier derives/pins)
    hfx = fx["deltas"][str(dms)][role]
    h_cc = bytes.fromhex(hfx["code_commit"])
    h_roleB = 1 if role == "B" else 0
    h_commit = p7.sponge16(p7.TAG_HALF, [nh, nl, fx["attempt"], h_roleB, hfx["half"] % P, salt])
    h_tpl = [tpl[role][0], tpl[role][1], tpl[other][0], tpl[other][1]]
    pub_tail = [str(nh), str(nl), str(fx["attempt"]), str(h_roleB), str(int.from_bytes(h_cc[:16], "big")),
                str(int.from_bytes(h_cc[16:], "big"))] + [fe(v) for t in h_tpl for v in t]
    if variant == "sig":
        hs = int(fr["holder_secret_dev"], 16)
        pubs = {r: fx["deltas"][str(dms)][r] for r in "AB"}
        xA, xB = int(pubs["A"]["device_pub_x"], 16) % P, int(pubs["B"]["device_pub_x"], 16) % P
        inp.update({
            "issuerX": str(int(fx["issuer"]["pub_x"], 16)), "issuerY": str(int(fx["issuer"]["pub_y"], 16)),
            "sr": str(SR), "validAt": str(VALID_AT),
            "ownPub": list(bytes.fromhex(fr["device_pub_x"] + fr["device_pub_y"])),
            "partnerPub": list(bytes.fromhex(fr["_partner_pub"])),
            "halfBytes": list(struct.pack(">i", half)),
            "recBytes": list(root.to_bytes(32, "big")),
            "pSelfB": list(struct.pack(">I", sig_p_self)), "pPartnerB": list(struct.pack(">I", p_part)),
            "deltaB": list(struct.pack(">H", delta)),
            "aSelfB": list(struct.pack(">I", claim_self)), "aPartnerB": list(struct.pack(">I", claim_part)),
            "ts": list(struct.pack(">Q", fr["os_ts"][0])),
            "sig_r": str(sig_r), "sig_sInv": sinv(sig_s),
            "exp": list(struct.pack(">Q", fr["cred_expiry_unix"])),
            "cred_r": str(int(fr["cred_sig_r_hex"], 16)), "cred_sInv": sinv(int(fr["cred_sig_s_hex"], 16)),
            "holderSecret": str(hs), "holdCommit": list(int(fr["holder_commit"], 16).to_bytes(32, "big")),
        })
        if tamper == "pself":
            inp["pSelfB"] = list(struct.pack(">I", p_self))
        nf = p7.sponge16(p7.TAG_NULL, [hs, nh, nl])
        ptag = p7.sponge16(7, [nh, nl, xA, xB])
        expected = [fe(h_commit), fe(nf), fe(ptag)] + pub_tail + [
            str(int(fx["issuer"]["pub_x"], 16) % P), str(int(fx["issuer"]["pub_y"], 16) % P), str(SR), str(VALID_AT)]
    else:
        inp.update({"recRoot": str(root), "pSelf": str(sig_p_self), "pPartner": str(p_part),
                    "aSelf": str(claim_self), "aPartner": str(claim_part)})
        expected = [fe(h_commit)] + pub_tail + [str(root), str(hfx["p_self"]), str(p_part)]
    return inp, expected, info


def build_pair(s8, dms):
    fx = json.loads((FIX / f"{s8}.json").read_text())
    d = fx["deltas"][str(dms)]
    nonce = bytes.fromhex(fx["nonce_hex"])
    nh, nl = int.from_bytes(nonce[:16], "big"), int.from_bytes(nonce[16:], "big")
    c = {}
    for r, rb in (("A", 0), ("B", 1)):
        c[r] = p7.sponge16(p7.TAG_HALF, [nh, nl, fx["attempt"], rb, d[r]["half"] % P, int(d[r]["salt_dev"], 16)])
    lo = (-20 * SR) // 17150
    hi = -((-60 * SR) // 17150)
    inp = {"nonceHi": str(nh), "nonceLo": str(nl), "attempt": str(fx["attempt"]), "commitA": str(c["A"]),
           "commitB": str(c["B"]), "dLo": fe(lo), "dHi": fe(hi),
           "halfA": fe(d["A"]["half"]), "saltA": str(int(d["A"]["salt_dev"], 16)),
           "halfB": fe(d["B"]["half"]), "saltB": str(int(d["B"]["salt_dev"], 16))}
    expected = [str(nh), str(nl), str(fx["attempt"]), str(c["A"]), str(c["B"]), fe(lo), fe(hi)]
    info = {"session": s8, "label_cm": fx["label_cm"], "flight_cm": d["flight_cm"], "verdict": d["verdict"],
            "d": d["A"]["half"] - d["B"]["half"], "dLo": lo, "dHi": hi}
    return inp, expected, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a", nargs="+")
    ap.add_argument("--tamper", default="none", choices=TAMPERS)
    ap.add_argument("--win", default="w400")
    ap.add_argument("--out", default=str(HERE / "inputs"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.a[0] == "pair":
        s8, dms = a.a[1], int(a.a[2])
        inp, exp, info = build_pair(s8, dms)
        name = f"{s8}_pair_d{dms}"
    else:
        s8, dms, role, variant = a.a[0], int(a.a[1]), a.a[2], a.a[3]
        inp, exp, info = build(s8, dms, role, variant, a.tamper, a.win)
        name = f"{s8}_d{dms}_{role}_{variant}" + ("" if a.tamper == "none" else f"_t-{a.tamper}")
    (out / f"{name}.input.json").write_text(json.dumps(inp))
    (out / f"{name}.public.json").write_text(json.dumps({"public": exp, "info": info}))
    print(json.dumps(info))


if __name__ == "__main__":
    main()

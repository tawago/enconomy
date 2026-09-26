"""POPT v2 fixture -> witness input + expected public values for oa2t_s48 / oa2t_s44 (+ _nf) and oa2t_pair.

  $PY prep_popt2.py phone <fixture> <A|B> [--tamper NAME] [--nf] [--out inputs]
  $PY prep_popt2.py pair  <fixture> [--tamper NAME] [--fixture-b OTHER]
  (fixture = ../fixtures/popt_v2/<name>.json stem, e.g. 180ca04b_mix)

Expected public values are what an honest verifier derives: outputs first (halfCommit[, nullifier]), then the
public inputs in declaration order. Transcript fields are sliced from the signed bytes, so the witness is
exactly what the enclave signed.

Phone tampers (expected publics stay honest):
  half         signed half +30 in the witness, not re-signed                -> ECDSA fails
  sr           public sr = the other rate (44100 on the 48 kHz circuit)     -> sr === SR / ECDSA fails
  nonce        verifier-side nonce of another session                       -> ECDSA fails
  swap_role    roleB flipped with the same signed bytes                     -> ECDSA fails (role byte)
  sample       one opened self sample +1                                    -> Merkle path fails
  resign_late  compromised app re-signs a_self' = p_self + delta (sod' = delta, same p_self, a_partner)
               with the Secure Enclave                                      -> self rule fails
  resign_early compromised app re-signs a_partner' = a_partner - 100 (half adjusted)  -> partner bar fails
Pair tampers:
  madeup       the combiner commits to made-up halves 0/0 with fresh salts (the pair circuit accepts; only
               the session verifier's link to the per-phone halfCommits rejects it)
  sr           srB = 48000 while B's commitment was made at 44100            -> commitB opening fails
  samekey      X_B := X_A in both openings                                  -> commitment / X_A != X_B fail
"""
from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ZK = HERE.parent
sys.path.insert(0, str(ZK / "enclave"))
sys.path.insert(0, str(HERE / "poseidon7"))
import oa_rate as R  # noqa: E402
import p7  # noqa: E402
import popt  # noqa: E402
import rectree  # noqa: E402

FIX = ZK / "fixtures" / "popt_v2"
P = popt.P256_P
N_ORDER = popt.P256_N
VALID_AT = 1790000000
TAG_HALF2 = 8
TAG_NULL = 5


def fe(v):
    return str(int(v) % P)


def sinv(s):
    return str(pow(s % N_ORDER, -1, N_ORDER))


def load_fixture(name):
    return json.loads((FIX / f"{name}.json").read_text())


def circuit_for(sr, nf=False):
    return f"oa2t_s{sr // 1000}" + ("_nf" if nf else "")


def half_commit(nonce, attempt, roleB, sr, half, salt, x_self, x_partner):
    nh, nl = int.from_bytes(nonce[:16], "big"), int.from_bytes(nonce[16:], "big")
    return p7.sponge16(TAG_HALF2, [nh, nl, attempt, roleB, sr, half % P, salt, x_self, x_partner])


def derived_public(fx, role, nf=False, holder_secret=None):
    """What the verifier derives for one per-phone proof: the public INPUT tail (no outputs)."""
    r = fx["roles"][role]
    o = "B" if role == "A" else "A"
    sr = r["sample_rate"]
    tI, tQ = R.templates(fx["seed_hex"], role, sr)
    pI, pQ = R.templates(fx["seed_hex"], o, sr)
    cc = R.code_commit(tI, tQ, pI, pQ)
    nonce = bytes.fromhex(fx["session_nonce"])
    vals = [int.from_bytes(nonce[:16], "big"), int.from_bytes(nonce[16:], "big"), fx["attempt"],
            1 if role == "B" else 0, int.from_bytes(cc[:16], "big"), int.from_bytes(cc[16:], "big")]
    for t in (tI, tQ, pI, pQ):
        vals += list(t)
    vals += [int(fx["issuer"]["pub_x"], 16), int(fx["issuer"]["pub_y"], 16), sr, VALID_AT]
    return [fe(v) for v in vals]


def open_region(x, lv, first, nl):
    xs, ch = [], []
    for i in range(nl):
        a = (first + i) * 1024
        seg = [int(v) for v in x[a: a + 1024]]
        seg += [0] * (1024 - len(seg))
        xs.append(seg)
        ch.append(rectree.path(lv, first + i))
    return xs, ch


def resign(fx, role, raw_fields):
    from build_popt_fixtures import dev_keys, sesign
    raw = popt.encode(raw_fields, 2)
    sig = sesign(dev_keys()[role]["blob"], raw)
    return raw, sig


def build_phone(name, role, tamper="none", nf=False):
    fx = load_fixture(name)
    r = fx["roles"][role]
    sr = r["sample_rate"]
    prm, geo = R.params(sr), R.geometry(sr)
    L, HM, DELTA, K = prm["L"], prm["HM"], prm["DELTA"], geo["K"]
    raw = base64.b64decode(r["transcript_b64"])
    sig = base64.b64decode(r["sig_b64"])
    t = popt.decode(raw)
    info = {"fixture": name, "role": role, "sr": sr, "tamper": tamper, "circuit": circuit_for(sr, nf),
            "label_cm": fx["label_cm"]}
    if tamper in ("resign_late", "resign_early"):
        t2 = {k: t[k] for k in popt.V1_FIELDS + popt.V2_EXTRA}
        p_self, a_part = t["p_self"], t["a_partner"]
        if tamper == "resign_late":
            t2["a_self"] = p_self + DELTA
            t2["self_os_delta"] = DELTA
            if t2["a_self"] == t["a_self"]:
                info["vacuous"] = True
        else:
            a_part = a_part - 100
        t2["half"] = a_part - t2["a_self"] if role == "A" else t2["a_self"] - a_part
        raw, sig = resign(fx, role, t2)
        t = popt.decode(raw)
        info["claimed"] = {"a_self": t["a_self"], "a_partner": t["a_partner"], "half": t["half"]}
    x = np.load(ZK / r["capture_npy"]).astype(np.int64)
    lv = rectree.load(json.loads((ZK / r["tree_json"]).read_text()))
    assert rectree.root(lv) == int(r["rec_root"], 16)
    tI, tQ = R.templates(fx["seed_hex"], role, sr)
    pI, pQ = R.templates(fx["seed_hex"], "B" if role == "A" else "A", sr)
    p_self, a_self, a_part = t["p_self"], t["a_self"], t["a_partner"]
    lo = p_self - DELTA
    I, Q, E = R.curve(x[lo - HM: lo + K + L - 1 + HM], tI, tQ, K, sr)
    ja = a_self - lo
    u = [1 if j < ja else 0 for j in range(K)]
    leafS = (p_self - DELTA - HM) // 1024
    leafP = (a_part - HM) // 1024
    xs, chS = open_region(x, lv, leafS, geo["NLS"])
    xp, chP = open_region(x, lv, leafP, geo["NLP"])
    if tamper == "sample":
        xs[1][500] += 1
    rs = int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")
    fields = {"ownPub": raw[40:104], "partnerPub": raw[105:169], "halfBytes": raw[173:177], "recBytes": raw[177:209],
              "pfpB": raw[209:217], "pntB": raw[217:225], "rf0B": raw[225:233], "sodB": raw[233:237],
              "chB": raw[237:269], "aSelfB": raw[269:273], "pPartnerB": raw[273:277], "deltaB": raw[277:279]}
    assert raw[39] == 4 and raw[104] == 4 and raw[279:311] == bytes.fromhex(r["code_commit"])
    inp = {k: list(v) for k, v in fields.items()}
    if tamper == "half":
        inp["halfBytes"] = list(struct.pack(">i", t["half"] + 30))
    pub = derived_public(fx, role)
    names = ["nonceHi", "nonceLo", "attempt", "roleB", "codeHi", "codeLo"]
    for i, n in enumerate(names):
        inp[n] = pub[i]
    for j, n in enumerate(("cIs", "cQs", "cIp", "cQp")):
        inp[n] = pub[6 + j * L: 6 + (j + 1) * L]
    inp["issuerX"], inp["issuerY"], inp["sr"], inp["validAt"] = pub[6 + 4 * L:]
    if tamper == "sr":
        inp["sr"] = "44100" if sr == 48000 else "48000"
    if tamper == "nonce":
        inp["nonceHi"] = str(int(inp["nonceHi"]) ^ 1)
    if tamper == "swap_role":
        inp["roleB"] = str(1 - int(inp["roleB"]))
    inp.update({
        "sig_r": str(rs[0]), "sig_sInv": sinv(rs[1]),
        "exp": list(struct.pack(">Q", r["cred_expiry_unix"])),
        "cred_r": str(int(r["cred_sig_r_hex"], 16)), "cred_sInv": sinv(int(r["cred_sig_s_hex"], 16)),
        "holdCommit": list(int(r["holder_commit"], 16).to_bytes(32, "big")),
        "salt": str(int(r["salt_dev"], 16)),
        "xs": [[fe(v) for v in row] for row in xs], "chS": [[[str(c) for c in l] for l in pth] for pth in chS],
        "leafS": str(leafS),
        "xp": [[fe(v) for v in row] for row in xp], "chP": [[[str(c) for c in l] for l in pth] for pth in chP],
        "leafP": str(leafP),
        "I": [fe(v) for v in I], "Q": [fe(v) for v in Q], "u": [str(v) for v in u]})
    if nf:
        inp["holderSecret"] = str(int(r["holder_secret_dev"], 16))
    # honest expected outputs
    nonce = bytes.fromhex(fx["session_nonce"])
    o = "B" if role == "A" else "A"
    xS = int(fx["roles"][role]["pubkey"][2:66], 16)
    xP = int(fx["roles"][o]["pubkey"][2:66], 16)
    hc = half_commit(nonce, fx["attempt"], 1 if role == "B" else 0, sr, r["half"], int(r["salt_dev"], 16), xS, xP)
    outs = [fe(hc)]
    if nf:
        nh, nl = int.from_bytes(nonce[:16], "big"), int.from_bytes(nonce[16:], "big")
        outs.append(fe(p7.sponge16(TAG_NULL, [int(r["holder_secret_dev"], 16), nh, nl])))
    return inp, outs + pub, info


def build_pair(name, tamper="none", name_b=None):
    fa = load_fixture(name)
    fb = load_fixture(name_b) if name_b else fa
    A, B = fa["roles"]["A"], fb["roles"]["B"]
    nonce = bytes.fromhex(fa["session_nonce"])
    xA, xB = int(A["pubkey"][2:66], 16), int(B["pubkey"][2:66], 16)
    hA, hB, sA, sB = A["half"], B["half"], int(A["salt_dev"], 16), int(B["salt_dev"], 16)
    srA, srB = A["sample_rate"], B["sample_rate"]
    cA = half_commit(nonce, fa["attempt"], 0, srA, hA, sA, xA, xB)
    cB = half_commit(bytes.fromhex(fb["session_nonce"]), fb["attempt"], 1, srB, hB, sB, xB, xA)
    info = {"fixture": name, "fixture_b": name_b, "tamper": tamper, "srA": srA, "srB": srB,
            "flight_cm": fa["expect"]["flight_cm"], "verdict": fa["expect"]["verdict"], "label_cm": fa["label_cm"]}
    if tamper == "madeup":
        hA, hB, sA, sB = 0, 0, 12345, 67890
        cA = half_commit(nonce, fa["attempt"], 0, srA, hA, sA, xA, xB)
        cB = half_commit(nonce, fa["attempt"], 1, srB, hB, sB, xB, xA)
    pub_srB = srB
    if tamper == "sr":
        pub_srB = 48000 if srB != 48000 else 44100
    if tamper == "samekey":
        xB = xA
    nh, nl = int.from_bytes(nonce[:16], "big"), int.from_bytes(nonce[16:], "big")
    inp = {"nonceHi": str(nh), "nonceLo": str(nl), "attempt": str(fa["attempt"]), "commitA": fe(cA),
           "commitB": fe(cB), "srA": str(srA), "srB": str(pub_srB), "halfA": fe(hA), "saltA": str(sA),
           "halfB": fe(hB), "saltB": str(sB), "xA": fe(xA), "xB": fe(xB)}
    expected = [str(nh), str(nl), str(fa["attempt"]), fe(cA), fe(cB), str(srA), str(pub_srB)]
    return inp, expected, info


def build_edges():
    """Pair inputs for the edge cases of ../verifier/edge_cases.json (run edge_cases.py first): synthetic halves,
    the 180ca04b_48k nonce/keys, fresh salts. Accept iff the exact integer rule says NEAR."""
    cases = json.loads((ZK / "verifier" / "edge_cases.json").read_text())
    fx = load_fixture("180ca04b_48k")
    nonce = bytes.fromhex(fx["session_nonce"])
    nh, nl = int.from_bytes(nonce[:16], "big"), int.from_bytes(nonce[16:], "big")
    xA, xB = int(fx["roles"]["A"]["pubkey"][2:66], 16), int(fx["roles"]["B"]["pubkey"][2:66], 16)
    picked = [c for c in cases if c["tie"] or c["exact"] != c["server"] or
              (c["srA"], c["srB"]) in ((48000, 44100), (44100, 48000), (36000, 96000))]
    out = []
    for i, c in enumerate(picked):
        cA = half_commit(nonce, 0, 0, c["srA"], c["hA"], 11, xA, xB)
        cB = half_commit(nonce, 0, 1, c["srB"], c["hB"], 22, xB, xA)
        inp = {"nonceHi": str(nh), "nonceLo": str(nl), "attempt": "0", "commitA": fe(cA), "commitB": fe(cB),
               "srA": str(c["srA"]), "srB": str(c["srB"]), "halfA": fe(c["hA"]), "saltA": "11",
               "halfB": fe(c["hB"]), "saltB": "22", "xA": fe(xA), "xB": fe(xB)}
        exp = [str(nh), str(nl), "0", fe(cA), fe(cB), str(c["srA"]), str(c["srB"])]
        stem = f"popt2_edge_{i:03d}"
        (HERE / "inputs" / f"{stem}.input.json").write_text(json.dumps(inp))
        (HERE / "inputs" / f"{stem}.public.json").write_text(json.dumps({"public": exp, "info": c}))
        out.append({"stem": stem, **c})
    print(json.dumps(out))


def main():
    if sys.argv[1:2] == ["edges"]:
        return build_edges()
    ap = argparse.ArgumentParser()
    ap.add_argument("a", nargs="+")
    ap.add_argument("--tamper", default="none")
    ap.add_argument("--nf", action="store_true")
    ap.add_argument("--fixture-b")
    ap.add_argument("--out", default=str(HERE / "inputs"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.a[0] == "phone":
        inp, exp, info = build_phone(a.a[1], a.a[2], a.tamper, a.nf)
        stem = f"popt2_{a.a[1]}_{a.a[2]}" + ("_nf" if a.nf else "") + ("" if a.tamper == "none" else f"_t-{a.tamper}")
    else:
        inp, exp, info = build_pair(a.a[1], a.tamper, a.fixture_b)
        stem = f"popt2_{a.a[1]}_pair" + (f"_x{a.fixture_b}" if a.fixture_b else "") + \
               ("" if a.tamper == "none" else f"_t-{a.tamper}")
    info["stem"] = stem
    (out / f"{stem}.input.json").write_text(json.dumps(inp))
    (out / f"{stem}.public.json").write_text(json.dumps({"public": exp, "info": info}))
    print(json.dumps(info))


if __name__ == "__main__":
    main()

"""Reviewer attacks on optionA-v2 (not in the builder's tamper list). Writes review/inputs/<name>.{input,public}.json.

  $PY review/attacks.py

Per-phone attacks use oa2_d2_sig on real fixtures; the expected public values are always the honest ones
(what a verifier derives or what the honest proof outputs), except where noted.
"""
from __future__ import annotations

import importlib.util
import json
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OA2 = HERE.parent
sys.path.insert(0, str(OA2))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


prep = load("prep_oa2", OA2 / "prep.py")
from common2 import HM, P, code_commit, delta_samples, geometry  # noqa: E402
import p7  # noqa: E402

OUT = HERE / "inputs"
OUT.mkdir(exist_ok=True)


def save(name, inp, exp, info):
    (OUT / f"{name}.input.json").write_text(json.dumps(inp))
    (OUT / f"{name}.public.json").write_text(json.dumps({"public": exp, "info": info}))
    print(name, json.dumps(info))


def fe(v):
    return str(int(v) % P)


def per_phone():
    s8, d, role = "180ca04b", 2, "A"
    inp, exp, info = prep.build(s8, d, role, "sig")
    save("honest_180ca04b_d2_A_sig", inp, exp, info)
    delta = delta_samples(d)
    g = geometry(delta)
    x = prep.twin2.load(s8)[4][role]
    lv = prep.levels(s8, role)
    leafS = int(inp["leafS"])

    # X1: Merkle paths + samples of the NEXT 13 leaves, leaf index kept (path reused from another position)
    a = dict(inp)
    xs, ch = prep.open_region(x, lv, leafS + 1, g["NLS"])
    a["xs"] = [[fe(v) for v in r] for r in xs]
    a["chS"] = [[[str(c) for c in lvl] for lvl in pth] for pth in ch]
    save("X1_path_other_position", a, exp, {"attack": "self leaves+paths from leaf+1.., index input unchanged"})

    # X1b: same content, but only the level-0 digit is moved: honest leaf 0 of the region is placed in the slot of
    # its right neighbour (children reordered), i.e. try to open leaf q's content "at" q+1 with a consistent-looking path
    b = json.loads(json.dumps(inp))
    c0 = b["chS"][0][0]
    dig = leafS % 4
    other = (dig + 1) % 4
    c0[dig], c0[other] = c0[other], c0[dig]
    save("X1b_children_reordered", b, exp, {"attack": "level-0 children of the first self leaf swapped"})

    # X2: re-split the window start: leaf one earlier, offset + 1024 (11 bits)
    c = dict(inp)
    xs, ch = prep.open_region(x, lv, leafS - 1, g["NLS"])
    c["xs"] = [[fe(v) for v in r] for r in xs]
    c["chS"] = [[[str(c_) for c_ in lvl] for lvl in pth] for pth in ch]
    c["leafS"] = str(leafS - 1)
    save("X2_leaf_minus1_offset_plus1024", c, exp, {"attack": "leafS-1, oS would be >= 1024"})

    # X6: own/partner templates in the partner's order (then code_commit = what B signed, not A)
    e = dict(inp)
    e["cIs"], e["cQs"], e["cIp"], e["cQp"] = inp["cIp"], inp["cQp"], inp["cIs"], inp["cQs"]
    fx = json.loads((OA2 / "fixtures" / f"{s8}.json").read_text())
    ccB = bytes.fromhex(fx["deltas"][str(d)]["B"]["code_commit"])
    e["codeHi"], e["codeLo"] = str(int.from_bytes(ccB[:16], "big")), str(int.from_bytes(ccB[16:], "big"))
    expE = list(exp)
    # verifier would derive B-ordered templates only if it believed the proof is role B; keep honest expectations
    save("X6_templates_partner_order", e, expE, {"attack": "A's proof with cIs<->cIp swapped and B's code_commit"})

    # X7: I and Q shifted by one lag (claimed curve = curve of the next lag), a_self unchanged
    f = dict(inp)
    f["I"] = inp["I"][1:] + [inp["I"][-1]]
    f["Q"] = inp["Q"][1:] + [inp["Q"][-1]]
    save("X7_curve_shifted_one_lag", f, exp, {"attack": "claimed I,Q = true curve shifted by one lag"})


def pair_attacks():
    # honest pair for 180ca04b (NEAR)
    inp, exp, info = prep.build_pair("180ca04b", 2)
    save("honest_pair_180ca04b", inp, exp, info)
    far, fexp, finfo = prep.build_pair("9afb91c6", 2)

    # X3: splice: nonce/attempt/commitA of 180ca04b (NEAR 30 cm), commitB of 9afb91c6 (200 cm)
    s = dict(inp)
    s["commitB"], s["halfB"], s["saltB"] = far["commitB"], far["halfB"], far["saltB"]
    sexp = list(exp)
    sexp[4] = far["commitB"]
    save("X3_cross_session_splice", s, sexp, {"attack": "A of 180ca04b + B of 9afb91c6 under 180ca04b's nonce"})

    # X4: combiner fabricates halves for the 200 cm session: halfA = halfB = 0, fresh salts, fresh commitments
    nh, nl, att = int(far["nonceHi"]), int(far["nonceLo"]), int(far["attempt"])
    sa, sb = secrets.randbits(250), secrets.randbits(250)
    ca = p7.sponge16(p7.TAG_HALF, [nh, nl, att, 0, 0, sa])
    cb = p7.sponge16(p7.TAG_HALF, [nh, nl, att, 1, 0, sb])
    fab = dict(far, commitA=str(ca), commitB=str(cb), halfA="0", halfB="0", saltA=str(sa), saltB=str(sb))
    fabexp = [far["nonceHi"], far["nonceLo"], far["attempt"], str(ca), str(cb), far["dLo"], far["dHi"]]
    save("X4_fabricated_pair_9afb91c6", fab, fabexp,
         {"attack": "combiner commits to fake halves 0/0 for the 200 cm session", "honest_commitA": far["commitA"],
          "honest_commitB": far["commitB"]})

    # X5: role doubling: A's commitment used for both slots (same half, roleB forced 1 in slot B)
    r = dict(inp)
    r["commitB"], r["halfB"], r["saltB"] = inp["commitA"], inp["halfA"], inp["saltA"]
    rexp = list(exp)
    rexp[4] = inp["commitA"]
    save("X5_role_doubling", r, rexp, {"attack": "commitA reused as commitB"})

    # X8: wrap: halfA' = halfA - 2^32 (so that halfA' - halfB lands in the NEAR band mod 2^32), commitA recomputed
    hA, hB = int(far["halfA"]), int(far["halfB"])
    hA = hA - P if hA > P // 2 else hA
    hB = hB - P if hB > P // 2 else hB
    w = dict(far)
    tgt = hB + 50                                   # a NEAR difference
    hA2 = tgt - (1 << 32)                           # congruent to tgt mod 2^32, not mod p
    ca2 = p7.sponge16(p7.TAG_HALF, [nh, nl, att, 0, hA2 % P, int(far["saltA"])])
    w["halfA"], w["commitA"] = fe(hA2), str(ca2)
    wexp = list(fexp)
    wexp[3] = str(ca2)
    save("X8_half_wrap_2p32", w, wexp, {"attack": "halfA - 2^32 so the i32 difference looks NEAR", "halfA'": hA2})


if __name__ == "__main__":
    per_phone()
    pair_attacks()

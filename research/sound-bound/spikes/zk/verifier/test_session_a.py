"""End-to-end tests of the option A session verifier (popzk.py) on real Spartan2 proofs from POPT v2 fixtures.

  PY=research/proximity-echo/.venv/bin/python3
  tools/heavy.sh session-a $PY verifier/test_session_a.py [--reprove]

Makes (or reuses, in ../optionA-v2/out/popt2/) the proofs it needs, then runs popzk.verify_session on honest
bundles and on the tamper set. Per-phone witnesses that violate the circuit are still turned into proofs by
oa2zk (the prover does not check satisfiability): such a "forced" proof must fail verification.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ZK = HERE.parent
OA2 = ZK / "optionA-v2"
OUT = OA2 / "out" / "popt2"
sys.path.insert(0, str(HERE))
import popzk  # noqa: E402

PY = sys.executable
REPROVE = "--reprove" in sys.argv
FIX = ZK / "fixtures" / "popt_v2"


def prep(*a, tamper="none", extra=()):
    args = [PY, str(OA2 / "prep_popt2.py"), *a, *extra] + (["--tamper", tamper] if tamper != "none" else [])
    r = subprocess.run(args, capture_output=True, text=True, check=True)
    return json.loads(r.stdout.strip().splitlines()[-1])


def prove(circuit, stem):
    OUT.mkdir(parents=True, exist_ok=True)
    proof = OUT / f"{stem}.proof"
    if proof.exists() and not REPROVE:
        return proof
    t = time.time()
    r = subprocess.run([str(OA2 / "oa2zk.sh"), "prove", circuit, str(OA2 / "inputs" / f"{stem}.input.json"),
                        str(proof)], capture_output=True, text=True)
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT")), (r.stdout + r.stderr)[-300:])
    print(f"    prove {stem}: {line[:150]} ({time.time() - t:.1f}s)", flush=True)
    return proof if proof.exists() else None


def phone(fx, role, tamper="none"):
    info = prep("phone", fx, role, tamper=tamper)
    return {"circuit": info["circuit"], "proof": str(prove(info["circuit"], info["stem"]))}


def pair(fx, tamper="none", fb=None):
    info = prep("pair", fx, tamper=tamper, extra=["--fixture-b", fb] if fb else [])
    p = prove("oa2t_pair", info["stem"])
    return {"circuit": "oa2t_pair", "proof": str(p)} if p else None


def session_of(fx):
    f = json.loads((FIX / f"{fx}.json").read_text())
    return {"nonce": f["session_nonce"], "attempt": f["attempt"], "code_seed_hex": f["seed_hex"]}


RES = []


def expect(label, bundle, want, nullifiers=None, policy=None):
    pol = policy or popzk.load_policy()
    t = time.time()
    try:
        got = popzk.verify_session(bundle, pol, nullifiers)
        out = (got["verdict"], got["reason"])
        extra = f"sr={got['sample_rates']} pair_tag={(got['pair_tag'] or '')[:16]}"
    except popzk.Reject as e:
        out = ("REJECT", e.reason)
        extra = e.detail[:110]
    good = out == want
    RES.append(good)
    print(f"{'PASS' if good else 'FAIL'}  {label:62} want={want} got={out} ({time.time() - t:.1f}s)  {extra}",
          flush=True)


def main():
    print("== proofs")
    P = {}
    for fx in ("180ca04b_48k", "180ca04b_mix", "9afb91c6_48k", "9afb91c6_mix"):
        for r in "AB":
            P[(fx, r)] = phone(fx, r)
    P[("180ca04b_48k", "pair")] = pair("180ca04b_48k")
    P[("180ca04b_mix", "pair")] = pair("180ca04b_mix")
    madeup = pair("9afb91c6_48k", "madeup")
    forced_pair = pair("9afb91c6_mix")                    # NOT_NEAR: unsatisfied witness, proof forced
    forced_half = phone("180ca04b_48k", "B", "half")       # half +30 not re-signed
    forced_sod = phone("180ca04b_48k_sodfar", "B")         # signed self_os_delta over tolerance
    forced_late = phone("180ca04b_48k", "A", "resign_late")
    forced_sr = pair("180ca04b_mix", "sr")

    def bundle(fx, A=None, B=None, pr="same", sess=None):
        return {"session": sess or session_of(fx), "A": A or P[(fx, "A")], "B": B or P[(fx, "B")],
                "pair": P.get((fx, "pair")) if pr == "same" else pr}

    print("== honest")
    expect("180ca04b 48k/48k NEAR", bundle("180ca04b_48k"), ("NEAR", None))
    expect("180ca04b 48k/44.1k (mixed rate) NEAR", bundle("180ca04b_mix"), ("NEAR", None))
    expect("180ca04b mixed, adapters nullifiers 101/202 -> pair_tag", bundle("180ca04b_mix"), ("NEAR", None),
           nullifiers=("101", "0xca"))
    expect("9afb91c6 200 cm, no pair proof", bundle("9afb91c6_48k", pr=None), ("NOT_NEAR", "too_far_or_failed"))
    print("== tampers")
    expect("9afb91c6 200 cm, forced pair proof (unsatisfied witness)",
           bundle("9afb91c6_mix", pr=forced_pair), ("REJECT", "proof_invalid"))
    expect("9afb91c6 200 cm, pair proof over made-up halves 0/0",
           bundle("9afb91c6_48k", pr=madeup), ("REJECT", "transcript_mismatch"))
    expect("half +30 not re-signed (forced B proof)",
           bundle("180ca04b_48k", B=forced_half), ("REJECT", "proof_invalid"))
    expect("self_os_delta 2401 > 50 ms (signed, forced B proof)",
           bundle("180ca04b_48k", B=forced_sod), ("REJECT", "proof_invalid"))
    expect("compromised app re-signs a later a_self (forced A proof)",
           bundle("180ca04b_48k", A=forced_late), ("REJECT", "proof_invalid"))
    expect("role swap (B proof in slot A, A proof in slot B)",
           bundle("180ca04b_48k", A=P[("180ca04b_48k", "B")], B=P[("180ca04b_48k", "A")]),
           ("REJECT", "transcript_mismatch"))
    expect("one proof used as both roles (A's proof in slot B)",
           bundle("180ca04b_48k", B=P[("180ca04b_48k", "A")]), ("REJECT", "transcript_mismatch"))
    expect("cross-session splice: A of 9afb91c6 + B and pair of 180ca04b",
           bundle("180ca04b_48k", A=P[("9afb91c6_48k", "A")]), ("REJECT", "transcript_mismatch"))
    expect("cross-session splice: pair proof of 180ca04b_48k on the _mix phones",
           bundle("180ca04b_mix", pr=P[("180ca04b_48k", "pair")]), ("REJECT", "transcript_mismatch"))
    other = session_of("180ca04b_48k")
    other["nonce"] = session_of("9afb91c6_48k")["nonce"]
    expect("nonce: honest 180ca04b bundle checked against another session nonce",
           bundle("180ca04b_48k", sess=other), ("REJECT", "transcript_mismatch"))
    att = session_of("180ca04b_48k")
    att["attempt"] = 1
    expect("attempt: verifier expects attempt 1", bundle("180ca04b_48k", sess=att), ("REJECT", "transcript_mismatch"))
    expect("sr change: 44.1 kHz B proof presented as circuit oa2t_s48",
           bundle("180ca04b_mix", B={"circuit": "oa2t_s48", "proof": P[("180ca04b_mix", "B")]["proof"]}),
           ("REJECT", "proof_invalid"))
    expect("sr change: pair proof claiming srB = 48000 on the mixed session (forced)",
           bundle("180ca04b_mix", pr=forced_sr), ("REJECT", "proof_invalid"))
    expect("unknown circuit name", bundle("180ca04b_48k", A={"circuit": "oa2_d2_sig",
                                                             "proof": P[("180ca04b_48k", "A")]["proof"]}),
           ("REJECT", "circuit_unknown"))
    pol = popzk.load_policy()
    pol.pinned = dict(pol.pinned, oa2t_s48="00" * 32)
    expect("pinned circuit id differs from the vk on disk", bundle("180ca04b_48k"), ("REJECT", "circuit_unknown"),
           policy=pol)
    pol = popzk.load_policy(issuer=("11" * 32, "22" * 32))
    expect("verifier pins another issuer", bundle("180ca04b_48k"), ("REJECT", "issuer_unknown"), policy=pol)
    pol = popzk.load_policy(valid_at=1790000001)
    expect("verifier time differs from the proof's validAt", bundle("180ca04b_48k"), ("REJECT", "transcript_mismatch"),
           policy=pol)
    s = session_of("180ca04b_48k")
    s["code_seed_hex"] = json.loads((FIX / "9afb91c6_48k.json").read_text())["seed_hex"]
    expect("templates: verifier derives another session's codes", bundle("180ca04b_48k", sess=s),
           ("REJECT", "transcript_mismatch"))
    expect("same human: both adapter nullifiers equal", bundle("180ca04b_48k"), ("REJECT", "same_human"),
           nullifiers=("12345", "0x3039"))
    print(f"\nsession verifier: {sum(RES)}/{len(RES)} as expected")
    return 0 if all(RES) else 1


if __name__ == "__main__":
    sys.exit(main())

"""Reviewer's end-to-end verifier sketch: the checks the README lists as "verifier's own duties" plus the
cross-proof bindings, done in code. Uses oa2zk verify for each proof.

  $PY review/verify_session.py <sess8> <proofA> <proofB> <pairproof>

For each per-phone proof the verifier derives every public INPUT itself (nonce, attempt, roleB, templates,
code_commit, issuer, sr, validAt) and reads the three OUTPUTS (halfCommit, nullifier, pairTag) from the proof.
Then: pairTag_A == pairTag_B, nullifier_A != nullifier_B, and the pair proof must carry
(nonce, attempt, halfCommit_A, halfCommit_B, dLo(sr), dHi(sr)).
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OA2 = HERE.parent
sys.path.insert(0, str(OA2))
spec = importlib.util.spec_from_file_location("prep_oa2", OA2 / "prep.py")
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)
from common2 import P, SR, code_commit  # noqa: E402

BIN = str(OA2 / "oa2zk.sh")


def run_verify(circuit, proof, expected):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"public": expected}, f)
    r = subprocess.run([BIN, "verify", circuit, proof, f.name], capture_output=True, text=True)
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT")), r.stdout + r.stderr)
    return line


def outputs_of(circuit, proof, n_pub):
    """Spartan-verify the proof and read its public vector (verify() checks the SNARK before comparing IO)."""
    line = run_verify(circuit, proof, ["0"] * n_pub)
    m = re.search(r"proof has \[(.*)\]", line)
    if not m:
        return None, line
    return m.group(1).split(", "), line


def derived_inputs(s8, role):
    fx = json.loads((OA2 / "fixtures" / f"{s8}.json").read_text())
    other = "B" if role == "A" else "A"
    tpl = prep.twin2.load(s8)[5]                  # stand-in for "derive from the revealed code seed"
    nonce = bytes.fromhex(fx["nonce_hex"])
    nh, nl = int.from_bytes(nonce[:16], "big"), int.from_bytes(nonce[16:], "big")
    cc = code_commit(tpl[role][0], tpl[role][1], tpl[other][0], tpl[other][1])
    vals = [nh, nl, fx["attempt"], 1 if role == "B" else 0, int.from_bytes(cc[:16], "big"),
            int.from_bytes(cc[16:], "big")]
    for t in (tpl[role][0], tpl[role][1], tpl[other][0], tpl[other][1]):
        vals += [int(v) for v in t]
    vals += [int(fx["issuer"]["pub_x"], 16), int(fx["issuer"]["pub_y"], 16), SR, prep.VALID_AT]
    return [str(v % P) for v in vals], (nh, nl, fx["attempt"])


def main():
    s8, pa, pb, pp = sys.argv[1:5]
    circ = "oa2_d2_sig"
    ok = True
    outs = {}
    for role, proof in (("A", pa), ("B", pb)):
        exp_in, hdr = derived_inputs(s8, role)
        got, line = outputs_of(circ, proof, 3 + len(exp_in))
        if got is None:
            print(f"per-phone {role}: SNARK REJECT  {line[:140]}")
            ok = False
            continue
        if got[3:] != exp_in:
            bad = [i for i, (a, b) in enumerate(zip(got[3:], exp_in)) if a != b][:5]
            print(f"per-phone {role}: SNARK ok, public inputs differ from the derived ones at {bad} -> REJECT")
            ok = False
            continue
        outs[role] = got[:3]
        print(f"per-phone {role}: ACCEPT  halfCommit={got[0][:12]}.. nullifier={got[1][:12]}.. pairTag={got[2][:12]}..")
    if len(outs) == 2:
        if outs["A"][2] != outs["B"][2]:
            print("pairTag differs -> REJECT")
            ok = False
        if outs["A"][1] == outs["B"][1]:
            print("same nullifier in both roles -> REJECT")
            ok = False
        lo = (-20 * SR) // 17150
        hi = -((-60 * SR) // 17150)
        nh, nl, att = hdr
        exp_pair = [str(nh), str(nl), str(att), outs["A"][0], outs["B"][0], str(lo % P), str(hi % P)]
        line = run_verify("oa2_pair", pp, exp_pair)
        print("pair (bound to the per-phone halfCommits):", line[:170])
        ok = ok and " ACCEPT " in line
    print("SESSION VERDICT:", "NEAR (accepted)" if ok else "REJECT")


if __name__ == "__main__":
    main()

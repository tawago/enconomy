"""Accept/reject tests for the sound-bound circuits (needs inputs/ from prep_inputs.py and a built sbzk).

  python3 run_tests.py check      # witness gen + direct R1CS check, all fixtures and tampers (no proving)
  python3 run_tests.py proofs     # real Spartan2 proofs: honest accept + verifier-side rejects
                                  # (run under ../tools/heavy.sh; needs keys/ from `sbzk setup`)
"""
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SBZK = os.path.join(HERE, "sbzk.sh")
INP = os.path.join(HERE, "inputs")
TMP = os.path.join(HERE, "out")


def run(*args):
    p = subprocess.run([SBZK, *args], capture_output=True, text=True)
    line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT")), None)
    if line is None:  # crash / no verdict: never counts as a clean accept or reject
        return None, "NO RESULT: " + (p.stdout[-200:] + p.stderr[-200:]).replace("\n", " | ")
    return p.returncode == 0 and " REJECT" not in line, line


def expect(label, want_accept, ok, line, results):
    passed = ok is not None and ok == want_accept
    results.append(passed)
    print(f"{'PASS' if passed else 'FAIL'}  {label:48} want={'accept' if want_accept else 'reject':6} "
          f"got={'error' if ok is None else 'accept' if ok else 'reject':6}  {line[:150]}")


def check():
    res = []
    # every fixture, pair_v1 honest: accept iff fixture verdict NEAR
    for pj in sorted(glob.glob(os.path.join(INP, "*_pair_v1.public.json"))):
        info = json.load(open(pj))["info"]
        ok, line = run("check", "sb_pair_v1", pj.replace(".public.json", ".input.json"))
        expect(f"{info['session']} {info['label_cm']:.0f}cm d={info['d_samples']} {info['verdict']}",
               info["verdict"] == "NEAR", ok, line, res)
    # tampers on a NEAR fixture
    for t, want in [("half", False), ("swap", False), ("nonce", False), ("badsig", False),
                    ("issuer", False), ("expired", False), ("holder", True)]:
        ok, line = run("check", "sb_pair_v1", os.path.join(INP, f"180ca04b_pair_v1_t-{t}.input.json"))
        expect(f"pair_v1 tamper {t}" + (" (v1 nullifier unbound: accepts)" if t == "holder" else ""),
               want, ok, line, res)
    for name, f, want in [("sb_pair_v2", "180ca04b_pair_v2", True), ("sb_pair_v2", "180ca04b_pair_v2_t-holder", False),
                          ("sb_half_v1", "180ca04b_half_v1_A", True), ("sb_half_v1", "180ca04b_half_v1_B", True),
                          ("sb_half_v2", "180ca04b_half_v2_A", True), ("sb_half_v2", "180ca04b_half_v2_B", True),
                          ("sb_half_v2", "180ca04b_half_v2_A_t-holder", False)]:
        ok, line = run("check", name, os.path.join(INP, f + ".input.json"))
        expect(f"{name} {f}", want, ok, line, res)
    return res


def proofs():
    os.makedirs(TMP, exist_ok=True)
    res = []
    for name, f in [("sb_pair_v1", "180ca04b_pair_v1"), ("sb_pair_v2", "180ca04b_pair_v2"),
                    ("sb_half_v1", "180ca04b_half_v1_A"), ("sb_half_v2", "180ca04b_half_v2_A")]:
        if not os.path.exists(os.path.join(HERE, "keys", name + ".vk")):
            print(f"SKIP  {name}: no keys")
            continue
        proof = os.path.join(TMP, f + ".proof")
        pub = os.path.join(INP, f + ".public.json")
        ok, line = run("prove", name, os.path.join(INP, f + ".input.json"), proof)
        expect(f"{name} prove honest", True, ok, line, res)
        ok, line = run("verify", name, proof, pub)
        expect(f"{name} verify honest", True, ok, line, res)
        # verifier expects another nonce (e.g. replay of this proof into another session)
        exp = json.load(open(pub))
        exp["public"][2 if name.startswith("sb_half") else 1] = "1"
        bad = os.path.join(TMP, f + "_wrongnonce.public.json")
        json.dump(exp, open(bad, "w"))
        ok, line = run("verify", name, proof, bad)
        expect(f"{name} verify vs wrong nonce", False, ok, line, res)
        # verifier expects another nullifier
        exp = json.load(open(pub))
        exp["public"][0] = "12345"
        bad = os.path.join(TMP, f + "_wrongnf.public.json")
        json.dump(exp, open(bad, "w"))
        ok, line = run("verify", name, proof, bad)
        expect(f"{name} verify vs wrong nullifier", False, ok, line, res)
        # flipped byte in the proof body
        b = bytearray(open(proof, "rb").read())
        b[len(b) // 2] ^= 0x01
        badp = os.path.join(TMP, f + "_flip.proof")
        open(badp, "wb").write(bytes(b))
        ok, line = run("verify", name, badp, pub)
        expect(f"{name} verify flipped proof byte", False, ok, line, res)
    # a pair proof checked against a different session's expected public values
    if os.path.exists(os.path.join(TMP, "180ca04b_pair_v1.proof")):
        ok, line = run("verify", "sb_pair_v1", os.path.join(TMP, "180ca04b_pair_v1.proof"),
                       os.path.join(INP, "b550cf12_pair_v1.public.json"))
        expect("sb_pair_v1 proof(180ca04b) vs public(b550cf12)", False, ok, line, res)
    return res


if __name__ == "__main__":
    r = check() if sys.argv[1:] == ["check"] else proofs()
    print(f"{sum(r)}/{len(r)} passed")
    sys.exit(0 if all(r) else 1)

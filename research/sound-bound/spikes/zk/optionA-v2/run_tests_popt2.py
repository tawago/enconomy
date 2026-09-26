"""Accept/reject tests for the POPT v2 circuits (witness generation + R1CS check; no proving).

  python3 run_tests_popt2.py phones [--wasm]   # every v2 fixture x role: honest per-phone witness accepted,
                                               # public values == what the verifier derives
  python3 run_tests_popt2.py tampers [--wasm]  # per-phone tampers on 180ca04b_48k / _mix + signed sod fixtures
  python3 run_tests_popt2.py pairs [--wasm]    # pair circuit on all fixtures: NEAR accepted, NOT_NEAR rejected,
                                               # plus pair tampers
Run under ../tools/heavy.sh. --wasm uses the circom wasm witness generator (node) + the public-value compare
(the R1CS check needs the C++ path: oa2zk check). Without --wasm: oa2zk check (C++ witness + full R1CS check).
"""
from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ZK = HERE.parent
PY = str(ZK.parents[2] / "proximity-echo/.venv/bin/python3")
OA2 = str(HERE / "oa2zk.sh")
INP = HERE / "inputs"
FIX = ZK / "fixtures" / "popt_v2"
WASM = "--wasm" in sys.argv
if WASM:
    sys.argv.remove("--wasm")


def prep(*a, tamper="none", extra=()):
    args = [PY, str(HERE / "prep_popt2.py"), *map(str, a), *extra] + (["--tamper", tamper] if tamper != "none" else [])
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def parse_wtns(path, n):
    b = open(path, "rb").read()
    pos, n8 = 12, 0
    for _ in range(struct.unpack("<I", b[8:12])[0]):
        sid, ln = struct.unpack("<IQ", b[pos:pos + 12])
        pos += 12
        if sid == 1:
            n8 = struct.unpack("<I", b[pos:pos + 4])[0]
        if sid == 2:
            return [str(int.from_bytes(b[pos + i * n8: pos + (i + 1) * n8], "little")) for i in range(1, n + 1)]
        pos += ln


def check(circuit, stem):
    """-> (witness_ok, public_equal_to_expected or None, line)."""
    exp = json.loads((INP / f"{stem}.public.json").read_text())["public"]
    if WASM:
        js = HERE / "build" / circuit / f"{circuit}_js"
        out = HERE / "build" / f"check_{circuit}.wtns"
        r = subprocess.run(["node", "--max-old-space-size=6000", str(js / "generate_witness.js"),
                            str(js / f"{circuit}.wasm"), str(INP / f"{stem}.input.json"), str(out)],
                           capture_output=True, text=True)
        if r.returncode:
            err = next((l for l in r.stderr.splitlines() if "Error in template" in l), r.stderr[-200:])
            return False, None, "REJECT wasm: " + err.strip()[:150]
        return True, parse_wtns(out, len(exp)) == exp, "ACCEPT (wasm)"
    r = subprocess.run([OA2, "check", circuit, str(INP / f"{stem}.input.json")], capture_output=True, text=True)
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT")), (r.stdout + r.stderr)[-300:])
    if " ACCEPT " not in line:
        return False, None, line[:160]
    got = line.split("public=[")[1].rstrip("]").split(",")
    return True, got == exp, line[:100]


def judge(label, want_accept, ok, pub_ok, line, res):
    # a witness that satisfies the circuit but whose public values differ from the honest derivation is a
    # verifier-level reject (the proof would not verify against the derived publics)
    accepted = ok and pub_ok is not False
    good = (ok and pub_ok) if want_accept else not accepted
    how = "ACCEPT" if accepted else ("ACCEPT witness, publics != derived -> verifier REJECT" if ok else "REJECT")
    print(f"{'PASS' if good else 'FAIL'}  {label:58} want={'accept' if want_accept else 'reject':6} got={how}  "
          f"{'' if ok else line}", flush=True)
    res.append(good)


def phone(fx, role, tamper="none", want=None, nf=False):
    info = prep("phone", fx, role, tamper=tamper, extra=["--nf"] if nf else [])
    if info.get("vacuous"):
        print(f"SKIP  {fx} {role} {tamper}: vacuous (claimed = honest)")
        return None
    ok, pub_ok, line = check(info["circuit"], info["stem"])
    return ok, pub_ok, line, info


def main():
    mode = sys.argv[1]
    res = []
    fixtures = sorted(p.stem for p in FIX.glob("*.json"))
    base = [f for f in fixtures if f.count("_") == 1]
    if mode == "phones":
        for fx in base:
            for r in "AB":
                ok, pub_ok, line, info = phone(fx, r)
                judge(f"{fx} {r} sr={info['sr']} honest", True, ok, pub_ok, line, res)
    elif mode == "tampers":
        for fx in ("180ca04b_48k", "180ca04b_mix"):
            for r in "AB":
                for t in ("half", "sr", "nonce", "swap_role", "sample", "resign_late", "resign_early"):
                    o = phone(fx, r, t)
                    if o:
                        judge(f"{fx} {r} tamper {t}", False, o[0], o[1], o[2], res)
        for fx, why in (("180ca04b_48k_sodfar", "sod 2401 > 50 ms tolerance"),
                        ("180ca04b_48k_sodwide", "sod 97 > delta 96 (completeness gap)")):
            o = phone(fx, "B")
            judge(f"{fx} B signed ({why})", False, o[0], o[1], o[2], res)
            o = phone(fx, "A")
            judge(f"{fx} A honest", True, o[0], o[1], o[2], res)
    elif mode == "pairs":
        for fx in base:
            info = prep("pair", fx)
            ok, pub_ok, line = check("oa2t_pair", info["stem"])
            judge(f"pair {fx} sr {info['srA']}/{info['srB']} label {info['label_cm']:.0f} flight {info['flight_cm']} "
                  f"{info['verdict']}", info["verdict"] == "NEAR", ok, pub_ok, line, res)
        for fx, t, want in (("180ca04b_mix", "sr", False), ("180ca04b_48k", "samekey", False),
                            ("9afb91c6_48k", "madeup", True)):
            info = prep("pair", fx, tamper=t)
            ok, pub_ok, line = check("oa2t_pair", info["stem"])
            judge(f"pair {fx} tamper {t}" + (" (circuit accepts; session verifier must reject)" if want else ""),
                  want, ok, pub_ok, line, res)
        info = prep("pair", "180ca04b_48k", extra=["--fixture-b", "b550cf12_48k"])
        ok, pub_ok, line = check("oa2t_pair", info["stem"])
        judge("pair splice A=180ca04b_48k B=b550cf12_48k", False, ok, pub_ok, line, res)
    elif mode == "edges":
        r = subprocess.run([PY, str(HERE / "prep_popt2.py"), "edges"], capture_output=True, text=True, check=True)
        for c in json.loads(r.stdout.strip().splitlines()[-1]):
            ok, pub_ok, line = check("oa2t_pair", c["stem"])
            judge(f"edge sr {c['srA']}/{c['srB']} hA {c['hA']} hB {c['hB']} exact={c['exact']} server={c['server']}"
                  f"{' TIE' if c['tie'] else ''}", c["exact"] == "NEAR", ok, pub_ok, line, res)
    print(f"\n{mode}: {sum(res)}/{len(res)} as expected")
    sys.exit(0 if all(res) else 1)


if __name__ == "__main__":
    main()

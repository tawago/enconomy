"""Accept/reject tests for optionA-v2 (witness generation + direct R1CS check through the oa2zk binary).

  python3 run_tests.py honest [d]        # all 12 sessions x 2 roles, sig circuit at delta d ms (default 2)
  python3 run_tests.py tamper [d]        # tamper list on 180ca04b (NEAR, 30 cm) and 9afb91c6 (200 cm)
  python3 run_tests.py notnear [d]       # 100 / 200 cm sessions end to end: per-phone accept, pair NEAR rejects
  python3 run_tests.py pairs [d]         # pair statement on all 12 sessions
Run the whole thing under ../tools/heavy.sh (1.3 M-constraint witnesses).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = str(HERE.parents[3] / "proximity-echo/.venv/bin/python3")
OA2 = str(HERE / "oa2zk.sh")
INP = HERE / "inputs"
FIX = HERE / "fixtures"
WASM = "--wasm" in sys.argv
if WASM:
    sys.argv.remove("--wasm")


def prep(*a, tamper="none"):
    args = [PY, str(HERE / "prep.py"), *map(str, a)] + (["--tamper", tamper] if tamper != "none" else [])
    return json.loads(subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip().splitlines()[-1])


def parse_wtns(path, n):
    import struct
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


def check(circuit, name):
    if WASM:
        js = HERE / "build" / circuit / f"{circuit}_js"
        out = HERE / "build" / "check.wtns"
        r = subprocess.run(["node", str(js / "generate_witness.js"), str(js / f"{circuit}.wasm"),
                            str(INP / f"{name}.input.json"), str(out)], capture_output=True, text=True)
        if r.returncode:
            err = next((l for l in r.stderr.splitlines() if "Error in template" in l), r.stderr[-200:])
            return False, None, "REJECT wasm witness: " + err
        exp = json.loads((INP / f"{name}.public.json").read_text())["public"]
        return True, parse_wtns(out, len(exp)) == exp, "ACCEPT (wasm)"
    r = subprocess.run([OA2, "check", circuit, str(INP / f"{name}.input.json")], capture_output=True, text=True)
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT")), r.stdout[-300:] + r.stderr[-300:])
    ok = " ACCEPT " in line
    pub_ok = None
    if ok:
        got = line.split("public=[")[1].rstrip("]").split(",")
        exp = json.loads((INP / f"{name}.public.json").read_text())["public"]
        pub_ok = got == exp
    return ok, pub_ok, line[:160]


def run_one(s8, d, role, variant, tamper="none", expect_accept=None):
    info = prep(s8, d, role, variant, tamper=tamper)
    name = f"{s8}_d{d}_{role}_{variant}" + ("" if tamper == "none" else f"_t-{tamper}")
    if tamper in ("late_self", "resign_late") and "claimed_half" not in info:
        print(f"SKIP {s8} d{d} {role} {variant:5s} {tamper:14s} -> vacuous: the honest a_self already sits at "
              f"p_self + delta (emulated offset = +delta), no later lag is claimable", flush=True)
        return True
    ok, pub_ok, line = check(f"oa2_d{d}_{variant}", name)
    if expect_accept is None:
        expect_accept = tamper == "none"
    good = (ok and pub_ok) if expect_accept else (not ok or pub_ok is False)
    how = "ACCEPT" if ok else "REJECT"
    if ok and pub_ok is False:
        how = "ACCEPT witness, public IO differs from the honest statement -> verifier REJECT"
    extra = {k: v for k, v in info.items() if k in ("claimed_half", "honest_half", "echo_lag_after_arrival", "echo_score", "other_session")}
    print(f"{'PASS' if good else 'FAIL'} {s8} d{d} {role} {variant:5s} {tamper:14s} -> {how}  {extra}  | {line if not ok else ''}", flush=True)
    return good


def pair(s8, d):
    info = prep("pair", s8, d)
    ok, pub_ok, line = check("oa2_pair", f"{s8}_pair_d{d}")
    near = info["verdict"] == "NEAR"
    good = (ok and pub_ok) if near else not ok
    print(f"{'PASS' if good else 'FAIL'} pair {s8} label {info['label_cm']:5.0f} flight {info['flight_cm']:7.2f} "
          f"{info['verdict']:8s} d={info['d']} bounds ({info['dLo']},{info['dHi']}) -> {'ACCEPT' if ok else 'REJECT'}", flush=True)
    return good


def main():
    mode = sys.argv[1]
    d = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    res = []
    sessions = sorted(p.stem for p in FIX.glob("*.json"))
    if mode == "honest":
        for s8 in sessions:
            for r in "AB":
                res.append(run_one(s8, d, r, "sig"))
    elif mode in ("tamper", "tamper_audio", "tamper_sig"):
        audio = ["late_self", "echo_self", "early_partner", "score", "sample", "sample_range", "path", "leafidx",
                 "template", "aself_outside", "pself", "swap_role"]
        sig = ["late_self", "early_partner", "swap_role", "template", "pself", "sample", "resign_late", "resign_early"]
        for s8 in (("180ca04b", "9afb91c6") if mode != "tamper_sig" else ()):
            for r in "AB":
                res.append(run_one(s8, d, r, "audio"))
                for t in audio:
                    res.append(run_one(s8, d, r, "audio", t))
        for r in ("AB" if mode != "tamper_audio" else ""):
            for t in sig:
                res.append(run_one("180ca04b", d, r, "sig", t))
    elif mode == "notnear":
        for s8 in sessions:
            fx = json.loads((FIX / f"{s8}.json").read_text())
            if fx["label_cm"] not in (100.0, 200.0):
                continue
            for r in "AB":
                res.append(run_one(s8, d, r, "sig"))
                res.append(run_one(s8, d, r, "sig", "resign_late"))
                res.append(run_one(s8, d, r, "sig", "resign_early"))
            res.append(pair(s8, d))
    elif mode == "pairs":
        for s8 in sessions:
            res.append(pair(s8, d))
    print(f"\n{mode} d{d}: {sum(res)}/{len(res)} as expected")


if __name__ == "__main__":
    main()

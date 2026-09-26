"""Tamper tests: every altered input must make witness generation fail (a constraint is violated).

  python tamper.py build/in_exact_K512.json build/arrival_exact_K512_js
"""
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

inp_path, js_dir = Path(sys.argv[1]), Path(sys.argv[2])
wasm = next(js_dir.glob("*.wasm"))
base = json.loads(inp_path.read_text())
K = len(base["I"])
ia = base.get("arr")


def witness(d):
    with tempfile.TemporaryDirectory() as t:
        p = Path(t) / "in.json"
        p.write_text(json.dumps(d))
        r = subprocess.run(["node", str(js_dir / "generate_witness.js"), str(wasm), str(p), str(Path(t) / "w.wtns")],
                           capture_output=True, text=True)
        lines = (r.stderr or r.stdout).strip().splitlines()
        hit = [ln.strip() for ln in lines if "Error in template" in ln or "Assert Failed" in ln
               or "Not enough values" in ln or "Too many values" in ln]
        return r.returncode == 0, (" | ".join(hit[:2])[:160] if hit else "")


def sel_for(a):
    return [1 if k <= a else 0 for k in range(K + 1)]


cases = []


def case(name, fn):
    d = copy.deepcopy(base)
    fn(d)
    cases.append((name, d))


case("honest", lambda d: None)
case("I[100] += 1 (one score, before arrival)", lambda d: d["I"].__setitem__(100, d["I"][100] + 1))
case("Q[400] -= 1 (one score, after arrival)", lambda d: d["Q"].__setitem__(400, d["Q"][400] - 1))
case("I[K-1] += 1 (last lag, no rule check there)", lambda d: d["I"].__setitem__(K - 1, d["I"][K - 1] + 1))
if ia is not None:
    case("I[arr] += 1 (score at the arrival)", lambda d: d["I"].__setitem__(ia, d["I"][ia] + 1))
case("x[6000] += 1, scores unchanged", lambda d: d["x"].__setitem__(6000, d["x"][6000] + 1))
case("x[0] = 40000 (out of int16)", lambda d: d["x"].__setitem__(0, 40000))
if ia is not None:
    def late(d, s):
        d["arr"] = ia + s
        d["sel"] = sel_for(ia + s)
        if "rsn" in d:
            for k in range(ia, ia + s):
                d["rsn"][k] = [1, 0, 0]
    case("claim arrival 1 lag late (reason a at the true one)", lambda d: late(d, 1))
    case("claim arrival 2 lags late", lambda d: late(d, 2))

    def late_b(d):
        late(d, 1)
        d["rsn"][ia] = [0, 1, 0]
    if "rsn" in base:
        case("claim 1 late, reason b (rising) at the true one", late_b)

        def late_c(d):
            late(d, 1)
            d["rsn"][ia] = [0, 0, 1]
        case("claim 1 late, reason c (falling) at the true one", late_c)

    def early(d, s):
        d["arr"] = ia - s
        d["sel"] = sel_for(ia - s)
        if "rsn" in d:
            for k in range(ia - s, ia):
                d["rsn"][k] = [0, 0, 0]
    case("claim arrival 3 lags early (rising edge)", lambda d: early(d, 3))

    def forge(d):
        # plant a fake candidate at lag 100: big score there, claim it; rule inputs consistent
        j = 100
        d["I"][j] = max(abs(v) for v in d["I"]) * 2
        d["arr"] = j
        d["sel"] = sel_for(j)
        if "rsn" in d:
            for k in range(K):
                d["rsn"][k] = [1, 0, 0] if k < j else [0, 0, 0]
    case("forge: plant a peak at lag 100 and claim it", forge)

ok_all = True
for name, d in cases:
    ok, msg = witness(d)
    want = name == "honest"
    good = ok == want
    ok_all &= good
    print(f"{'PASS' if good else 'FAIL'}  witness={'ok' if ok else 'rejected':8s}  {name}   {'' if ok else msg}")
print("ALL PASS" if ok_all else "SOME FAILED")
sys.exit(0 if ok_all else 1)

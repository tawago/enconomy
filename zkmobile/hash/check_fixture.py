#!/usr/bin/env python3
"""Python poseidon2.py vs the team's Noir helper on the real fixture.

usage: check_fixture.py HELPER_PROVER_TOML NARGO_EXECUTE_STDOUT [prep.json] [--dump vectors.json]
The helper (optA-noir/noir/helper) prints ([Field; 341] tree levels, code_commit, half_A, half_B).
"""
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "server"))
from pop import poseidon2 as p2  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
toml, out = pathlib.Path(args[0]).read_text(), pathlib.Path(args[1]).read_text()
prep = json.loads(pathlib.Path(args[2]).read_text()) if len(args) > 2 else None


def arr(name):
    m = re.search(r"^" + name + r" = \[(.*?)\]$", toml, re.M)
    return [int(v.strip().strip('"'), 0) for v in m.group(1).split(",")]


cap_u = arr("cap")
tm = {k: arr(k) for k in ("c_is", "c_qs", "c_ip", "c_qp")}
hc_a, hc_b = arr("hc_a"), arr("hc_b")
nums = [int(v, 16) for v in re.findall(r"0x[0-9a-fA-F]+", out.split("output:", 1)[1])]
assert len(nums) == 344, len(nums)
lv_n, code_n, ha_n, hb_n = nums[:341], nums[341], nums[342], nums[343]

x = [u - 32768 for u in cap_u]
while x and x[-1] == 0:
    x.pop()
t0 = time.perf_counter()
levels = p2.rec_levels(x)
t_tree = time.perf_counter() - t0
lv_p = [v for l in levels for v in l]
t0 = time.perf_counter()
code_p = p2.code_commitment_u8(tm["c_is"], tm["c_qs"], tm["c_ip"], tm["c_qp"])
t_code = time.perf_counter() - t0
ha_p = p2.hash_n(p2.TAG_HALF, hc_a)
hb_p = p2.hash_n(p2.TAG_HALF, hc_b)
leaf_ok = sum(a == b for a, b in zip(lv_p[:256], lv_n[:256]))
node_ok = sum(a == b for a, b in zip(lv_p[256:], lv_n[256:]))
print(f"capture samples (trimmed) {len(x)}; leaves match {leaf_ok}/256, nodes match {node_ok}/85")
print(f"rec_root  py {lv_p[-1]:#066x} {'==' if lv_p[-1] == lv_n[-1] else '!='} noir")
print(f"code      py {code_p:#066x} {'==' if code_p == code_n else '!='} noir")
print(f"half_A    py {ha_p:#066x} {'==' if ha_p == ha_n else '!='} noir")
print(f"half_B    py {hb_p:#066x} {'==' if hb_p == hb_n else '!='} noir")
if prep:
    print("prep json rec_root", "==" if int(prep["rec_root_p2"], 16) == lv_p[-1] else "!=",
          "code", "==" if int(prep["code_commit_p2"], 16) == code_p else "!=",
          "hcA", "==" if int(prep["halfCommit_A"], 16) == ha_p else "!=",
          "hcB", "==" if int(prep["halfCommit_B"], 16) == hb_p else "!=")
print(f"time: rec tree {t_tree:.3f} s, code_commit {t_code:.3f} s")
ok = lv_p == lv_n and code_p == code_n and ha_p == ha_n and hb_p == hb_n
if "--dump" in sys.argv:
    dst = pathlib.Path(sys.argv[sys.argv.index("--dump") + 1])
    dst.write_text(json.dumps({"root": hex(lv_n[-1]), "leaf0": hex(lv_n[0]), "leaf_last": hex(lv_n[255]),
                               "code": hex(code_n), "half_A": hex(ha_n), "half_B": hex(hb_n),
                               "hc_a": [str(v) for v in hc_a], "hc_b": [str(v) for v in hc_b]}, indent=1))
print("ALL MATCH" if ok else "MISMATCH")
sys.exit(0 if ok else 1)

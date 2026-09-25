"""Compare corr circuit public outputs with the integer answers from prep_corr.py."""
import json
import sys

P = 21888242871839275222246405745257275088548364400416034343698204186575808495617
pub = [int(v) for v in json.load(open(sys.argv[1]))]
exp = json.load(open(sys.argv[2]))
K = len(exp["I"])
signed = [v - P if v > P // 2 else v for v in pub]
got = {"I": signed[2:2 + K], "Q": signed[2 + K:2 + 2 * K],
       "env2": signed[2 + 2 * K:2 + 3 * K], "E": signed[2 + 3 * K:2 + 4 * K]}
ok = all(got[k] == exp[k] for k in got)
print("match" if ok else "MISMATCH", {k: (got[k][:2], exp[k][:2]) for k in got} if not ok else "")
print("score per lag", ["%.3f" % s for s in exp["score"]])

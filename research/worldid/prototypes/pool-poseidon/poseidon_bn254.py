"""circomlib-compatible Poseidon over BN254 Fr, n = 1..3 inputs (t = 2..4). Pure Python, no deps."""
import json, pathlib
P = 21888242871839275222246405745257275088548364400416034343698204186575808495617
_K = json.loads((pathlib.Path(__file__).parent / "poseidon_bn254_t2_t4.json").read_text())
_K = {int(k[1:]): (v["RF"], v["RP"], [int(x, 16) for x in v["C"]], [[int(x, 16) for x in r] for r in v["M"]]) for k, v in _K.items()}

def poseidon(inputs):
    t = len(inputs) + 1
    RF, RP, C, M = _K[t]
    s = [0] + [x % P for x in inputs]
    for r in range(RF + RP):
        s = [(x + C[r * t + i]) % P for i, x in enumerate(s)]
        full = r < RF // 2 or r >= RF // 2 + RP
        s = [pow(x, 5, P) if (full or i == 0) else x for i, x in enumerate(s)]
        s = [sum(M[i][j] * s[j] for j in range(t)) % P for i in range(t)]
    return s[0]

if __name__ == "__main__":
    g = json.load(open(pathlib.Path(__file__).parent / "golden.json"))
    bad = [c["name"] for c in g["cases"] if poseidon([int(x, 16) for x in c["in"]]) != int(c["out"], 16)]
    print("PY ALL AGREE" if not bad else f"PY MISMATCH {bad}")

"""Writes the zk parity vectors (commonTest/resources/zk/*.json) by running the spike's own python.

Run: $PY gen_vectors.py   ($PY = research/proximity-echo/.venv/bin/python3). Reads research/ only.
Needs the spike's optionA-v2/build/popt2 captures (gitignored there, present on the dev Mac).
"""
import base64
import hashlib
import json
import random
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
REPO = HERE.parents[6]
ZK = REPO / "research/sound-bound/spikes/zk"
OA2 = ZK / "optionA-v2"
sys.path.insert(0, str(OA2))
sys.path.insert(0, str(OA2 / "poseidon7"))
import p7  # noqa: E402
import rectree  # noqa: E402
import oa_rate  # noqa: E402

P = p7.P
H = lambda v: "%064x" % (v % P)  # noqa: E731

# (fixture, role) captures copied as pcm16 LE base64; two sessions, both rates.
CAPTURES = [("180ca04b_48k", "A"), ("180ca04b_48k", "B"), ("2940913c_mix", "B")]
# code_commit parity: every role of these fixtures.
CODES = ["180ca04b_48k", "180ca04b_mix", "2940913c_mix", "7711d899_48k"]


def write(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=1) + "\n")
    print("wrote", name)


def p7_vectors():
    rng = random.Random(7)
    v = {"p": "%064x" % P, "perm": [], "node5": [], "sponge16": [], "pack_leaf": [],
         "leaf_hash": [], "zero_nodes": [H(z) for z in rectree.zero_nodes()], "rec_root": []}
    states = [list(range(5)), list(range(16)), [P - 1] * 5, [P - 1] * 16, [0] * 5, [0] * 16,
              [rng.randrange(P) for _ in range(5)], [rng.randrange(P) for _ in range(16)]]
    for s in states:
        v["perm"].append({"in": [H(x) for x in s], "out": [H(x) for x in p7.perm(s)]})
    for c in ([1, 2, 3, 4], [0, 0, 0, 0], [rng.randrange(P) for _ in range(4)]):
        v["node5"].append({"in": [H(x) for x in c], "out": H(p7.node5(c))})
    cases = [(6, [1], 1), (5, [1, 2, 3], 1), (8, list(range(1, 10)), 1), (8, [], 2),
             (3, [rng.randrange(P) for _ in range(15)], 2), (9 + (16 << 8), [rng.randrange(P) for _ in range(16)], 2),
             (p7.TAG_LEAF, [rng.randrange(1 << 240) for _ in range(69)], 2)]
    for tag, xs, nout in cases:
        o = p7.sponge16(tag, xs, nout)
        o = o if nout > 1 else [o]
        v["sponge16"].append({"tag": tag, "in": [H(x) for x in xs], "out": [H(x) for x in o]})
    leaves = [[0] * 1024, [(37 * i % 65536) - 32768 for i in range(1024)],
              [rng.randrange(-32768, 32768) for _ in range(1024)], [32767] * 512 + [-32768] * 512]
    for x in leaves:
        pk = p7.pack_leaf(x)
        b = np.asarray(x, dtype="<i2").tobytes()
        v["pack_leaf"].append({"pcm16_b64": base64.b64encode(b).decode(), "packed": [H(e) for e in pk]})
        v["leaf_hash"].append({"pcm16_b64": base64.b64encode(b).decode(), "out": H(p7.leaf_hash(x))})
    for n, mul in ((0, 1), (1, 1), (3000, 7919), (1024, 7919), (4097, 31), (16385, 12345)):
        x = [(mul * i % 65536) - 32768 for i in range(n)]
        lv = rectree.build(x, procs=4)
        idx = max(0, (n + 1023) // 1024 - 1)
        v["rec_root"].append({"n": n, "mul": mul, "root": H(rectree.root(lv)), "path_leaf": idx,
                              "path": [[H(c) for c in lvl] for lvl in rectree.path(lv, idx)]})
    write("p7_vectors.json", v)


def fixture(name):
    return json.loads((ZK / "fixtures/popt_v2" / f"{name}.json").read_text())


def captures():
    for name, role in CAPTURES:
        d = fixture(name)
        r = d["roles"][role]
        x = np.load(ZK / r["capture_npy"])
        assert x.dtype == np.int16 and len(x) == r["capture_frames"]
        tr = base64.b64decode(r["transcript_b64"])
        root = int(r["rec_root"], 16)
        assert tr[177:209] == root.to_bytes(32, "big"), "transcript rec_root"
        lv = rectree.load(json.loads((ZK / r["tree_json"]).read_text()))
        assert rectree.root(lv) == root
        nl = len(lv[0])
        paths = {str(i): [[H(c) for c in lvl] for lvl in rectree.path(lv, i)] for i in (0, 27, nl - 1)}
        write(f"rec_{name}_{role}.json", {
            "fixture": name, "role": role, "sample_rate": r["sample_rate"], "frames": len(x),
            "pcm16_b64": base64.b64encode(x.astype("<i2").tobytes()).decode(),
            "rec_root": H(root), "levels": [[H(lv[l][i]) for i in sorted(lv[l])] for l in range(len(lv))],
            "paths": paths})


def codes():
    out = []
    for name in CODES:
        d = fixture(name)
        for role in "AB":
            r = d["roles"][role]
            sr = r["sample_rate"]
            other = "B" if role == "A" else "A"
            cIs, cQs = oa_rate.templates(d["seed_hex"], role, sr)
            cIp, cQp = oa_rate.templates(d["seed_hex"], other, sr)
            cc = oa_rate.code_commit(cIs, cQs, cIp, cQp)
            assert cc.hex() == r["code_commit"], (name, role)
            tr = base64.b64decode(r["transcript_b64"])
            assert tr[279:311] == cc
            b = lambda a: base64.b64encode(np.asarray(a, dtype=np.int8).tobytes()).decode()  # noqa: E731
            out.append({"fixture": name, "role": role, "sample_rate": sr, "n": len(cIs),
                        "cI_self_b64": b(cIs), "cQ_self_b64": b(cQs), "cI_partner_b64": b(cIp),
                        "cQ_partner_b64": b(cQp), "code_commit": cc.hex()})
    write("code_commit.json", {"tag": "pop-code-v2", "cases": out})


if __name__ == "__main__":
    what = sys.argv[1:] or ["p7", "captures", "codes"]
    if "p7" in what:
        p7_vectors()
    if "captures" in what:
        captures()
    if "codes" in what:
        codes()

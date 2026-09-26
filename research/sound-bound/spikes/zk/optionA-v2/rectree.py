"""rec_root for POPT v2 (docs/pop-transcript-v2.md): 4-ary Poseidon7 Merkle tree of DEPTH 4 over the capture.

Same leaf and node hashes as poseidon7/p7.py (1,024 int16 samples per leaf, packed 15 per element,
sponge16 TAG_LEAF; node = Perm7(5)[TAG_NODE, c0..c3][1]); only the depth differs. 4^4 = 256 leaves =
262,144 samples >= CAPTURE_S * SR_MAX = 240,000, so one tree shape covers every allowed rate. Missing leaves
are zero-sample leaves (as p7.py). The old spike tree (depth 6, whole 87 s file) is unchanged in p7.py.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "poseidon7"))
import p7  # noqa: E402

DEPTH = 4
NLEAVES = 4 ** DEPTH
IDX_BITS = 2 * DEPTH


@lru_cache(None)
def zero_nodes():
    z = [p7.leaf_hash([0] * p7.LEAF)]
    for _ in range(DEPTH):
        z.append(p7.node5([z[-1]] * 4))
    return z


def build(x, procs=4):
    import numpy as np
    x = np.asarray(x, dtype=np.int64)
    n = (len(x) + p7.LEAF - 1) // p7.LEAF
    assert n <= NLEAVES
    xp = np.zeros(n * p7.LEAF, dtype=np.int64)
    xp[: len(x)] = x
    chunks = [xp[i * p7.LEAF:(i + 1) * p7.LEAF].tolist() for i in range(n)]
    if procs > 1:
        from multiprocessing import Pool
        with Pool(procs) as pool:
            hs = pool.map(p7.leaf_hash, chunks)
    else:
        hs = [p7.leaf_hash(c) for c in chunks]
    z = zero_nodes()
    levels = [dict(enumerate(hs))]
    for l in range(DEPTH):
        cur = levels[-1]
        levels.append({j: p7.node5([cur.get(4 * j + k, z[l]) for k in range(4)])
                       for j in sorted({i // 4 for i in cur})})
    return levels


def root(levels):
    return levels[DEPTH].get(0, zero_nodes()[DEPTH])


def path(levels, leaf_idx):
    z = zero_nodes()
    out, i = [], leaf_idx
    for l in range(DEPTH):
        base = (i // 4) * 4
        out.append([levels[l].get(base + k, z[l]) for k in range(4)])
        i //= 4
    return out


def dump(levels):
    return {"depth": DEPTH, "levels": [{str(k): hex(v) for k, v in lvl.items()} for lvl in levels]}


def load(d):
    assert d["depth"] == DEPTH
    return [{int(k): int(v, 16) for k, v in lvl.items()} for lvl in d["levels"]]

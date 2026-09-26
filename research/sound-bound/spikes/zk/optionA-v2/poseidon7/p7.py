"""Poseidon alpha=7 over the P-256 base field (research instantiation, params from gen_params.py),
plus the recording commitment and the Fiat-Shamir sponge used by the optionA-v2 circuit.

Conventions (the circuit in ../circuits/p7.circom does exactly the same):
  permutation   per round r: state += C[r*t : r*t+t]; S-box x^7 on all cells (full rounds: the first
                R_F/2 and the last R_F/2) or on cell 0 (partial rounds); state = M . state
  sponge16      t = 16, rate 15, capacity cell 0 = domain tag; absorb by adding into cells 1..15,
                permute after every block (last block zero-padded; lengths are fixed per tag);
                output cells 1, 2 (squeeze without an extra permutation)
  node5         t = 5: state = [TAG_NODE, c0, c1, c2, c3], permute, output cell 1
  leaf          1,024 int16 samples, u = x + 32768 in [0, 2^16), packed 15 per element
                (e_j = sum_i u_{15j+i} 2^(16 i), 69 elements), sponge16 with TAG_LEAF
  tree          4-ary, depth 6 (4,096 leaves = 87 s at 48 kHz); the recording is zero-padded to
                whole leaves and the tree to 4,096 leaves; rec_root = the node at depth 6
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
LEAF = 1024
PACK = 15
NPACK = (LEAF + PACK - 1) // PACK      # 69
DEPTH = 6
ARITY = 4
NLEAVES = ARITY ** DEPTH               # 4096
TAG_LEAF = 1 + (LEAF << 8)
TAG_NODE = 2
TAG_FS = 3
TAG_HALF = 4
TAG_NULL = 5
TAG_HOLD = 6


@lru_cache(None)
def params(t):
    d = json.loads((HERE / f"params_t{t}.json").read_text())
    C = [int(c, 16) for c in d["C"]]
    M = [[int(v, 16) for v in row] for row in d["M"]]
    return d["R_F"], d["R_P"], C, M


def perm(state):
    t = len(state)
    R_F, R_P, C, M = params(t)
    s = list(state)
    half = R_F // 2
    for r in range(R_F + R_P):
        s = [(a + C[r * t + i]) % P for i, a in enumerate(s)]
        if r < half or r >= half + R_P:
            s = [pow(a, 7, P) for a in s]
        else:
            s[0] = pow(s[0], 7, P)
        s = [sum(m * a for m, a in zip(row, s)) % P for row in M]
    return s


def sponge16(tag, xs, nout=1):
    s = [tag % P] + [0] * 15
    xs = [v % P for v in xs]
    nb = max(1, (len(xs) + 14) // 15)
    for b in range(nb):
        blk = xs[15 * b: 15 * b + 15]
        blk += [0] * (15 - len(blk))
        s = [s[0]] + [(s[1 + i] + blk[i]) % P for i in range(15)]
        s = perm(s)
    return s[1: 1 + nout] if nout > 1 else s[1]


def node5(children):
    assert len(children) == 4
    return perm([TAG_NODE] + [c % P for c in children])[1]


def pack_leaf(samples):
    assert len(samples) == LEAF
    out = []
    for j in range(NPACK):
        v = 0
        for i, x in enumerate(samples[PACK * j: PACK * j + PACK]):
            assert -32768 <= x <= 32767
            v += (int(x) + 32768) << (16 * i)
        out.append(v)
    return out


def leaf_hash(samples):
    return sponge16(TAG_LEAF, pack_leaf(samples))


@lru_cache(None)
def zero_nodes():
    """zero_nodes()[l] = hash of an all-zero subtree at level l (level 0 = a zero leaf)."""
    z = [leaf_hash([0] * LEAF)]
    for _ in range(DEPTH):
        z.append(node5([z[-1]] * 4))
    return z


def _leaf_worker(chunk):
    return [leaf_hash(c) for c in chunk]


def build_tree(x, procs=4):
    """x: int16 sequence. Returns levels[0..DEPTH] as dicts {index: value} (absent = zero subtree)."""
    import numpy as np
    x = np.asarray(x, dtype=np.int64)
    n = (len(x) + LEAF - 1) // LEAF
    assert n <= NLEAVES
    xp = np.zeros(n * LEAF, dtype=np.int64)
    xp[: len(x)] = x
    chunks = [xp[i * LEAF:(i + 1) * LEAF].tolist() for i in range(n)]
    if procs > 1:
        from multiprocessing import Pool
        step = (n + procs * 4 - 1) // (procs * 4)
        parts = [chunks[i: i + step] for i in range(0, n, step)]
        with Pool(procs) as pool:
            hs = [h for part in pool.map(_leaf_worker, parts) for h in part]
    else:
        hs = _leaf_worker(chunks)
    z = zero_nodes()
    levels = [dict(enumerate(hs))]
    for l in range(DEPTH):
        cur = levels[-1]
        nxt = {}
        for j in sorted({i // 4 for i in cur}):
            nxt[j] = node5([cur.get(4 * j + k, z[l]) for k in range(4)])
        levels.append(nxt)
    return levels


def root(levels):
    return levels[DEPTH].get(0, zero_nodes()[DEPTH])


def path(levels, leaf_idx):
    """For each level l < DEPTH: the 4 children of the parent of the node on the path (incl. itself)."""
    z = zero_nodes()
    out = []
    i = leaf_idx
    for l in range(DEPTH):
        base = (i // 4) * 4
        out.append([levels[l].get(base + k, z[l]) for k in range(4)])
        i //= 4
    return out


def check_path(leaf_value, leaf_idx, sibs, rt):
    cur, i = leaf_value, leaf_idx
    for l in range(DEPTH):
        if sibs[l][i % 4] != cur:
            return False
        cur = node5(sibs[l])
        i //= 4
    return cur == rt


def to_signed(v):
    v %= P
    return v - P if v > P // 2 else v


if __name__ == "__main__":
    import time
    t0 = time.time()
    for t in (5, 16):
        s = perm(list(range(t)))
        print(f"t={t} perm(0..{t-1})[0:2] = {hex(s[0])[:20]}.. {hex(s[1])[:20]}..")
    n = 50
    t0 = time.time()
    for _ in range(n):
        perm(list(range(16)))
    print(f"t=16 perm: {(time.time()-t0)/n*1e3:.2f} ms")

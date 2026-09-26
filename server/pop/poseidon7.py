"""Poseidon x^7 over the P-256 base field, and rec_root (POPT v2 §2). Vendored port of the optionA-v2 spike.

Source: research/sound-bound/spikes/zk/optionA-v2/poseidon7/p7.py (perm, sponge16, node5, pack_leaf, leaf_hash)
and optionA-v2/rectree.py (depth-4 tree). Parameters: p7params/params_t{5,16}.json, copied byte for byte.

  perm       per round r: s += C[r*t : r*t+t]; x^7 on every cell (first/last R_F/2 rounds) or cell 0; s = M.s
  sponge16   t = 16, cell 0 = tag (set), absorb 15 per block by adding into cells 1..15, output cell 1
  node5      perm5([TAG_NODE, c0, c1, c2, c3])[1]
  leaf       1,024 int16 samples, u = x + 32768, 15 per element little-endian (69 elements), sponge16(TAG_LEAF)
  tree       4-ary, depth 4 (256 leaves); missing leaves = leaves of zero samples; rec_root = level-4 node

Research instantiation, not audited. leaf_hashes() runs every leaf of a capture in lockstep on numpy object
arrays (same integers as the scalar path, ~5x faster).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
LEAF = 1024
PACK = 15
NPACK = (LEAF + PACK - 1) // PACK      # 69
DEPTH = 4
NLEAVES = 4 ** DEPTH                   # 256 leaves = 262,144 frames >= 2.5 s at 96 kHz
TAG_LEAF = 1 + (LEAF << 8)
TAG_NODE = 2
TAG_NULL = 5
TAG_HOLD = 6
TAG_HALF2 = 8
PARAMS = Path(__file__).resolve().parent / "p7params"


@lru_cache(None)
def params(t: int):
    d = json.loads((PARAMS / f"params_t{t}.json").read_text())
    assert int(d["p"], 16) == P and d["t"] == t and d["alpha"] == 7
    C = [int(c, 16) for c in d["C"]]
    M = [[int(v, 16) for v in row] for row in d["M"]]
    assert len(C) == (d["R_F"] + d["R_P"]) * t and len(M) == t
    return d["R_F"], d["R_P"], C, M


def perm(state) -> list[int]:
    t = len(state)
    R_F, R_P, C, M = params(t)
    s = [a % P for a in state]
    half = R_F // 2
    for r in range(R_F + R_P):
        s = [(a + C[r * t + i]) % P for i, a in enumerate(s)]
        if r < half or r >= half + R_P:
            s = [pow(a, 7, P) for a in s]
        else:
            s[0] = pow(s[0], 7, P)
        s = [sum(m * a for m, a in zip(row, s)) % P for row in M]
    return s


def sponge16(tag: int, xs, nout: int = 1):
    s = [tag % P] + [0] * 15
    xs = [int(v) % P for v in xs]
    for b in range(max(1, (len(xs) + 14) // 15)):
        blk = xs[15 * b: 15 * b + 15]
        blk += [0] * (15 - len(blk))
        s = perm([s[0]] + [(s[1 + i] + blk[i]) % P for i in range(15)])
    return s[1: 1 + nout] if nout > 1 else s[1]


def node5(children) -> int:
    if len(children) != 4:
        raise ValueError("node5 takes 4 children")
    return perm([TAG_NODE] + [int(c) % P for c in children])[1]


def pack_leaf(samples) -> list[int]:
    if len(samples) != LEAF:
        raise ValueError(f"leaf needs {LEAF} samples")
    out = []
    for j in range(NPACK):
        v = 0
        for i, x in enumerate(samples[PACK * j: PACK * j + PACK]):
            x = int(x)
            if not -32768 <= x <= 32767:
                raise ValueError("sample outside int16")
            v += (x + 32768) << (16 * i)
        out.append(v)
    return out


def leaf_hash(samples) -> int:
    return sponge16(TAG_LEAF, pack_leaf(samples))


# -- lockstep path: n leaves at once, state = t object arrays of length n

def _pow7(a):
    a2 = a * a % P
    return a2 * a2 % P * a2 % P * a % P


def _perm_vec(s: list, t: int) -> list:
    R_F, R_P, C, M = params(t)
    Mo = np.array(M, dtype=object)
    half = R_F // 2
    S = np.stack([np.asarray(v, dtype=object) for v in s])
    for r in range(R_F + R_P):
        S = S + np.array(C[r * t:(r + 1) * t], dtype=object)[:, None]
        if r < half or r >= half + R_P:
            S = _pow7(S)
        else:
            S[0] = _pow7(S[0])
        S = Mo.dot(S) % P
    return list(S)


def _pack_many(x: np.ndarray) -> np.ndarray:
    """x: (n, 1024) int16-range -> (n, 69) object array of packed elements."""
    u = (np.asarray(x, dtype=np.int64) + 32768).astype(object)
    u = np.concatenate([u, np.zeros((u.shape[0], NPACK * PACK - LEAF), dtype=object)], axis=1)
    u = u.reshape(u.shape[0], NPACK, PACK)
    sh = np.array([1 << (16 * i) for i in range(PACK)], dtype=object)
    return (u * sh).sum(axis=2)


def leaf_hashes(x) -> list[int]:
    """All leaves of capture x (zero samples past the end), in index order."""
    x = np.asarray(x, dtype=np.int64)
    if x.size and (x.min() < -32768 or x.max() > 32767):
        raise ValueError("sample outside int16")
    n = max(1, -(-x.size // LEAF))
    xp = np.zeros(n * LEAF, dtype=np.int64)
    xp[: x.size] = x
    e = _pack_many(xp.reshape(n, LEAF))
    z = np.zeros(n, dtype=object)
    s = [np.full(n, TAG_LEAF, dtype=object)] + [z.copy() for _ in range(15)]
    for b in range(-(-NPACK // 15)):
        for i in range(15):
            j = 15 * b + i
            if j < NPACK:
                s[1 + i] = (s[1 + i] + e[:, j]) % P
        s = _perm_vec(s, 16)
    return [int(v) for v in s[1]]


@lru_cache(None)
def zero_nodes() -> tuple[int, ...]:
    z = [leaf_hash([0] * LEAF)]
    for _ in range(DEPTH):
        z.append(node5([z[-1]] * 4))
    return tuple(z)


def levels_from_leaves(hs: list[int]) -> list[dict[int, int]]:
    if len(hs) > NLEAVES:
        raise ValueError(f"capture over {NLEAVES} leaves")
    z = zero_nodes()
    levels = [dict(enumerate(hs))]
    for lv in range(DEPTH):
        cur = levels[-1]
        levels.append({j: node5([cur.get(4 * j + k, z[lv]) for k in range(4)]) for j in sorted({i // 4 for i in cur})})
    return levels


def build(x) -> list[dict[int, int]]:
    """Tree levels 0..DEPTH as {index: value}; absent = zero subtree."""
    return levels_from_leaves(leaf_hashes(x))


def root_of(levels) -> int:
    return levels[DEPTH].get(0, zero_nodes()[DEPTH])


def rec_root(x) -> bytes:
    """32-byte big-endian rec_root of an int16 capture."""
    return root_of(build(x)).to_bytes(32, "big")


def path(levels, leaf_idx: int) -> list[list[int]]:
    """Per level: the 4 children of the parent of the node on the path (including itself)."""
    z = zero_nodes()
    out, i = [], leaf_idx
    for lv in range(DEPTH):
        base = (i // 4) * 4
        out.append([levels[lv].get(base + k, z[lv]) for k in range(4)])
        i //= 4
    return out

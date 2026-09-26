// Small reference vectors for the Python / Kotlin ports of oalib's Poseidon2 hashes (unconstrained, never proven).
// Inputs are generated here from fixed formulas (mirrored in gen_vectors.py), so Prover.toml only carries `seed`.
use oalib::{code_commitment, hash_n, leaf_hash, node_hash, L, TAG_HALF, TAG_NODE};
use poseidon::poseidon2::Poseidon2;
use std::hash::poseidon2_permutation;

unconstrained fn lhash(f: fn(u32) -> u16) -> Field {
    let mut x: [u16; 1024] = [0; 1024];
    for i in 0..1024 {
        x[i] = f(i);
    }
    leaf_hash(x, 0)
}

unconstrained fn main(seed: Field) -> pub ([Field; 4], [Field; 4], [Field; 8], [Field; 3], Field, Field, Field, [Field; 3], Field) {
    // permutation
    let p0 = poseidon2_permutation([0, 1, 2, 3]);
    let p1 = poseidon2_permutation([seed, seed + 1, -1, 12345678901234567890]);
    // Sp hash_n, lengths 0..7, tag 5, x_i = seed * (i + 1) + i
    let mut xs: [Field; 7] = [0; 7];
    for i in 0..7 {
        xs[i] = seed * (i as Field + 1) + i as Field;
    }
    let empty: [Field; 0] = [];
    let h: [Field; 8] = [
        hash_n(5, empty),
        hash_n(5, [xs[0]]),
        hash_n(5, [xs[0], xs[1]]),
        hash_n(5, [xs[0], xs[1], xs[2]]),
        hash_n(5, [xs[0], xs[1], xs[2], xs[3]]),
        hash_n(5, [xs[0], xs[1], xs[2], xs[3], xs[4]]),
        hash_n(5, [xs[0], xs[1], xs[2], xs[3], xs[4], xs[5]]),
        hash_n(5, xs),
    ];
    // leaves: u_i = (i * 7919 + 13) mod 65536; all 32768 (silent); all 65535
    let lv = [lhash(|i| ((i * 7919 + 13) % 65536) as u16), lhash(|_| 32768), lhash(|_| 65535)];
    let nd = node_hash([lv[0], lv[1], lv[2], seed]);
    let _ = TAG_NODE;
    // code commitment: u8 template k, index i = (i * 37 + k * 11 + 5) mod 256
    let mut t: [[u8; L]; 4] = [[0; L]; 4];
    for k in 0..4 {
        for i in 0..L {
            t[k][i] = ((i * 37 + k * 11 + 5) % 256) as u8;
        }
    }
    let cc = code_commitment(t[0], t[1], t[2], t[3]);
    // half: nonce_hi, nonce_lo, attempt, role_b, sr, half (negative), salt, X own hi/lo, X partner hi/lo
    let two128m1 = 340282366920938463463374607431768211455;
    let hc = hash_n(
        TAG_HALF,
        [
            two128m1, seed, 3, 1, 48000, -45042, 0xdeadbeefcafebabe, two128m1 - 1, 7, 0x0123456789abcdef0123456789abcdef,
            0xfedcba9876543210fedcba9876543210,
        ],
    );
    // holder_commit, both conventions
    let secret = seed * seed + 0x1234;
    let ho = [Poseidon2::hash([secret], 1), hash_n(11, [secret]), secret];
    (p0, p1, h, lv, nd, cc, hc, ho, seed)
}

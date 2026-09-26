// Witness-prep helper (unconstrained, never proven): Poseidon2 rec tree over the whole capture (256 leaves,
// depth 4), the Poseidon2 code commitment of the four templates, and two half commitments (for the pair input).
use oalib::{code_commitment, hash_n, leaf_hash, node_hash, L, TAG_HALF};
unconstrained fn main(
    cap: [u16; 262144],
    c_is: [u8; L],
    c_qs: [u8; L],
    c_ip: [u8; L],
    c_qp: [u8; L],
    hc_a: [Field; 11],
    hc_b: [Field; 11],
) -> pub ([Field; 341], Field, Field, Field) {
    let mut lv: [Field; 341] = [0; 341];
    for i in 0..256 {
        lv[i] = leaf_hash(cap, i * 1024);
    }
    let mut base = 0;
    let mut n = 256;
    for _ in 0..4 {
        let nb = base + n;
        for j in 0..n / 4 {
            lv[nb + j] = node_hash([lv[base + 4 * j], lv[base + 4 * j + 1], lv[base + 4 * j + 2], lv[base + 4 * j + 3]]);
        }
        base = nb;
        n = n / 4;
    }
    (lv, code_commitment(c_is, c_qs, c_ip, c_qp), hash_n(TAG_HALF, hc_a), hash_n(TAG_HALF, hc_b))
}

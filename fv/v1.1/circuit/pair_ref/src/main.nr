// Pair statement (oa2t_pair): opens both hiding half commitments with crossed keys, checks NEAR with both rates.
use oalib::{hash_n, TAG_HALF};
fn main(
    nonce_hi: pub Field,
    nonce_lo: pub Field,
    attempt: pub u8,
    commit_a: pub Field,
    commit_b: pub Field,
    sr_a: pub u32,
    sr_b: pub u32,
    half_a: Field,
    salt_a: Field,
    half_b: Field,
    salt_b: Field,
    xa: [Field; 2],
    xb: [Field; 2],
) {
    let at = attempt as Field;
    let sa = sr_a as Field;
    let sb = sr_b as Field;
    let ca = hash_n(TAG_HALF, [nonce_hi, nonce_lo, at, 0, sa, half_a, salt_a, xa[0], xa[1], xb[0], xb[1]]);
    assert(ca == commit_a);
    let cb = hash_n(TAG_HALF, [nonce_hi, nonce_lo, at, 1, sb, half_b, salt_b, xb[0], xb[1], xa[0], xa[1]]);
    assert(cb == commit_b);
    assert((xa[0] != xb[0]) | (xa[1] != xb[1]));
    (half_a + 2147483648).assert_max_bit_size::<32>();
    (half_b + 2147483648).assert_max_bit_size::<32>();
    (sa - 36000).assert_max_bit_size::<17>();
    (96000 - sa).assert_max_bit_size::<17>();
    (sb - 36000).assert_max_bit_size::<17>();
    (96000 - sb).assert_max_bit_size::<17>();
    // NEAR iff -20 < c/2 (hA/srA - hB/srB) < 60 cm, c = 34300 cm/s; times 2 srA srB > 0
    let n = half_a * sb - half_b * sa;
    let s = sa * sb;
    (34300 * n + 40 * s - 1).assert_max_bit_size::<70>();
    (120 * s - 34300 * n - 1).assert_max_bit_size::<70>();
}

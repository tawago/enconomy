// One pair proof: both halves + NEAR inside. Public: issuer key, now, scope, context; outputs nonce, pair_tag, 2 nullifiers.
use poplib::{unpack_issuer, check_half, nullifier, to_signed};
fn main(
    t_a: [u8; 311], s_a: [u8; 64], c_a: [u8; 111], cs_a: [u8; 64], hs_a: Field,
    t_b: [u8; 311], s_b: [u8; 64], c_b: [u8; 111], cs_b: [u8; 64], hs_b: Field,
    issuer: pub [Field; 4], now: pub u64, scope: pub Field, context: pub Field,
) -> pub ([Field; 2], Field, Field, Field) {
    let (issuer_x, issuer_y) = unpack_issuer(issuer);
    let a = check_half(t_a, s_a, c_a, cs_a, hs_a, issuer_x, issuer_y, now);
    let b = check_half(t_b, s_b, c_b, cs_b, hs_b, issuer_x, issuer_y, now);
    assert(a.role == 0x41); assert(b.role == 0x42);
    assert(a.pair_tag == b.pair_tag); // same nonce, attempt, and crossed keys
    let _ = context;
    // NEAR: -20 < 34300/2 * (hA/srA - hB/srB) < 60   (cm), times srA*srB > 0
    let ha = to_signed(a.half); let hb = to_signed(b.half);
    assert((ha < 1048576) & (ha > -1048576) & (hb < 1048576) & (hb > -1048576));
    assert((a.sr < 131072) & (b.sr < 131072) & (a.sr > 0) & (b.sr > 0));
    let sa = a.sr as i64; let sb = b.sr as i64;
    let f = 17150 * (ha * sb - hb * sa);
    assert(f > -20 * sa * sb);
    assert(f < 60 * sa * sb);
    (a.nonce, a.pair_tag, nullifier(hs_a, scope), nullifier(hs_b, scope))
}

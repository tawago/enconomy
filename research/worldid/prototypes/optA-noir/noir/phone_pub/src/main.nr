// Option A per phone, faithful variant: same public interface as oa2t_s48 (48,000 public template values,
// code_commit = SHA-256 of the templates as 2 x 128-bit public limbs, recomputed by the verifier).
use oalib::{check_signed, phone_core, K, L, NL, NT};
fn main(
    nonce_hi: pub Field,
    nonce_lo: pub Field,
    attempt: pub u8,
    role_b: pub bool,
    code_hi: pub Field,
    code_lo: pub Field,
    c_is: pub [Field; L],
    c_qs: pub [Field; L],
    c_ip: pub [Field; L],
    c_qp: pub [Field; L],
    issuer: pub [Field; 4],
    sr: pub u32,
    valid_at: pub u64,
    t: [u8; 311],
    sig: [u8; 64],
    exp: [u8; 8],
    hold: [u8; 32],
    csig: [u8; 64],
    salt: Field,
    xs: [u16; NT],
    chs: [[[Field; 4]; 4]; NL],
    leaf_s: Field,
    xp: [u16; NT],
    chp: [[[Field; 4]; 4]; NL],
    leaf_p: Field,
    ci: [Field; K],
    cq: [Field; K],
    u: [bool; K],
) -> pub Field {
    let h: [u8; 16] = code_hi.to_be_bytes();
    let l: [u8; 16] = code_lo.to_be_bytes();
    let mut cb = [0u8; 32];
    for i in 0..16 {
        cb[i] = h[i];
        cb[16 + i] = l[i];
    }
    let sg = check_signed(t, sig, exp, hold, csig, nonce_hi, nonce_lo, attempt, role_b, issuer, sr, valid_at, cb);
    phone_core(
        nonce_hi, nonce_lo, attempt, role_b, sr, [code_hi, code_lo], sg, salt, c_is, c_qs, c_ip, c_qp, xs, chs,
        leaf_s, xp, chp, leaf_p, ci, cq, u,
    )
}

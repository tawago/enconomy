// Option A per phone, onchain variant: templates private, bound by a Poseidon2 code commitment (public input,
// attested by the server) that is also the signed code_commit field of the transcript.
use oalib::{check_signed, code_commitment, phone_core, K, L, NL, NT};
fn main(
    nonce_hi: pub Field,
    nonce_lo: pub Field,
    attempt: pub u8,
    role_b: pub bool,
    code_commit: pub Field,
    issuer: pub [Field; 4],
    sr: pub u32,
    valid_at: pub u64,
    t: [u8; 311],
    sig: [u8; 64],
    exp: [u8; 8],
    hold: [u8; 32],
    csig: [u8; 64],
    salt: Field,
    c_is: [u8; L],
    c_qs: [u8; L],
    c_ip: [u8; L],
    c_qp: [u8; L],
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
    let cc = code_commitment(c_is, c_qs, c_ip, c_qp);
    assert(cc == code_commit);
    let cb: [u8; 32] = cc.to_be_bytes();
    let sg = check_signed(t, sig, exp, hold, csig, nonce_hi, nonce_lo, attempt, role_b, issuer, sr, valid_at, cb);
    phone_core(
        nonce_hi, nonce_lo, attempt, role_b, sr, [cc, 0], sg, salt, c_is, c_qs, c_ip, c_qp, xs, chs, leaf_s, xp,
        chp, leaf_p, ci, cq, u,
    )
}

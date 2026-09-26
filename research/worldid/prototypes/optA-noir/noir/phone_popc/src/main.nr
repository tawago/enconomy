// `phone` + the POPC v2 commit signature, without the FIR lever (headroom test for the plain port).
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
    popc_sig: [u8; 64],
) -> pub Field {
    let cc = code_commitment(c_is, c_qs, c_ip, c_qp);
    assert(cc == code_commit);
    let cb: [u8; 32] = cc.to_be_bytes();
    let sg = check_signed(t, sig, exp, hold, csig, nonce_hi, nonce_lo, attempt, role_b, issuer, sr, valid_at, cb);
    let mut c = [0u8; 71];
    c[0] = 0x50; c[1] = 0x4f; c[2] = 0x50; c[3] = 0x43; c[4] = 2;
    for i in 0..34 { c[5 + i] = t[5 + i]; }
    for i in 0..32 { c[39 + i] = t[177 + i]; }
    let mut px = [0u8; 32];
    let mut py = [0u8; 32];
    for i in 0..32 { px[i] = t[40 + i]; py[i] = t[72 + i]; }
    assert(std::ecdsa_secp256r1::verify_signature(px, py, popc_sig, sha256::digest(c)));
    phone_core(
        nonce_hi, nonce_lo, attempt, role_b, sr, [cc, 0], sg, salt, c_is, c_qs, c_ip, c_qp, xs, chs, leaf_s, xp,
        chp, leaf_p, ci, cq, u,
    )
}

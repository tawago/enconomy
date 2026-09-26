use oalib::check_signed;
fn main(nonce_hi: pub Field, nonce_lo: pub Field, attempt: pub u8, role_b: pub bool, issuer: pub [Field; 4], sr: pub u32, valid_at: pub u64,
        t: [u8; 311], sig: [u8; 64], exp: [u8; 8], hold: [u8; 32], csig: [u8; 64], code: [u8; 32]) -> pub Field {
    let s = check_signed(t, sig, exp, hold, csig, nonce_hi, nonce_lo, attempt, role_b, issuer, sr, valid_at, code);
    s.rec_root + s.a_self + s.p_self + s.a_partner + s.p_partner + s.half + s.x_own[0] + s.x_own[1] + s.x_partner[0] + s.x_partner[1]
}

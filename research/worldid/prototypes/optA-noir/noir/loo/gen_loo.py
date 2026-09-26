"""Leave-one-out variants of the phone circuit, for the gate breakdown (marginal gates of each part inside the
full circuit). usage: python3 gen_loo.py OUTDIR  -> OUTDIR/loo_<part>/{Nargo.toml,src/main.nr}"""
import pathlib, sys

PARTS = ["code", "sig", "open", "fs", "self", "partner", "half"]
MAIN = r'''use oalib::{w, check_signed, code_commitment, fs_challenges, open_leaves, partner_side, self_side, hash_n, be_f, signed32,
    Signed, K, L, NL, NT, DELTA, HM, WPRE, WPOST, TAG_HALF};
fn parse_only(t: [u8; 311], role_b: bool) -> Signed {
    let a_self = be_f(t, 269, 4);
    let half = signed32(t, 173);
    let sod = signed32(t, 233);
    Signed { rec_root: be_f(t, 177, 32), a_self, p_self: a_self - sod, a_partner: a_self + (1 - 2 * (role_b as Field)) * half,
             p_partner: be_f(t, 273, 4), half, x_own: [be_f(t, 40, 16), be_f(t, 56, 16)], x_partner: [be_f(t, 105, 16), be_f(t, 121, 16)] }
}
fn main(nonce_hi: pub Field, nonce_lo: pub Field, attempt: pub u8, role_b: pub bool, code_commit: pub Field, issuer: pub [Field; 4],
    sr: pub u32, valid_at: pub u64, t: [u8; 311], sig: [u8; 64], exp: [u8; 8], hold: [u8; 32], csig: [u8; 64], salt: Field,
    c_is: [u8; L], c_qs: [u8; L], c_ip: [u8; L], c_qp: [u8; L], xs: [u16; NT], chs: [[[Field; 4]; 4]; NL], leaf_s: Field,
    xp: [u16; NT], chp: [[[Field; 4]; 4]; NL], leaf_p: Field, ci: [Field; K], cq: [Field; K], u: [bool; K]) -> pub Field {
    let cc = @CODE@;
    assert(cc == code_commit);
    let cb: [u8; 32] = cc.to_be_bytes();
    let sg = @SIG@;
    let os = sg.p_self - DELTA as Field - HM as Field - 1024 * leaf_s;
    os.assert_max_bit_size::<10>();
    let op = sg.a_partner - HM as Field - 1024 * leaf_p;
    op.assert_max_bit_size::<10>();
    @OPEN@
    let (r, rho) = @FS@;
    @SELF@
    @PARTNER@
    (sg.a_partner - sg.p_partner + WPRE).assert_max_bit_size::<33>();
    (sg.p_partner + WPOST - sg.a_partner).assert_max_bit_size::<33>();
    @HALF@
}
'''
FULL = {
    "CODE": "code_commitment(c_is, c_qs, c_ip, c_qp)",
    "SIG": "check_signed(t, sig, exp, hold, csig, nonce_hi, nonce_lo, attempt, role_b, issuer, sr, valid_at, cb)",
    "OPEN": "open_leaves(xs, leaf_s, chs, sg.rec_root); open_leaves(xp, leaf_p, chp, sg.rec_root);",
    "FS": "fs_challenges(nonce_hi, nonce_lo, attempt, role_b, sg, [cc, 0], ci, cq)",
    "SELF": "self_side(xs, os as u32, ci, cq, u, c_is, c_qs, r, rho, sg.a_self - sg.p_self + DELTA as Field);",
    "PARTNER": "partner_side(xp, op as u32, c_ip, c_qp);",
    "HALF": "hash_n(TAG_HALF, [nonce_hi, nonce_lo, attempt as Field, role_b as Field, sr as Field, sg.half, salt, sg.x_own[0], sg.x_own[1], sg.x_partner[0], sg.x_partner[1]])",
}
# replacements that keep every input used (so input range checks stay) but drop the part's constraints
DROP = {
    "CODE": "be_f(t, 279, 31) + (c_is[0] + c_qs[0] + c_ip[0] + c_qp[0]) as Field",
    "SIG": "parse_only(t, role_b)",
    "OPEN": "assert(xs[0] + xp[0] != 0); let _ = (chs, chp);",
    "FS": "(w(nonce_hi + ci[0]), w(nonce_lo + cq[0]))",  # witnesses, as the real r and rho are
    "SELF": "let _ = (r, rho, u);",
    "PARTNER": "let _ = 0;",
    "HALF": "salt + sg.half",
}
out = pathlib.Path(sys.argv[1])
for part in ["full"] + PARTS:
    src = MAIN
    for k in FULL:
        src = src.replace("@%s@" % k, DROP[k] if k.lower() == part else FULL[k])
    d = out / f"loo_{part}"
    (d / "src").mkdir(parents=True, exist_ok=True)
    (d / "Nargo.toml").write_text(f'[package]\nname = "loo_{part}"\ntype = "bin"\nauthors = [""]\n[dependencies]\noalib = {{ path = "../oalib" }}\n')
    (d / "src/main.nr").write_text(src)
print("ok")

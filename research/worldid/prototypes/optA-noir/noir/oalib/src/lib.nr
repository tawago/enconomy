// Option A (POPT v2, one phone) ported from circom (optionA-v2/circuits/main/oa2t_s48.circom) to Noir.
// BN254 UltraHonk. Same statement; hash changes (noted in research/worldid/notes/onchain-zk/optA-noir.md):
//   Poseidon7 over the P-256 field  ->  Poseidon2 over BN254 (bb blackbox, t = 4)
//   ECDSA P-256 gadget              ->  std::ecdsa_secp256r1 blackbox
// Big arrays are never written in loops (the Noir SSA copies them per write); everything is streamed.
use std::ecdsa_secp256r1::verify_signature;
use std::hash::poseidon2_permutation;

// Materialize `e` as one fresh witness with one constraint. std::as_witness and long `+=` chains make the Noir
// compiler quadratic in memory (measured: 2 GB at 9,600 steps); a hint + assert is linear and costs 1 gate.
unconstrained fn id(x: Field) -> Field {
    x
}
pub fn w(e: Field) -> Field {
    // Safety: the value is fully constrained by the assert.
    let v = unsafe { id(e) };
    assert(v == e);
    v
}

// ---- 48 kHz constants (optionA-v2/oa_rate.py, gen_popt2.py)
pub global SR: u32 = 48000;
pub global L: u32 = 12000; // template length
pub global K: u32 = 193; // self lags, 2 DELTA + 1
pub global DELTA: u32 = 96;
pub global HM: u32 = 31; // FIR half length
pub global NS: u32 = 12254; // self window samples, K + L - 1 + 2 HM
pub global NP: u32 = 12062; // partner window samples, L + 2 HM
pub global NL: u32 = 13; // opened leaves per side
pub global NT: u32 = 13312; // NL * 1024
pub global WPRE: Field = 7200;
pub global WPOST: Field = 12000;
pub global BAR: Field = 4474747; // B = round(g^2 / 0.09^2)
pub global NZ: u32 = 31; // non-zero FIR taps
pub global NZT: [u32; 31] =
    [9, 11, 12, 14, 15, 17, 18, 20, 21, 23, 24, 26, 27, 29, 30, 31, 32, 33, 35, 36, 38, 39, 41, 42, 44, 45, 47, 48, 50, 51, 53];
pub global NZH: [Field; 31] = [
    1, 1, 2, 2, 2, 4, -1, 2, -7, -5, -13, -19, -13, -45, 27, 127, 27, -45, -13, -19, -13, -5, -7, 2, -1, 4, 2, 2, 2, 1, 1,
];

// domain tags (capacity cell of the sponge)
pub global TAG_LEAF: Field = 262145; // 1 + (1024 << 8), as circom
pub global TAG_NODE: Field = 2;
pub global TAG_HALF: Field = 8;
pub global TAG_FS: Field = 101897; // 9 + (398 << 8), as circom
pub global TAG_CODE: Field = 10;

// ---- Poseidon2 sponge, rate 3, capacity 1 (= tag), fixed length per tag; streaming absorb.
pub struct Sp {
    s: [Field; 4],
    pos: u32,
}

impl Sp {
    pub fn new(tag: Field) -> Sp {
        Sp { s: [0, 0, 0, tag], pos: 0 }
    }
    pub fn absorb(&mut self, x: Field) {
        self.s[self.pos] += x;
        self.pos += 1;
        if self.pos == 3 {
            self.s = poseidon2_permutation(self.s);
            self.pos = 0;
        }
    }
    pub fn finish(&mut self) -> (Field, Field) {
        if self.pos != 0 {
            self.s = poseidon2_permutation(self.s);
            self.pos = 0;
        }
        (self.s[0], self.s[1])
    }
}

pub fn hash_n<let N: u32>(tag: Field, x: [Field; N]) -> Field {
    let mut sp = Sp::new(tag);
    for i in 0..N {
        sp.absorb(x[i]);
    }
    sp.finish().0
}

// ---- recording: 1,024 int16 samples per leaf, stored as u = x + 32768 (u16, range-checked on input)
// leaf = sponge(TAG_LEAF; 69 elements, 15 x 16 bits each, little-end within an element)
pub fn leaf_hash<let T: u32>(x: [u16; T], base: u32) -> Field {
    let mut sp = Sp::new(TAG_LEAF);
    for k in 0..69 {
        let mut acc: Field = 0;
        let mut mul: Field = 1;
        for j in 0..15 {
            let idx = k * 15 + j;
            if idx < 1024 {
                acc += (x[base + idx] as Field) * mul;
                mul *= 65536;
            }
        }
        sp.absorb(acc);
    }
    sp.finish().0
}

// 4-ary node
pub fn node_hash(c: [Field; 4]) -> Field {
    hash_n(TAG_NODE, c)
}

// path of one leaf in the depth-4 4-ary tree; idx < 256 (8-bit check here, as circom Num2Bits(2 D))
pub fn merkle_root(leaf: Field, idx: Field, ch: [[Field; 4]; 4]) -> Field {
    let bits: [bool; 8] = idx.to_le_bits();
    let mut cur = leaf;
    for l in 0..4 {
        let b0 = bits[2 * l] as Field;
        let b1 = bits[2 * l + 1] as Field;
        let c = ch[l];
        let b01 = b0 * b1;
        let sel = c[0] + b0 * (c[1] - c[0]) + b1 * (c[2] - c[0]) + b01 * (c[3] - c[2] - c[1] + c[0]);
        assert(cur == sel);
        cur = node_hash(c);
    }
    cur
}

// NL contiguous leaves starting at leaf index `first`, all under `root`
pub fn open_leaves(x: [u16; NT], first: Field, ch: [[[Field; 4]; 4]; NL], root: Field) {
    for i in 0..NL {
        let h = leaf_hash(x, i * 1024);
        let r = merkle_root(h, first + i as Field, ch[i]);
        assert(r == root);
    }
}

// ---- templates: u8 (offset +128, range-checked on input, private) or Field (public, faithful variant)
pub trait ToF {
    fn tf(self) -> Field;
}
impl ToF for u8 {
    fn tf(self) -> Field {
        self as Field - 128
    }
}
impl ToF for Field {
    fn tf(self) -> Field {
        self
    }
}

// code commitment over the four private u8 templates: 31 bytes per element (1,552 elements, 518 perms)
fn absorb_bytes(sp: &mut Sp, a: [u8; L]) {
    for k in 0..(L + 30) / 31 {
        let mut acc: Field = 0;
        for j in 0..31 {
            let idx = 31 * k + j;
            if idx < L {
                acc = acc * 256 + a[idx] as Field;
            }
        }
        sp.absorb(acc);
    }
}

pub fn code_commitment(a: [u8; L], b: [u8; L], c: [u8; L], d: [u8; L]) -> Field {
    let mut sp = Sp::new(TAG_CODE);
    absorb_bytes(&mut sp, a);
    absorb_bytes(&mut sp, b);
    absorb_bytes(&mut sp, c);
    absorb_bytes(&mut sp, d);
    sp.finish().0
}

// ---- transcript helpers
pub fn be_f<let T: u32>(t: [u8; T], off: u32, n: u32) -> Field {
    let mut v: Field = 0;
    for i in 0..n {
        v = v * 256 + t[off + i] as Field;
    }
    v
}

pub fn signed32<let T: u32>(t: [u8; T], off: u32) -> Field {
    let msb = (t[off] >> 7) as Field;
    be_f(t, off, 4) - msb * 4294967296
}

pub fn unpack_issuer(k: [Field; 4]) -> ([u8; 32], [u8; 32]) {
    let mut x = [0u8; 32];
    let mut y = [0u8; 32];
    let a: [u8; 16] = k[0].to_be_bytes();
    let b: [u8; 16] = k[1].to_be_bytes();
    let c: [u8; 16] = k[2].to_be_bytes();
    let d: [u8; 16] = k[3].to_be_bytes();
    for i in 0..16 {
        x[i] = a[i];
        x[16 + i] = b[i];
        y[i] = c[i];
        y[16 + i] = d[i];
    }
    (x, y)
}

pub struct Signed {
    pub rec_root: Field,
    pub a_self: Field,
    pub p_self: Field,
    pub a_partner: Field,
    pub p_partner: Field,
    pub half: Field,
    pub x_own: [Field; 2],
    pub x_partner: [Field; 2],
}

// (1) POPT v2 transcript (311 B) signed by the hidden device key, SBcred3 (111 B) signed by the public issuer,
// unexpired at valid_at; signed sr == SR, delta == DELTA, own X != partner X; code bytes == `code`.
pub fn check_signed(
    t: [u8; 311],
    sig: [u8; 64],
    exp: [u8; 8],
    hold: [u8; 32],
    csig: [u8; 64],
    nonce_hi: Field,
    nonce_lo: Field,
    attempt: u8,
    role_b: bool,
    issuer: [Field; 4],
    sr: u32,
    valid_at: u64,
    code: [u8; 32],
) -> Signed {
    assert(t[0] == 0x50);
    assert(t[1] == 0x4f);
    assert(t[2] == 0x50);
    assert(t[3] == 0x54);
    assert(t[4] == 2);
    assert(t[5] == 0x41 + (role_b as u8));
    assert(t[6] == attempt);
    assert(be_f(t, 7, 16) == nonce_hi);
    assert(be_f(t, 23, 16) == nonce_lo);
    assert(t[39] == 4);
    assert(t[104] == 4);
    assert(be_f(t, 169, 4) == sr as Field);
    assert(sr == SR);
    assert(be_f(t, 277, 2) == DELTA as Field);
    for i in 0..32 {
        assert(t[279 + i] == code[i]);
    }
    // device signature over sha256(transcript)
    let digest = sha256::digest(t);
    let mut px = [0u8; 32];
    let mut py = [0u8; 32];
    for i in 0..32 {
        px[i] = t[40 + i];
        py[i] = t[72 + i];
    }
    assert(verify_signature(px, py, sig, digest));
    // SBcred3 = "SBcred3" | X||Y | expiry u64 | holder_commit(32), sha256 + ECDSA by the issuer
    let mut c = [0u8; 111];
    let tag = [0x53, 0x42, 0x63, 0x72, 0x65, 0x64, 0x33];
    for i in 0..7 {
        c[i] = tag[i];
    }
    for i in 0..64 {
        c[7 + i] = t[40 + i];
    }
    for i in 0..8 {
        c[71 + i] = exp[i];
    }
    for i in 0..32 {
        c[79 + i] = hold[i];
    }
    let cd = sha256::digest(c);
    let (ix, iy) = unpack_issuer(issuer);
    assert(verify_signature(ix, iy, csig, cd));
    let expiry = be_f(exp, 0, 8) as u64;
    assert(valid_at <= expiry);
    // keys as 2 x 128-bit limbs, own X != partner X
    let x_own = [be_f(t, 40, 16), be_f(t, 56, 16)];
    let x_partner = [be_f(t, 105, 16), be_f(t, 121, 16)];
    assert((x_own[0] != x_partner[0]) | (x_own[1] != x_partner[1]));
    // rec_root: canonical BN254 element
    let rr = be_f(t, 177, 32);
    let back: [u8; 32] = rr.to_be_bytes();
    for i in 0..32 {
        assert(back[i] == t[177 + i]);
    }
    let a_self = be_f(t, 269, 4);
    let p_partner = be_f(t, 273, 4);
    let half = signed32(t, 173);
    let sod = signed32(t, 233);
    let sg = 1 - 2 * (role_b as Field);
    Signed {
        rec_root: rr,
        a_self,
        p_self: a_self - sod,
        a_partner: a_self + sg * half,
        p_partner,
        half,
        x_own,
        x_partner,
    }
}

// ---- (3) Fiat-Shamir: r, rho over everything the identity depends on, before the challenge
pub fn fs_challenges(
    nonce_hi: Field,
    nonce_lo: Field,
    attempt: u8,
    role_b: bool,
    s: Signed,
    code: [Field; 2],
    ci: [Field; K],
    cq: [Field; K],
) -> (Field, Field) {
    let mut sp = Sp::new(TAG_FS);
    sp.absorb(nonce_hi);
    sp.absorb(nonce_lo);
    sp.absorb(attempt as Field);
    sp.absorb(role_b as Field);
    sp.absorb(s.rec_root);
    sp.absorb(s.p_self);
    sp.absorb(s.p_partner);
    sp.absorb(DELTA as Field);
    sp.absorb(s.a_self);
    sp.absorb(s.a_partner);
    sp.absorb(code[0]);
    sp.absorb(code[1]);
    for j in 0..K {
        sp.absorb(ci[j]);
    }
    for j in 0..K {
        sp.absorb(cq[j]);
    }
    sp.finish()
}

// ---- (3)+(4) self window: x[p_self - DELTA - HM + i], i < NS, read at offset o from the 13 opened leaves.
// Checks the claimed curve I, Q (Freivalds, streaming form: sum_j r^j (I_j + rho Q_j) =
// sum_n (cI_n + rho cQ_n) r^-n (S_{n+K} - S_n), S_m = sum_{m' < m} r^m' x[lo + m']), the FIR energy E_j and the rule:
// score(j) < bar before the arrival lag, score >= bar at it (u = 1 before the arrival).
pub fn self_side<T>(
    xs: [u16; NT],
    o: u32,
    ci: [Field; K],
    cq: [Field; K],
    u: [bool; K],
    c_i: [T; L],
    c_q: [T; L],
    r: Field,
    rho: Field,
    usum_target: Field,
)
where
    T: ToF,
{
    // template energy cn2
    let mut cna: Field = 0;
    for n in 0..L {
        let v = c_i[n].tf();
        let a = w(cna + v * v);
        cna = a;
    }
    // arrival selector: u monotone (1 ... 1 0 ... 0), u[K-1] = 0, sum u = a_self - p_self + DELTA
    assert(!u[K - 1]);
    let mut usum: Field = 0;
    for j in 0..K {
        if j > 0 {
            assert(!u[j] | u[j - 1]);
        }
        usum += u[j] as Field;
    }
    assert(usum == usum_target);

    let rinv = 1 / r;
    let mut ring: [Field; 64] = [0; 64];
    let mut sring: [Field; K] = [0; K];
    let mut eyf: [Field; K] = [0; K];
    let mut ey: Field = 0;
    let mut s: Field = 0;
    let mut pr: Field = 1;
    let mut pinv: Field = 1;
    let mut acc: Field = 0;
    let mut lhs: Field = 0;
    for i in 0..NS {
        let wi = xs[o + i] as Field - 32768;
        ring[i % 64] = wi;
        if i >= 62 {
            let m = i - 62;
            // FIR output y_m = sum_t h_t x[lo - HM + m + t]
            let mut y: Field = 0;
            for t in 0..NZ {
                y += NZH[t] * ring[(m + NZT[t]) % 64];
            }
            let y = w(y);
            if m < K {
                eyf[m] = ey;
            }
            let e2 = w(ey + y * y);
            ey = e2; // EY[m + 1]
            if m + 1 >= L {
                let j = m + 1 - L;
                let big_c = (ey - eyf[j]) * cna;
                let env2 = ci[j] * ci[j] + cq[j] * cq[j];
                let d = big_c - BAR * env2;
                let uj = u[j] as Field;
                let e = (if j == 0 { 1 } else { u[j - 1] as Field }) - uj;
                let v = uj * (d - 1) - e * d;
                v.assert_max_bit_size::<96>();
            }
            // prefix S and Freivalds
            let wc = ring[(m + HM) % 64];
            if m < K {
                let tq = w(ci[m] + rho * cq[m]);
                let l2 = w(lhs + pr * tq);
                lhs = l2;
            }
            let s2 = w(s + pr * wc); // S_{m+1}
            if m + 1 >= K {
                let n = m + 1 - K;
                if n < L {
                    let sn = sring[n % K];
                    let cp = w(c_i[n].tf() + rho * c_q[n].tf());
                    let g = w(cp * pinv);
                    let a2 = w(acc + g * (s2 - sn));
                    acc = a2;
                    let p2 = w(pinv * rinv);
                    pinv = p2;
                }
            }
            sring[(m + 1) % K] = s2;
            s = s2;
            let p3 = w(pr * r);
            pr = p3;
        }
    }
    assert(lhs == acc);
}

// ---- (5) partner: the one lag a_partner scores >= bar; window x[a_partner - HM + i], i < NP.
pub fn partner_side<T>(xp: [u16; NT], o: u32, c_i: [T; L], c_q: [T; L])
where
    T: ToF,
{
    let mut cnp: Field = 0;
    for n in 0..L {
        let v = c_i[n].tf();
        let a = w(cnp + v * v);
        cnp = a;
    }
    let mut ring: [Field; 64] = [0; 64];
    let mut ep: Field = 0;
    let mut ii: Field = 0;
    let mut qq: Field = 0;
    for i in 0..NP {
        let wi = xp[o + i] as Field - 32768;
        ring[i % 64] = wi;
        if i >= 62 {
            let m = i - 62;
            let mut y: Field = 0;
            for t in 0..NZ {
                y += NZH[t] * ring[(m + NZT[t]) % 64];
            }
            let y = w(y);
            let e2 = w(ep + y * y);
            ep = e2;
            let wc = ring[(m + HM) % 64];
            let i2 = w(ii + c_i[m].tf() * wc);
            ii = i2;
            let q2 = w(qq + c_q[m].tf() * wc);
            qq = q2;
        }
    }
    let penv2 = ii * ii + qq * qq;
    let v = BAR * penv2 - ep * cnp;
    v.assert_max_bit_size::<96>();
}

// ---- whole per-phone statement after the signature part; returns halfCommit.
pub fn phone_core<T>(
    nonce_hi: Field,
    nonce_lo: Field,
    attempt: u8,
    role_b: bool,
    sr: u32,
    code: [Field; 2],
    sg: Signed,
    salt: Field,
    c_is: [T; L],
    c_qs: [T; L],
    c_ip: [T; L],
    c_qp: [T; L],
    xs: [u16; NT],
    chs: [[[Field; 4]; 4]; NL],
    leaf_s: Field,
    xp: [u16; NT],
    chp: [[[Field; 4]; 4]; NL],
    leaf_p: Field,
    ci: [Field; K],
    cq: [Field; K],
    u: [bool; K],
) -> Field
where
    T: ToF,
{
    // (2) open the recording under the signed rec_root; window offsets inside the first opened leaf
    let os = sg.p_self - DELTA as Field - HM as Field - 1024 * leaf_s;
    os.assert_max_bit_size::<10>();
    open_leaves(xs, leaf_s, chs, sg.rec_root);
    let op = sg.a_partner - HM as Field - 1024 * leaf_p;
    op.assert_max_bit_size::<10>();
    open_leaves(xp, leaf_p, chp, sg.rec_root);
    // (3) + (4)
    let (r, rho) = fs_challenges(nonce_hi, nonce_lo, attempt, role_b, sg, code, ci, cq);
    self_side(
        xs,
        os as u32,
        ci,
        cq,
        u,
        c_is,
        c_qs,
        r,
        rho,
        sg.a_self - sg.p_self + DELTA as Field,
    );
    // (5)
    partner_side(xp, op as u32, c_ip, c_qp);
    (sg.a_partner - sg.p_partner + WPRE).assert_max_bit_size::<33>();
    (sg.p_partner + WPOST - sg.a_partner).assert_max_bit_size::<33>();
    // (6) hiding half commitment (sr and both keys inside)
    hash_n(
        TAG_HALF,
        [
            nonce_hi, nonce_lo, attempt as Field, role_b as Field, sr as Field, sg.half, salt, sg.x_own[0],
            sg.x_own[1], sg.x_partner[0], sg.x_partner[1],
        ],
    )
}

// =====================================================================================================
// Lever: FIR claim-and-check ("opt" variant). Same statement; the prover supplies the FIR outputs
// y_m (offset by 2^25, range-checked to 26 bits) and they are packed 9 per element into the Fiat-Shamir
// sponge before r. With T_i = sum_{i' < i} r^i' w_i' over the window samples w:
//   FIR:       sum_m r^(m+62) y_m == sum_t h_t r^(62-t) (T_{t+NF} - T_t)        (NF = number of outputs)
//   Freivalds: sum_j r^j (I_j + rho Q_j) == sum_n (cI_n + rho cQ_n) r^(-n-31) (T_{n+K+31} - T_{n+31})
// Both are fixed polynomials in r once everything is absorbed; soundness error <= (NS + L) / p each.
pub global N: u32 = 12192; // self FIR outputs, K + L - 1
pub global YOFF: Field = 33554432; // 2^25 > 32768 * sum |h| = 32768 * 415 = 13,598,720

fn absorb_packed_y<let M: u32>(sp: &mut Sp, y: [Field; M]) {
    for k in 0..(M + 8) / 9 {
        let mut acc: Field = 0;
        let mut mul: Field = 1;
        for j in 0..9 {
            let idx = 9 * k + j;
            if idx < M {
                y[idx].assert_max_bit_size::<26>();
                acc += y[idx] * mul;
                mul *= 67108864; // 2^26
            }
        }
        sp.absorb(acc);
    }
}

pub fn fs_challenges_opt(
    nonce_hi: Field,
    nonce_lo: Field,
    attempt: u8,
    role_b: bool,
    s: Signed,
    code: [Field; 2],
    ci: [Field; K],
    cq: [Field; K],
    ys: [Field; N],
    yp: [Field; L],
) -> (Field, Field) {
    let mut sp = Sp::new(TAG_FS + 1);
    sp.absorb(nonce_hi);
    sp.absorb(nonce_lo);
    sp.absorb(attempt as Field);
    sp.absorb(role_b as Field);
    sp.absorb(s.rec_root);
    sp.absorb(s.p_self);
    sp.absorb(s.p_partner);
    sp.absorb(DELTA as Field);
    sp.absorb(s.a_self);
    sp.absorb(s.a_partner);
    sp.absorb(code[0]);
    sp.absorb(code[1]);
    for j in 0..K {
        sp.absorb(ci[j]);
    }
    for j in 0..K {
        sp.absorb(cq[j]);
    }
    absorb_packed_y(&mut sp, ys);
    absorb_packed_y(&mut sp, yp);
    sp.finish()
}

// r^0 .. r^62
pub fn first_powers(r: Field) -> [Field; 63] {
    let mut p: [Field; 63] = [1; 63];
    for i in 1..63 {
        p[i] = w(p[i - 1] * r);
    }
    p
}

pub fn self_side_opt<T>(
    xs: [u16; NT],
    o: u32,
    ci: [Field; K],
    cq: [Field; K],
    u: [bool; K],
    c_i: [T; L],
    c_q: [T; L],
    ys: [Field; N],
    r: Field,
    rho: Field,
    pf: [Field; 63],
    usum_target: Field,
)
where
    T: ToF,
{
    let mut cna: Field = 0;
    for n in 0..L {
        let v = c_i[n].tf();
        cna = w(cna + v * v);
    }
    assert(!u[K - 1]);
    let mut usum: Field = 0;
    for j in 0..K {
        if j > 0 {
            assert(!u[j] | u[j - 1]);
        }
        usum += u[j] as Field;
    }
    assert(usum == usum_target);

    let rinv = 1 / r;
    let rinv31 = 1 / pf[31]; // r^-31
    let mut tfirst: [Field; 63] = [0; 63]; // T_0 .. T_62
    let mut tlast: [Field; 45] = [0; 45]; // T_{N+9} .. T_{N+53}
    let mut tring: [Field; K] = [0; K];
    let mut eyf: [Field; K] = [0; K];
    let mut tt: Field = 0; // T_i
    let mut pr: Field = 1; // r^i
    let mut pinv: Field = rinv31; // r^(-n-31)
    let mut acc: Field = 0;
    let mut lhs: Field = 0;
    let mut ey: Field = 0;
    let mut fl: Field = 0; // FIR check, left
    for i in 0..NS {
        let wi = xs[o + i] as Field - 32768;
        let t2 = w(tt + pr * wi); // T_{i+1}
        if i + 1 <= 62 {
            tfirst[i + 1] = t2;
        }
        if (i + 1 >= N + 9) & (i + 1 < N + 54) {
            tlast[i + 1 - N - 9] = t2;
        }
        if i >= 62 {
            let m = i - 62;
            let y = ys[m] - YOFF;
            fl = w(fl + pr * y);
            if m < K {
                eyf[m] = ey;
            }
            ey = w(ey + y * y); // EY[m + 1]
            if m + 1 >= L {
                let j = m + 1 - L;
                let big_c = (ey - eyf[j]) * cna;
                let env2 = ci[j] * ci[j] + cq[j] * cq[j];
                let d = big_c - BAR * env2;
                let uj = u[j] as Field;
                let e = (if j == 0 { 1 } else { u[j - 1] as Field }) - uj;
                let v = uj * (d - 1) - e * d;
                v.assert_max_bit_size::<96>();
            }
        }
        if i < K {
            let tq = w(ci[i] + rho * cq[i]);
            lhs = w(lhs + pr * tq);
        }
        // Freivalds: n = i + 1 - K - 31, uses T_{n+K+31} = t2 and T_{n+31} = tring[(i + 1) % K]
        if i + 1 >= K + 31 {
            let n = i + 1 - K - 31;
            if n < L {
                let sn = tring[(i + 1) % K];
                let cp = w(c_i[n].tf() + rho * c_q[n].tf());
                let g = w(cp * pinv);
                acc = w(acc + g * (t2 - sn));
                pinv = w(pinv * rinv);
            }
        }
        tring[(i + 1) % K] = t2;
        tt = t2;
        pr = w(pr * r);
    }
    assert(lhs == acc);
    // FIR right side: sum_t h_t r^(62-t) (T_{t+N} - T_t)
    let mut fr: Field = 0;
    for k in 0..NZ {
        fr = w(fr + NZH[k] * pf[62 - NZT[k]] * (tlast[NZT[k] - 9] - tfirst[NZT[k]]));
    }
    assert(fl == fr);
}

pub fn partner_side_opt<T>(xp: [u16; NT], o: u32, c_i: [T; L], c_q: [T; L], yp: [Field; L], r: Field, pf: [Field; 63])
where
    T: ToF,
{
    let mut cnp: Field = 0;
    for n in 0..L {
        let v = c_i[n].tf();
        cnp = w(cnp + v * v);
    }
    let mut ring: [Field; 64] = [0; 64];
    let mut tfirst: [Field; 63] = [0; 63];
    let mut tlast: [Field; 45] = [0; 45];
    let mut tt: Field = 0;
    let mut pr: Field = 1;
    let mut fl: Field = 0;
    let mut ep: Field = 0;
    let mut ii: Field = 0;
    let mut qq: Field = 0;
    for i in 0..NP {
        let wi = xp[o + i] as Field - 32768;
        ring[i % 64] = wi;
        let t2 = w(tt + pr * wi);
        if i + 1 <= 62 {
            tfirst[i + 1] = t2;
        }
        if (i + 1 >= L + 9) & (i + 1 < L + 54) {
            tlast[i + 1 - L - 9] = t2;
        }
        if i >= 62 {
            let m = i - 62;
            let y = yp[m] - YOFF;
            fl = w(fl + pr * y);
            ep = w(ep + y * y);
            let wc = ring[(m + HM) % 64];
            ii = w(ii + c_i[m].tf() * wc);
            qq = w(qq + c_q[m].tf() * wc);
        }
        tt = t2;
        pr = w(pr * r);
    }
    let mut fr: Field = 0;
    for k in 0..NZ {
        fr = w(fr + NZH[k] * pf[62 - NZT[k]] * (tlast[NZT[k] - 9] - tfirst[NZT[k]]));
    }
    assert(fl == fr);
    let penv2 = ii * ii + qq * qq;
    let v = BAR * penv2 - ep * cnp;
    v.assert_max_bit_size::<96>();
}

pub fn phone_core_opt<T>(
    nonce_hi: Field,
    nonce_lo: Field,
    attempt: u8,
    role_b: bool,
    sr: u32,
    code: [Field; 2],
    sg: Signed,
    salt: Field,
    c_is: [T; L],
    c_qs: [T; L],
    c_ip: [T; L],
    c_qp: [T; L],
    xs: [u16; NT],
    chs: [[[Field; 4]; 4]; NL],
    leaf_s: Field,
    xp: [u16; NT],
    chp: [[[Field; 4]; 4]; NL],
    leaf_p: Field,
    ci: [Field; K],
    cq: [Field; K],
    u: [bool; K],
    ys: [Field; N],
    yp: [Field; L],
) -> Field
where
    T: ToF,
{
    let os = sg.p_self - DELTA as Field - HM as Field - 1024 * leaf_s;
    os.assert_max_bit_size::<10>();
    open_leaves(xs, leaf_s, chs, sg.rec_root);
    let op = sg.a_partner - HM as Field - 1024 * leaf_p;
    op.assert_max_bit_size::<10>();
    open_leaves(xp, leaf_p, chp, sg.rec_root);
    let (r, rho) = fs_challenges_opt(nonce_hi, nonce_lo, attempt, role_b, sg, code, ci, cq, ys, yp);
    let pf = first_powers(r);
    self_side_opt(
        xs,
        os as u32,
        ci,
        cq,
        u,
        c_is,
        c_qs,
        ys,
        r,
        rho,
        pf,
        sg.a_self - sg.p_self + DELTA as Field,
    );
    partner_side_opt(xp, op as u32, c_ip, c_qp, yp, r, pf);
    (sg.a_partner - sg.p_partner + WPRE).assert_max_bit_size::<33>();
    (sg.p_partner + WPOST - sg.a_partner).assert_max_bit_size::<33>();
    hash_n(
        TAG_HALF,
        [
            nonce_hi, nonce_lo, attempt as Field, role_b as Field, sr as Field, sg.half, salt, sg.x_own[0],
            sg.x_own[1], sg.x_partner[0], sg.x_partner[1],
        ],
    )
}

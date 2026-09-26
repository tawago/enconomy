// PoP option 3: P-256 checks inside a BN254 UltraHonk proof.
// POPT v2 (311 B) and SBcred3-bn (111 B, holder_commit = Poseidon2_bn254(secret)).
use poseidon::poseidon2::Poseidon2;
use std::ecdsa_secp256r1::verify_signature;

pub global T_LEN: u32 = 311;
pub global C_LEN: u32 = 111;

pub fn be_u32<let N: u32>(b: [u8; N], off: u32) -> u32 {
    ((b[off] as u32) << 24) | ((b[off + 1] as u32) << 16) | ((b[off + 2] as u32) << 8) | (b[off + 3] as u32)
}
pub fn be_u64<let N: u32>(b: [u8; N], off: u32) -> u64 {
    let mut v: u64 = 0;
    for i in 0..8 { v = (v << 8) | (b[off + i] as u64); }
    v
}
// 32 bytes -> 2 x 128-bit fields
pub fn pack32<let N: u32>(b: [u8; N], off: u32) -> [Field; 2] {
    let mut hi: Field = 0;
    let mut lo: Field = 0;
    for i in 0..16 { hi = hi * 256 + b[off + i] as Field; lo = lo * 256 + b[off + 16 + i] as Field; }
    [hi, lo]
}
pub fn slice32<let N: u32>(b: [u8; N], off: u32) -> [u8; 32] {
    let mut o = [0u8; 32];
    for i in 0..32 { o[i] = b[off + i]; }
    o
}
pub fn to_signed(u: u32) -> i64 {
    if u >= 0x80000000 { (u as i64) - 0x100000000 } else { u as i64 }
}

pub struct Half {
    pub role: u8,
    pub attempt: u8,
    pub nonce: [Field; 2],
    pub sr: u32,
    pub half: u32,
    pub pair_tag: Field,
    pub self_pk: [Field; 4],
    pub partner_pk: [Field; 4],
}

// Everything one phone's half needs: transcript sig by hidden device key, issuer cred over that key,
// cred not expired, holder secret opens cred.holder_commit.
pub fn check_half(
    transcript: [u8; 311],
    sig_t: [u8; 64],
    cred: [u8; 111],
    sig_c: [u8; 64],
    holder_secret: Field,
    issuer_x: [u8; 32],
    issuer_y: [u8; 32],
    now: u64,
) -> Half {
    // transcript header
    assert(transcript[0] == 0x50); assert(transcript[1] == 0x4f); assert(transcript[2] == 0x50); assert(transcript[3] == 0x54);
    assert(transcript[4] == 2);
    let role = transcript[5];
    assert((role == 0x41) | (role == 0x42));
    assert(transcript[39] == 4);
    assert(transcript[104] == 4);
    // cred header "SBcred3"
    let tag = [0x53, 0x42, 0x63, 0x72, 0x65, 0x64, 0x33];
    for i in 0..7 { assert(cred[i] == tag[i]); }
    // cred device key == transcript pk_self
    for i in 0..64 { assert(cred[7 + i] == transcript[40 + i]); }
    let expiry = be_u64(cred, 71);
    assert(now < expiry);
    // holder commit
    let hc = Poseidon2::hash([holder_secret], 1);
    let hcb: [u8; 32] = hc.to_be_bytes();
    for i in 0..32 { assert(cred[79 + i] == hcb[i]); }
    // signatures
    let ht = sha256::digest(transcript);
    let dx = slice32(transcript, 40);
    let dy = slice32(transcript, 72);
    assert(verify_signature(dx, dy, sig_t, ht));
    let hcred = sha256::digest(cred);
    assert(verify_signature(issuer_x, issuer_y, sig_c, hcred));
    // self timestamp tolerance: |self_os_delta| <= 50 ms
    let sr = be_u32(transcript, 169);
    let sod = to_signed(be_u32(transcript, 233));
    let tol = ((sr as i64) * 50) / 1000;
    assert((sod <= tol) & (sod >= -tol));
    let sx = pack32(transcript, 40); let sy = pack32(transcript, 72);
    let px = pack32(transcript, 105); let py = pack32(transcript, 137);
    let self_pk = [sx[0], sx[1], sy[0], sy[1]];
    let partner_pk = [px[0], px[1], py[0], py[1]];
    // distinct devices
    assert((self_pk[0] != partner_pk[0]) | (self_pk[1] != partner_pk[1]) | (self_pk[2] != partner_pk[2]) | (self_pk[3] != partner_pk[3]));
    let nonce = pack32(transcript, 7);
    // pair tag orders keys by role: H(nonce, pk_A, pk_B)
    let (a, b) = if role == 0x41 { (self_pk, partner_pk) } else { (partner_pk, self_pk) };
    let pair_tag = Poseidon2::hash([nonce[0], nonce[1], a[0], a[1], a[2], a[3], b[0], b[1], b[2], b[3], transcript[6] as Field], 11);
    Half { role, attempt: transcript[6], nonce, sr, half: be_u32(transcript, 173), pair_tag, self_pk, partner_pk }
}

// issuer key as 4 x 128-bit public fields -> bytes
pub fn unpack_issuer(k: [Field; 4]) -> ([u8; 32], [u8; 32]) {
    let mut x = [0u8; 32]; let mut y = [0u8; 32];
    let a: [u8; 16] = k[0].to_be_bytes(); let b: [u8; 16] = k[1].to_be_bytes();
    let c: [u8; 16] = k[2].to_be_bytes(); let d: [u8; 16] = k[3].to_be_bytes();
    for i in 0..16 { x[i] = a[i]; x[16 + i] = b[i]; y[i] = c[i]; y[16 + i] = d[i]; }
    (x, y)
}

pub fn nullifier(holder_secret: Field, scope: Field) -> Field {
    Poseidon2::hash([holder_secret, scope], 2)
}

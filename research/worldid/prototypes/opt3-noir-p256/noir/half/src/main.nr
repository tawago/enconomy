// Per-phone proof. Public: issuer key, now, scope, context, nonce; outputs role, sr, half, pair_tag, nullifier.
use poplib::{unpack_issuer, check_half, nullifier};
fn main(
    transcript: [u8; 311], sig_t: [u8; 64], cred: [u8; 111], sig_c: [u8; 64], holder_secret: Field,
    issuer: pub [Field; 4], now: pub u64, scope: pub Field, context: pub Field,
) -> pub (u8, u8, [Field; 2], u32, u32, Field, Field) {
    let (issuer_x, issuer_y) = unpack_issuer(issuer);
    let h = check_half(transcript, sig_t, cred, sig_c, holder_secret, issuer_x, issuer_y, now);
    let _ = context; // bound as a public input only
    (h.role, h.attempt, h.nonce, h.sr, h.half, h.pair_tag, nullifier(holder_secret, scope))
}

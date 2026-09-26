use oalib::{self_side, K, L, NT};
fn main(xs: [u16; NT], o: u16, ci: [Field; K], cq: [Field; K], u: [bool; K], c_is: [u8; L], c_qs: [u8; L], r: Field, rho: Field, tgt: Field) {
    assert(o < 1024);
    self_side(xs, o as u32, ci, cq, u, c_is, c_qs, r, rho, tgt);
}

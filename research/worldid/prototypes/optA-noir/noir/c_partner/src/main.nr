use oalib::{partner_side, L, NT};
fn main(xp: [u16; NT], o: u16, c_ip: [u8; L], c_qp: [u8; L]) {
    assert(o < 1024);
    partner_side(xp, o as u32, c_ip, c_qp);
}

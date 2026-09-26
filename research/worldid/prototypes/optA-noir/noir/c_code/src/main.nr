use oalib::{code_commitment, L};
fn main(c_is: [u8; L], c_qs: [u8; L], c_ip: [u8; L], c_qp: [u8; L], code_commit: pub Field) {
    let cc = code_commitment(c_is, c_qs, c_ip, c_qp);
    assert(cc == code_commit);
    let _cb: [u8; 32] = cc.to_be_bytes();
}

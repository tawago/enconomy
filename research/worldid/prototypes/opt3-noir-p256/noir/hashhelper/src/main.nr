use poseidon::poseidon2::Poseidon2;
fn main(s: Field) -> pub [u8; 32] { Poseidon2::hash([s], 1).to_be_bytes() }

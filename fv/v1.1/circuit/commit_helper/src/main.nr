// Witness help only, never proven: the two half commitments for a throwaway pair input.
use oalib::{hash_n, TAG_HALF};
unconstrained fn main(hc_a: [Field; 11], hc_b: [Field; 11]) -> pub (Field, Field) {
    (hash_n(TAG_HALF, hc_a), hash_n(TAG_HALF, hc_b))
}

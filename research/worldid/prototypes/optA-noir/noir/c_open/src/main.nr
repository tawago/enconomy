use oalib::{open_leaves, NL, NT};
fn main(xs: [u16; NT], chs: [[[Field; 4]; 4]; NL], leaf_s: Field, xp: [u16; NT], chp: [[[Field; 4]; 4]; NL], leaf_p: Field, root: Field) {
    open_leaves(xs, leaf_s, chs, root);
    open_leaves(xp, leaf_p, chp, root);
}

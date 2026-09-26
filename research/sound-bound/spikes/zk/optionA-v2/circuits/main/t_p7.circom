pragma circom 2.2.3;
include "oa2lib.circom";
template T() {
    signal input a[20];
    signal input x[1024];
    signal input c[4];
    signal output s1; signal output s2; signal output lh; signal output nd;
    component sp = Sponge16(20, 12345); sp.in <== a; s1 <== sp.o1; s2 <== sp.o2;
    component lf = Leaf1024(); lf.x <== x; lh <== lf.h;
    component n = Node5(); n.c <== c; nd <== n.out;
}
component main = T();

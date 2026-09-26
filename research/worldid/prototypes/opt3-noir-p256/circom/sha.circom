pragma circom 2.1.6;
include "circomlib/circuits/sha256/sha256.circom";
template Two() { signal input t[2488]; signal input c[888]; signal output ht[256]; signal output hc[256];
  component a = Sha256(2488); a.in <== t; ht <== a.out;
  component b = Sha256(888); b.in <== c; hc <== b.out; }
component main = Two();

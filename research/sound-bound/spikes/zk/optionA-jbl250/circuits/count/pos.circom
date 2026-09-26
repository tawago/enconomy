pragma circom 2.1.0;
include "../../../node_modules/circomlib/circuits/poseidon.circom";
template T() { signal input a[16]; signal input b[2]; signal output o1; signal output o2;
 component p = Poseidon(16); p.inputs <== a; o1 <== p.out; component q = Poseidon(2); q.inputs <== b; o2 <== q.out; }
component main = T();

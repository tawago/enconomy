pragma circom 2.1.0;
include "../../../node_modules/circomlib/circuits/poseidon.circom";
template T() { signal input b[2]; signal output o2; component q = Poseidon(2); q.inputs <== b; o2 <== q.out; }
component main = T();

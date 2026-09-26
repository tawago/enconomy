pragma circom 2.1.0;
include "circomlib/circuits/poseidon.circom";
template H(n) { signal input in[n]; signal output out; component h = Poseidon(n); for (var i=0;i<n;i++) h.inputs[i] <== in[i]; out <== h.out; }

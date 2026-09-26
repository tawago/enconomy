pragma circom 2.1.0;

include "../../node_modules/circomlib/circuits/poseidon.circom";
include "../../node_modules/circomlib/circuits/bitify.circom";

// in in [0, 2^W): W boolean constraints + 1 linear.
template Range(W) {
    signal input in;
    component b = Num2Bits(W);
    b.in <== in;
}

// Poseidon(16) chain over N field elements, 15 new elements per call, length as IV.
template HashChain(N) {
    signal input in[N];
    signal output h;
    var P = (N + 14) \ 15;
    component ps[P];
    for (var p = 0; p < P; p++) {
        ps[p] = Poseidon(16);
        if (p == 0) { ps[p].inputs[0] <== N; } else { ps[p].inputs[0] <== ps[p - 1].out; }
        for (var j = 0; j < 15; j++) {
            var idx = p * 15 + j;
            if (idx < N) { ps[p].inputs[j + 1] <== in[idx]; } else { ps[p].inputs[j + 1] <== 0; }
        }
    }
    h <== ps[P - 1].out;
}

// Commitment to N int16 samples: range-check each (16 bits), pack 15 per element, HashChain.
// Binding because every sample is forced into [-32768, 32767] before packing.
template Commit16(N) {
    signal input x[N];
    signal output h;
    component rc[N];
    for (var i = 0; i < N; i++) {
        rc[i] = Num2Bits(16);
        rc[i].in <== x[i] + 32768;
    }
    var E = (N + 14) \ 15;
    component hc = HashChain(E);
    for (var e = 0; e < E; e++) {
        var lc = 0;
        for (var j = 0; j < 15; j++) {
            var idx = e * 15 + j;
            if (idx < N) { lc += (x[idx] + 32768) * (1 << (16 * j)); }
        }
        hc.in[e] <== lc;
    }
    h <== hc.h;
}

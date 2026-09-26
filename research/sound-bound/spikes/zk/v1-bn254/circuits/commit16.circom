pragma circom 2.1.0;

include "../../node_modules/circomlib/circuits/poseidon.circom";
include "../../node_modules/circomlib/circuits/bitify.circom";

// Commit to N signed 16-bit samples: range-check each, pack 15 per field
// element, absorb 15 elements per Poseidon(16) in a chain.
template Commit16(N) {
    signal input x[N];
    signal output h;

    component rc[N];
    for (var i = 0; i < N; i++) {
        rc[i] = Num2Bits(16);
        rc[i].in <== x[i] + 32768;
    }

    var E = (N + 14) \ 15;          // packed elements
    var P = (E + 14) \ 15;          // Poseidon calls
    signal packed[P * 15];
    for (var e = 0; e < P * 15; e++) {
        var lc = 0;
        for (var j = 0; j < 15; j++) {
            var idx = e * 15 + j;
            if (idx < N) { lc += (x[idx] + 32768) * (1 << (16 * j)); }
        }
        packed[e] <== lc;
    }

    component ps[P];
    for (var p = 0; p < P; p++) {
        ps[p] = Poseidon(16);
        if (p == 0) { ps[p].inputs[0] <== 0; } else { ps[p].inputs[0] <== ps[p - 1].out; }
        for (var j = 0; j < 15; j++) { ps[p].inputs[j + 1] <== packed[p * 15 + j]; }
    }
    h <== ps[P - 1].out;
}

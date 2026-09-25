pragma circom 2.1.0;

include "commit16.circom";

// Option A core: analytic matched filter at K lags, template length L.
// Recording and template (I and its Hilbert pair Q) are private, committed by hash.
// Outputs per lag: I, Q, env^2 = I^2 + Q^2, and window energy E = sum x^2.
// Not included: band mask, normalization divide, ppm bank, null codes,
// first-peak rule, deriving the template from the seed.
template Corr(L, K) {
    signal input rec[L + K - 1];
    signal input tI[L];
    signal input tQ[L];

    signal output recH;
    signal output tH;
    signal output I[K];
    signal output Q[K];
    signal output env2[K];
    signal output E[K];

    component cr = Commit16(L + K - 1);
    cr.x <== rec;
    recH <== cr.h;

    component ci = Commit16(L);
    component cq = Commit16(L);
    ci.x <== tI;
    cq.x <== tQ;
    component th = Poseidon(2);
    th.inputs[0] <== ci.h;
    th.inputs[1] <== cq.h;
    tH <== th.out;

    signal pI[K][L];
    signal pQ[K][L];
    for (var k = 0; k < K; k++) {
        var si = 0;
        var sq = 0;
        for (var n = 0; n < L; n++) {
            pI[k][n] <== rec[k + n] * tI[n];
            pQ[k][n] <== rec[k + n] * tQ[n];
            si += pI[k][n];
            sq += pQ[k][n];
        }
        I[k] <== si;
        Q[k] <== sq;
    }

    signal x2[L + K - 1];
    for (var i = 0; i < L + K - 1; i++) { x2[i] <== rec[i] * rec[i]; }
    signal i2[K];
    for (var k = 0; k < K; k++) {
        var e = 0;
        for (var n = 0; n < L; n++) { e += x2[k + n]; }
        E[k] <== e;
        i2[k] <== I[k] * I[k];
        env2[k] <== i2[k] + Q[k] * Q[k];
    }
}

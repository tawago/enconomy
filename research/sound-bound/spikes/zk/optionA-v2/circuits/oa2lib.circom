pragma circom 2.2.3;
include "p7.circom";
include "circomlib/circuits/bitify.circom";
include "circomlib/circuits/comparators.circom";

// in in [0, 2^W): W boolean constraints (recomposition is linear).
template Range(W) {
    signal input in;
    component b = Num2Bits(W);
    b.in <== in;
}

// 1,024 int16 samples: range check (16 bits each) and leaf hash (packed 15 per element).
template Leaf1024() {
    signal input x[1024];
    signal output h;
    component rc[1024];
    for (var i = 0; i < 1024; i++) { rc[i] = Num2Bits(16); rc[i].in <== x[i] + 32768; }
    component sp = Sponge16(69, 262145);
    for (var e = 0; e < 69; e++) {
        var lc = 0;
        for (var j = 0; j < 15; j++) {
            var idx = e * 15 + j;
            if (idx < 1024) { lc += (x[idx] + 32768) * (1 << (16 * j)); }
        }
        sp.in[e] <== lc;
    }
    h <== sp.o1;
}

// Path of one leaf in the 4-ary depth-6 tree. idx: 12-bit leaf index (range-checked here).
// ch[l][k]: the 4 children of the level-l parent on the path; ch[l][digit_l] must equal the running node.
template MerklePath() {
    signal input leaf;
    signal input idx;
    signal input ch[6][4];
    signal output root;
    component ib = Num2Bits(12);
    ib.in <== idx;
    component nd[6];
    signal s3[6];
    signal t1[6];
    signal t2[6];
    signal t3[6];
    var cur = leaf;
    for (var l = 0; l < 6; l++) {
        var b0 = ib.out[2 * l];
        var b1 = ib.out[2 * l + 1];
        s3[l] <== b0 * b1;
        // ch[digit] = ch0 + b0 (ch1 - ch0) + b1 (ch2 - ch0) + b0 b1 (ch3 - ch2 - ch1 + ch0)
        t1[l] <== b0 * (ch[l][1] - ch[l][0]);
        t2[l] <== b1 * (ch[l][2] - ch[l][0]);
        t3[l] <== s3[l] * (ch[l][3] - ch[l][2] - ch[l][1] + ch[l][0]);
        cur === ch[l][0] + t1[l] + t2[l] + t3[l];
        nd[l] = Node5();
        for (var k = 0; k < 4; k++) { nd[l].c[k] <== ch[l][k]; }
        cur = nd[l].out;
    }
    root <== cur;
}

// One barrel stage: out[i] = in[i + S * bit].
template ShiftStage(NIN, S) {
    signal input in[NIN];
    signal input bit;
    signal output out[NIN - S];
    for (var i = 0; i < NIN - S; i++) { out[i] <== in[i] + bit * (in[i + S] - in[i]); }
}

// out[i] = in[i + o], o = sum bits[k] 2^k (10 bits), i < NOUT.  NIN >= NOUT + 1023.
template Barrel1024(NIN, NOUT) {
    signal input in[NIN];
    signal input bits[10];
    signal output out[NOUT];
    component st[10];
    var need = NOUT + 1023;
    for (var k = 0; k < 10; k++) {
        st[k] = ShiftStage(need, 1 << k);
        for (var i = 0; i < need; i++) {
            if (k == 0) { st[k].in[i] <== in[i]; } else { st[k].in[i] <== st[k - 1].out[i]; }
        }
        st[k].bit <== bits[k];
        need = need - (1 << k);
    }
    for (var i = 0; i < NOUT; i++) { out[i] <== st[9].out[i]; }
}

// NL contiguous leaves starting at leaf index `first`, all under `root`. Output: the samples.
template OpenLeaves(NL) {
    signal input x[NL][1024];
    signal input first;
    signal input ch[NL][6][4];
    signal input root;
    component lf[NL];
    component mp[NL];
    for (var i = 0; i < NL; i++) {
        lf[i] = Leaf1024();
        lf[i].x <== x[i];
        mp[i] = MerklePath();
        mp[i].leaf <== lf[i].h;
        mp[i].idx <== first + i;
        mp[i].ch <== ch[i];
        mp[i].root === root;
    }
}

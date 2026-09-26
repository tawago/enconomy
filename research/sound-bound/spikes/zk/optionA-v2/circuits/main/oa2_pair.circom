pragma circom 2.2.3;
// Pair statement: the two per-phone half commitments (same nonce/attempt, roles A and B) open to halves
// with dLo < halfA - halfB < dHi  (-20 cm < flight < 60 cm; verifier computes dLo, dHi from sr).
include "oa2lib.circom";

template Pair() {
    signal input nonceHi;
    signal input nonceLo;
    signal input attempt;
    signal input commitA;
    signal input commitB;
    signal input dLo;
    signal input dHi;
    signal input halfA;
    signal input saltA;
    signal input halfB;
    signal input saltB;
    component ca = Sponge16(6, 4);
    ca.in[0] <== nonceHi; ca.in[1] <== nonceLo; ca.in[2] <== attempt; ca.in[3] <== 0;
    ca.in[4] <== halfA; ca.in[5] <== saltA;
    ca.o1 === commitA;
    component cb = Sponge16(6, 4);
    cb.in[0] <== nonceHi; cb.in[1] <== nonceLo; cb.in[2] <== attempt; cb.in[3] <== 1;
    cb.in[4] <== halfB; cb.in[5] <== saltB;
    cb.o1 === commitB;
    var OFF = 1 << 34;
    component ra = Num2Bits(32); ra.in <== halfA + (1 << 31);
    component rb = Num2Bits(32); rb.in <== halfB + (1 << 31);
    signal a <== halfA - halfB + OFF;
    component loR = Num2Bits(35); loR.in <== dLo + OFF;
    component hiR = Num2Bits(35); hiR.in <== dHi + OFF;
    component gtLo = LessThan(36); gtLo.in[0] <== dLo + OFF; gtLo.in[1] <== a; gtLo.out === 1;
    component ltHi = LessThan(36); ltHi.in[0] <== a; ltHi.in[1] <== dHi + OFF; ltHi.out === 1;
}

component main {public [nonceHi, nonceLo, attempt, commitA, commitB, dLo, dHi]} = Pair();

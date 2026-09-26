pragma circom 2.2.3;
// Cost probe: SHA-256 over one 2,048-byte leaf (1,024 int16 samples), circomlib, secq256r1.
include "circomlib/circuits/sha256/sha256.circom";
include "circomlib/circuits/bitify.circom";
template T() {
    signal input x[1024];
    signal output h[256];
    component rc[1024];
    component sha = Sha256(8 * 2048);
    for (var i = 0; i < 1024; i++) {
        rc[i] = Num2Bits(16); rc[i].in <== x[i] + 32768;
        for (var j = 0; j < 16; j++) { sha.in[16 * i + j] <== rc[i].out[15 - j]; }
    }
    h <== sha.out;
}
component main = T();

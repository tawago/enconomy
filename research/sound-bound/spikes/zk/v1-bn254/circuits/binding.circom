pragma circom 2.1.0;

include "../../node_modules/circomlib/circuits/poseidon.circom";
include "../../node_modules/circomlib/circuits/eddsaposeidon.circom";
include "../../node_modules/circomlib/circuits/comparators.circom";

// Option C: the audio analysis runs outside (attested app or server) and signs
// its result. The circuit binds that result to both identities and hides them.
//
// Public:  sessionCommit, measurerKeyHash, maxFlight, minDrr, minScore, nullifier
// Private: seed, salt, both identity keys + signatures, the measured values,
//          the measurer's key + signature, timestamp
//
// Fixed point: flight in mm (>= 0), drr in 0.01 dB offset by +10000, score in 0.01 %.
template Binding() {
    signal input sessionCommit;
    signal input measurerKeyHash;
    signal input maxFlight;
    signal input minDrr;
    signal input minScore;
    signal input nullifier;

    signal input seed;
    signal input salt;
    signal input timestamp;
    signal input flight;
    signal input drr;
    signal input score;
    signal input pkA[2];
    signal input sigA[3];     // R8x, R8y, S
    signal input pkB[2];
    signal input sigB[3];
    signal input pkM[2];
    signal input sigM[3];

    // 1. the seed the phones played is the one committed for this session
    component sc = Poseidon(2);
    sc.inputs[0] <== seed;
    sc.inputs[1] <== salt;
    sessionCommit === sc.out;

    // 2. the measurer is an accepted one
    component mk = Poseidon(2);
    mk.inputs[0] <== pkM[0];
    mk.inputs[1] <== pkM[1];
    measurerKeyHash === mk.out;

    // 3. measurer signed (session, identities, time, values)
    component msg = Poseidon(10);
    msg.inputs[0] <== sessionCommit;
    msg.inputs[1] <== pkA[0];
    msg.inputs[2] <== pkA[1];
    msg.inputs[3] <== pkB[0];
    msg.inputs[4] <== pkB[1];
    msg.inputs[5] <== timestamp;
    msg.inputs[6] <== flight;
    msg.inputs[7] <== drr;
    msg.inputs[8] <== score;
    msg.inputs[9] <== 0;
    component vM = EdDSAPoseidonVerifier();
    vM.enabled <== 1;
    vM.Ax <== pkM[0]; vM.Ay <== pkM[1];
    vM.R8x <== sigM[0]; vM.R8y <== sigM[1]; vM.S <== sigM[2];
    vM.M <== msg.out;

    // 4. both parties signed the same attestation
    component att = Poseidon(6);
    att.inputs[0] <== sessionCommit;
    att.inputs[1] <== pkA[0];
    att.inputs[2] <== pkA[1];
    att.inputs[3] <== pkB[0];
    att.inputs[4] <== pkB[1];
    att.inputs[5] <== timestamp;
    component vA = EdDSAPoseidonVerifier();
    vA.enabled <== 1;
    vA.Ax <== pkA[0]; vA.Ay <== pkA[1];
    vA.R8x <== sigA[0]; vA.R8y <== sigA[1]; vA.S <== sigA[2];
    vA.M <== att.out;
    component vB = EdDSAPoseidonVerifier();
    vB.enabled <== 1;
    vB.Ax <== pkB[0]; vB.Ay <== pkB[1];
    vB.R8x <== sigB[0]; vB.R8y <== sigB[1]; vB.S <== sigB[2];
    vB.M <== att.out;

    // 5. values pass the thresholds
    component f = LessThan(32);
    f.in[0] <== flight; f.in[1] <== maxFlight; f.out === 1;
    component d = GreaterEqThan(32);
    d.in[0] <== drr; d.in[1] <== minDrr; d.out === 1;
    component s = GreaterEqThan(32);
    s.in[0] <== score; s.in[1] <== minScore; s.out === 1;

    // 6. one proof per meeting
    component nf = Poseidon(3);
    nf.inputs[0] <== sessionCommit;
    nf.inputs[1] <== pkA[0];
    nf.inputs[2] <== pkB[0];
    nullifier === nf.out;
}

component main {public [sessionCommit, measurerKeyHash, maxFlight, minDrr, minScore, nullifier]} = Binding();

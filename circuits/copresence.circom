pragma circom 2.1.0;

include "circomlib/circuits/poseidon.circom";
include "circomlib/circuits/eddsaposeidon.circom";

/**
 * Copresence Attestation Circuit
 *
 * Proves that two parties (A and B) were co-present by verifying:
 * 1. The attestation hash matches the hash of (timestamp, nonceA, nonceB, audioKeyHash)
 * 2. Both parties signed the attestation hash with their EdDSA private keys
 *
 * The nullifier is used to prevent double-spending of attestations.
 */
template Copresence() {
    // Public inputs
    signal input attestationHash;
    signal input nullifier;

    // Private inputs - attestation data
    signal input timestamp;
    signal input nonceA;
    signal input nonceB;
    signal input audioKeyHash;

    // Private inputs - Party A's EdDSA signature
    signal input pubKeyA[2];  // [Ax, Ay]
    signal input sigRA[2];    // R point [Rx, Ry]
    signal input sigSA;       // S scalar

    // Private inputs - Party B's EdDSA signature
    signal input pubKeyB[2];  // [Bx, By]
    signal input sigRB[2];    // R point [Rx, Ry]
    signal input sigSB;       // S scalar

    // Constraint 1: Verify attestation hash computation
    component hasher = Poseidon(4);
    hasher.inputs[0] <== timestamp;
    hasher.inputs[1] <== nonceA;
    hasher.inputs[2] <== nonceB;
    hasher.inputs[3] <== audioKeyHash;
    attestationHash === hasher.out;

    // Constraint 2: Verify Party A's EdDSA signature on attestationHash
    component verifyA = EdDSAPoseidonVerifier();
    verifyA.enabled <== 1;
    verifyA.Ax <== pubKeyA[0];
    verifyA.Ay <== pubKeyA[1];
    verifyA.R8x <== sigRA[0];
    verifyA.R8y <== sigRA[1];
    verifyA.S <== sigSA;
    verifyA.M <== attestationHash;

    // Constraint 3: Verify Party B's EdDSA signature on attestationHash
    component verifyB = EdDSAPoseidonVerifier();
    verifyB.enabled <== 1;
    verifyB.Ax <== pubKeyB[0];
    verifyB.Ay <== pubKeyB[1];
    verifyB.R8x <== sigRB[0];
    verifyB.R8y <== sigRB[1];
    verifyB.S <== sigSB;
    verifyB.M <== attestationHash;

    // Constraint 4: Verify nullifier is derived from the attestation
    // (Nullifier should be computed as hash(attestationHash, pubKeyA, pubKeyB) off-chain
    // and verified here to ensure uniqueness)
    component nullifierHasher = Poseidon(5);
    nullifierHasher.inputs[0] <== attestationHash;
    nullifierHasher.inputs[1] <== pubKeyA[0];
    nullifierHasher.inputs[2] <== pubKeyA[1];
    nullifierHasher.inputs[3] <== pubKeyB[0];
    nullifierHasher.inputs[4] <== pubKeyB[1];
    nullifier === nullifierHasher.out;
}

component main {public [attestationHash, nullifier]} = Copresence();

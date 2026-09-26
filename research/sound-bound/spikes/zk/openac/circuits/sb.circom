pragma circom 2.2.3;

// Sound-bound co-presence statement over secq256r1 (circuit field = P-256 base field p).
// ECDSA P-256 gadget, HashModScalarField: PSE zkID wallet-unit-poc (vendor/zkID).
// SHA-256: circomlib (fixed length, standard padding).
//
// Byte layouts (big-endian), must match ../../enclave/common.py:
//   transcript = "SBv1" | nonce(32) | attempt(u8) | role(u8) | own_pub(64) | partner_pub(64)
//                | sr(u32) | half(i32) | rec_hash(32) | n_ts(u8) | ts(u64 * n_ts)
//   cred v1    = "SBcred1" | device_pub(64) | expiry(u64)
//   cred v2    = "SBcred2" | device_pub(64) | expiry(u64) | holder_commit(32)
//   holder_commit = SHA256("SBhold1" | holder_secret(32))
//   nullifier     = first 31 bytes of SHA256(holder_secret(32) | nonce(32)), as an integer

include "circomlib/circuits/sha256/sha256.circom";
include "circomlib/circuits/bitify.circom";
include "circomlib/circuits/comparators.circom";
include "ecdsa/ecdsa.circom";
include "utils/utils.circom";

// n bytes -> 8n bits, MSB first per byte. Range-checks every byte.
template BytesBits(n) {
    signal input in[n];
    signal output out[8 * n];
    component nb[n];
    for (var i = 0; i < n; i++) {
        nb[i] = Num2Bits(8);
        nb[i].in <== in[i];
        for (var j = 0; j < 8; j++) {
            out[8 * i + j] <== nb[i].out[7 - j];
        }
    }
}

// Field element (< 2^nb) -> nb bits, MSB first. Range-checks.
template NumBitsBE(nb) {
    signal input in;
    signal output out[nb];
    component n2b = Num2Bits(nb);
    n2b.in <== in;
    for (var i = 0; i < nb; i++) {
        out[i] <== n2b.out[nb - 1 - i];
    }
}

// MSB-first bits -> integer (no wrap as long as nb < 256 and caller knows the value < p).
template PackBits(nb) {
    signal input in[nb];
    signal output out;
    var acc = 0;
    for (var i = 0; i < nb; i++) {
        acc = acc * 2 + in[i];
    }
    out <== acc;
}

// Big-endian bytes -> field element (reduced mod p).
template PackBytes(n) {
    signal input in[n];
    signal output out;
    var acc = 0;
    for (var i = 0; i < n; i++) {
        acc = acc * 256 + in[i];
    }
    out <== acc;
}

// ECDSA P-256 verify over a 256-bit digest (MSB-first bits).
// sInv = s^-1 mod n is a witness; the zkID gadget checks sInv != 0, sInv < n, r != 0, r < n,
// pub on curve, and x(sInv*(m*G + r*Q)) == r.  Accepts high-S too (ECDSA itself does).
template VerifyDigestSig() {
    signal input digest[256];
    signal input r;
    signal input sInv;
    signal input pubX;
    signal input pubY;

    component m = HashModScalarField();
    m.hash <== digest;

    component e = ECDSA();
    e.s_inverse <== sInv;
    e.r <== r;
    e.m <== m.out;
    e.pubKeyX <== pubX;
    e.pubKeyY <== pubY;
}

// SHA256 of the SBv1 transcript, rebuilt from fields.
template TranscriptDigest(N_TS) {
    signal input nonceBits[256];
    signal input attemptBits[8];
    signal input roleBits[8];
    signal input ownBits[512];
    signal input partnerBits[512];
    signal input srBits[32];
    signal input halfBits[32];
    signal input recBits[256];
    signal input tsBits[N_TS * 64];
    signal output digest[256];

    var L = 4 + 32 + 1 + 1 + 64 + 64 + 4 + 4 + 32 + 1 + 8 * N_TS;
    component sha = Sha256(8 * L);
    var magic[4] = [0x53, 0x42, 0x76, 0x31];  // "SBv1"
    var k = 0;
    for (var i = 0; i < 4; i++) {
        for (var j = 0; j < 8; j++) { sha.in[k] <== (magic[i] >> (7 - j)) & 1; k++; }
    }
    for (var i = 0; i < 256; i++) { sha.in[k] <== nonceBits[i]; k++; }
    for (var i = 0; i < 8; i++)   { sha.in[k] <== attemptBits[i]; k++; }
    for (var i = 0; i < 8; i++)   { sha.in[k] <== roleBits[i]; k++; }
    for (var i = 0; i < 512; i++) { sha.in[k] <== ownBits[i]; k++; }
    for (var i = 0; i < 512; i++) { sha.in[k] <== partnerBits[i]; k++; }
    for (var i = 0; i < 32; i++)  { sha.in[k] <== srBits[i]; k++; }
    for (var i = 0; i < 32; i++)  { sha.in[k] <== halfBits[i]; k++; }
    for (var i = 0; i < 256; i++) { sha.in[k] <== recBits[i]; k++; }
    for (var j = 0; j < 8; j++)   { sha.in[k] <== (N_TS >> (7 - j)) & 1; k++; }
    for (var i = 0; i < N_TS * 64; i++) { sha.in[k] <== tsBits[i]; k++; }
    digest <== sha.out;
}

// SHA256 of the credential. CRED_V = 1: SBcred1 (79 bytes). CRED_V = 2: SBcred2 with holder commit (111 bytes).
template CredDigest(CRED_V) {
    signal input pubBits[512];
    signal input expBits[64];
    signal input commitBits[256];   // ignored (and unconstrained) when CRED_V == 1
    signal output digest[256];

    var L = CRED_V == 2 ? 7 + 64 + 8 + 32 : 7 + 64 + 8;
    component sha = Sha256(8 * L);
    var magic[7] = [0x53, 0x42, 0x63, 0x72, 0x65, 0x64, 0x30 + CRED_V];  // "SBcred1" / "SBcred2"
    var k = 0;
    for (var i = 0; i < 7; i++) {
        for (var j = 0; j < 8; j++) { sha.in[k] <== (magic[i] >> (7 - j)) & 1; k++; }
    }
    for (var i = 0; i < 512; i++) { sha.in[k] <== pubBits[i]; k++; }
    for (var i = 0; i < 64; i++)  { sha.in[k] <== expBits[i]; k++; }
    if (CRED_V == 2) {
        for (var i = 0; i < 256; i++) { sha.in[k] <== commitBits[i]; k++; }
    }
    digest <== sha.out;
}

// Signed i32 from 32 MSB-first bits (two's complement), as a field element.
template SignedI32() {
    signal input bits[32];
    signal output out;
    var acc = 0;
    for (var i = 0; i < 32; i++) { acc = acc * 2 + bits[i]; }
    out <== acc - bits[0] * (1 << 32);
}

// One device: issuer signed its credential (which contains its pub and expiry >= validAt),
// and the device key signed the transcript whose bits are given.
template DeviceChecks(CRED_V) {
    signal input transcriptDigest[256];
    signal input pubBits[512];
    signal input pubX;
    signal input pubY;
    signal input sigR;
    signal input sigSInv;
    signal input expBytes[8];
    signal input commitBits[256];
    signal input credR;
    signal input credSInv;
    signal input issuerX;
    signal input issuerY;
    signal input validAt;          // range-checked to 64 bits by the caller

    component dev = VerifyDigestSig();
    dev.digest <== transcriptDigest;
    dev.r <== sigR;
    dev.sInv <== sigSInv;
    dev.pubX <== pubX;
    dev.pubY <== pubY;

    component expB = BytesBits(8);
    expB.in <== expBytes;
    component cd = CredDigest(CRED_V);
    cd.pubBits <== pubBits;
    cd.expBits <== expB.out;
    cd.commitBits <== commitBits;

    component iss = VerifyDigestSig();
    iss.digest <== cd.digest;
    iss.r <== credR;
    iss.sInv <== credSInv;
    iss.pubX <== issuerX;
    iss.pubY <== issuerY;

    component expV = PackBytes(8);
    expV.in <== expBytes;
    component notExpired = LessEqThan(64);
    notExpired.in[0] <== validAt;
    notExpired.in[1] <== expV.out;
    notExpired.out === 1;
}

// nullifier = first 31 bytes of SHA256(secret || nonce).
template Nullifier() {
    signal input secretBits[256];
    signal input nonceBits[256];
    signal output out;
    component sha = Sha256(512);
    for (var i = 0; i < 256; i++) {
        sha.in[i] <== secretBits[i];
        sha.in[256 + i] <== nonceBits[i];
    }
    component pk = PackBits(248);
    for (var i = 0; i < 248; i++) { pk.in[i] <== sha.out[i]; }
    out <== pk.out;
}

// SHA256("SBhold1" || secret) as bits.
template HolderCommit() {
    signal input secretBits[256];
    signal output digest[256];
    component sha = Sha256(8 * 39);
    var magic[7] = [0x53, 0x42, 0x68, 0x6f, 0x6c, 0x64, 0x31];  // "SBhold1"
    var k = 0;
    for (var i = 0; i < 7; i++) {
        for (var j = 0; j < 8; j++) { sha.in[k] <== (magic[i] >> (7 - j)) & 1; k++; }
    }
    for (var i = 0; i < 256; i++) { sha.in[k] <== secretBits[i]; k++; }
    digest <== sha.out;
}

// Public nonce (2 x 128-bit limbs, hi first), attempt, sr -> bits.
template PublicHeader() {
    signal input nonceHi;
    signal input nonceLo;
    signal input attempt;
    signal input sr;
    signal input validAt;
    signal output nonceBits[256];
    signal output attemptBits[8];
    signal output srBits[32];

    component h = NumBitsBE(128); h.in <== nonceHi;
    component l = NumBitsBE(128); l.in <== nonceLo;
    for (var i = 0; i < 128; i++) {
        nonceBits[i] <== h.out[i];
        nonceBits[128 + i] <== l.out[i];
    }
    component a = NumBitsBE(8); a.in <== attempt; attemptBits <== a.out;
    component s = NumBitsBE(32); s.in <== sr; srBits <== s.out;
    component v = Num2Bits(64); v.in <== validAt;
}

// Two-role statement. Public: nonceHi, nonceLo, attempt, issuerX, issuerY, sr, dLo, dHi, validAt;
// output nullifier. Accepts iff both roles are credentialed, both signed SBv1 transcripts for this
// nonce/attempt with crossed pubs and roles A/B, and dLo < halfA - halfB < dHi.
template SBPair(N_TS, CRED_V) {
    signal input nonceHi;
    signal input nonceLo;
    signal input attempt;
    signal input issuerX;
    signal input issuerY;
    signal input sr;
    signal input dLo;       // strict lower bound on halfA - halfB (signed, as field element)
    signal input dHi;       // strict upper bound
    signal input validAt;   // unix seconds; credentials must not expire before it
    signal output nullifier;

    signal input pubA[64];
    signal input pubB[64];
    signal input halfA[4];
    signal input halfB[4];
    signal input recA[32];
    signal input recB[32];
    signal input tsA[N_TS][8];
    signal input tsB[N_TS][8];
    signal input sigA_r;
    signal input sigA_sInv;
    signal input sigB_r;
    signal input sigB_sInv;
    signal input expA[8];
    signal input expB[8];
    signal input credA_r;
    signal input credA_sInv;
    signal input credB_r;
    signal input credB_sInv;
    signal input holderSecret[32];
    signal input commitA[32];   // CRED_V == 2 only (pass zeros for v1; unconstrained there)
    signal input commitB[32];
    signal input me;            // CRED_V == 2: 0 = prover holds role A's credential, 1 = B's

    component hdr = PublicHeader();
    hdr.nonceHi <== nonceHi;
    hdr.nonceLo <== nonceLo;
    hdr.attempt <== attempt;
    hdr.sr <== sr;
    hdr.validAt <== validAt;

    component pA = BytesBits(64); pA.in <== pubA;
    component pB = BytesBits(64); pB.in <== pubB;
    component xA = PackBytes(32); component yA = PackBytes(32);
    component xB = PackBytes(32); component yB = PackBytes(32);
    for (var i = 0; i < 32; i++) {
        xA.in[i] <== pubA[i]; yA.in[i] <== pubA[32 + i];
        xB.in[i] <== pubB[i]; yB.in[i] <== pubB[32 + i];
    }
    component hA = BytesBits(4); hA.in <== halfA;
    component hB = BytesBits(4); hB.in <== halfB;
    component rA = BytesBits(32); rA.in <== recA;
    component rB = BytesBits(32); rB.in <== recB;
    component tA = BytesBits(8 * N_TS);
    component tB = BytesBits(8 * N_TS);
    for (var i = 0; i < N_TS; i++) {
        for (var j = 0; j < 8; j++) { tA.in[8 * i + j] <== tsA[i][j]; tB.in[8 * i + j] <== tsB[i][j]; }
    }
    component cA = BytesBits(32); cA.in <== commitA;
    component cB = BytesBits(32); cB.in <== commitB;

    // role A transcript: role 0x41, own = A, partner = B
    component trA = TranscriptDigest(N_TS);
    trA.nonceBits <== hdr.nonceBits;
    trA.attemptBits <== hdr.attemptBits;
    for (var j = 0; j < 8; j++) { trA.roleBits[j] <== (0x41 >> (7 - j)) & 1; }
    trA.ownBits <== pA.out;
    trA.partnerBits <== pB.out;
    trA.srBits <== hdr.srBits;
    trA.halfBits <== hA.out;
    trA.recBits <== rA.out;
    trA.tsBits <== tA.out;

    // role B transcript: role 0x42, own = B, partner = A
    component trB = TranscriptDigest(N_TS);
    trB.nonceBits <== hdr.nonceBits;
    trB.attemptBits <== hdr.attemptBits;
    for (var j = 0; j < 8; j++) { trB.roleBits[j] <== (0x42 >> (7 - j)) & 1; }
    trB.ownBits <== pB.out;
    trB.partnerBits <== pA.out;
    trB.srBits <== hdr.srBits;
    trB.halfBits <== hB.out;
    trB.recBits <== rB.out;
    trB.tsBits <== tB.out;

    component devA = DeviceChecks(CRED_V);
    devA.transcriptDigest <== trA.digest;
    devA.pubBits <== pA.out;
    devA.pubX <== xA.out;
    devA.pubY <== yA.out;
    devA.sigR <== sigA_r;
    devA.sigSInv <== sigA_sInv;
    devA.expBytes <== expA;
    devA.commitBits <== cA.out;
    devA.credR <== credA_r;
    devA.credSInv <== credA_sInv;
    devA.issuerX <== issuerX;
    devA.issuerY <== issuerY;
    devA.validAt <== validAt;

    component devB = DeviceChecks(CRED_V);
    devB.transcriptDigest <== trB.digest;
    devB.pubBits <== pB.out;
    devB.pubX <== xB.out;
    devB.pubY <== yB.out;
    devB.sigR <== sigB_r;
    devB.sigSInv <== sigB_sInv;
    devB.expBytes <== expB;
    devB.commitBits <== cB.out;
    devB.credR <== credB_r;
    devB.credSInv <== credB_sInv;
    devB.issuerX <== issuerX;
    devB.issuerY <== issuerY;
    devB.validAt <== validAt;

    // Verdict: dLo < halfA - halfB < dHi, integer compare after shifting by 2^34.
    component sA = SignedI32(); sA.bits <== hA.out;
    component sB = SignedI32(); sB.bits <== hB.out;
    var OFF = 1 << 34;
    signal a <== sA.out - sB.out + OFF;        // in [0, 2^35) by construction
    component loR = Num2Bits(35); loR.in <== dLo + OFF;
    component hiR = Num2Bits(35); hiR.in <== dHi + OFF;
    component gtLo = LessThan(36); gtLo.in[0] <== dLo + OFF; gtLo.in[1] <== a; gtLo.out === 1;
    component ltHi = LessThan(36); ltHi.in[0] <== a; ltHi.in[1] <== dHi + OFF; ltHi.out === 1;

    // Nullifier.
    component sec = BytesBits(32); sec.in <== holderSecret;
    component nf = Nullifier();
    nf.secretBits <== sec.out;
    nf.nonceBits <== hdr.nonceBits;
    nullifier <== nf.out;

    if (CRED_V == 2) {
        // Bind the holder secret to one of the two credentials (the prover's own).
        me * (me - 1) === 0;
        component hc = HolderCommit();
        hc.secretBits <== sec.out;
        signal sel[256];
        for (var i = 0; i < 256; i++) {
            sel[i] <== cA.out[i] + me * (cB.out[i] - cA.out[i]);
            hc.digest[i] === sel[i];
        }
    }
}

// One-role variant (cost reference): one device proves its own signed half.
// Public: nonceHi, nonceLo, attempt, issuerX, issuerY, sr, roleB (0 = A, 1 = B), validAt;
// outputs nullifier, half. Partner pub stays private (and unchecked beyond being signed).
template SBHalf(N_TS, CRED_V) {
    signal input nonceHi;
    signal input nonceLo;
    signal input attempt;
    signal input issuerX;
    signal input issuerY;
    signal input sr;
    signal input roleB;
    signal input validAt;
    signal output nullifier;
    signal output half;

    signal input ownPub[64];
    signal input partnerPub[64];
    signal input halfBytes[4];
    signal input rec[32];
    signal input ts[N_TS][8];
    signal input sig_r;
    signal input sig_sInv;
    signal input exp[8];
    signal input cred_r;
    signal input cred_sInv;
    signal input holderSecret[32];
    signal input commit[32];

    component hdr = PublicHeader();
    hdr.nonceHi <== nonceHi;
    hdr.nonceLo <== nonceLo;
    hdr.attempt <== attempt;
    hdr.sr <== sr;
    hdr.validAt <== validAt;
    roleB * (roleB - 1) === 0;

    component pO = BytesBits(64); pO.in <== ownPub;
    component pP = BytesBits(64); pP.in <== partnerPub;
    component xO = PackBytes(32); component yO = PackBytes(32);
    for (var i = 0; i < 32; i++) { xO.in[i] <== ownPub[i]; yO.in[i] <== ownPub[32 + i]; }
    component hb = BytesBits(4); hb.in <== halfBytes;
    component rb = BytesBits(32); rb.in <== rec;
    component tb = BytesBits(8 * N_TS);
    for (var i = 0; i < N_TS; i++) { for (var j = 0; j < 8; j++) { tb.in[8 * i + j] <== ts[i][j]; } }
    component cb = BytesBits(32); cb.in <== commit;

    component tr = TranscriptDigest(N_TS);
    tr.nonceBits <== hdr.nonceBits;
    tr.attemptBits <== hdr.attemptBits;
    // 0x41 = 01000001, 0x42 = 01000010
    for (var j = 0; j < 6; j++) { tr.roleBits[j] <== (0x41 >> (7 - j)) & 1; }
    tr.roleBits[6] <== roleB;
    tr.roleBits[7] <== 1 - roleB;
    tr.ownBits <== pO.out;
    tr.partnerBits <== pP.out;
    tr.srBits <== hdr.srBits;
    tr.halfBits <== hb.out;
    tr.recBits <== rb.out;
    tr.tsBits <== tb.out;

    component dev = DeviceChecks(CRED_V);
    dev.transcriptDigest <== tr.digest;
    dev.pubBits <== pO.out;
    dev.pubX <== xO.out;
    dev.pubY <== yO.out;
    dev.sigR <== sig_r;
    dev.sigSInv <== sig_sInv;
    dev.expBytes <== exp;
    dev.commitBits <== cb.out;
    dev.credR <== cred_r;
    dev.credSInv <== cred_sInv;
    dev.issuerX <== issuerX;
    dev.issuerY <== issuerY;
    dev.validAt <== validAt;

    component s = SignedI32(); s.bits <== hb.out;
    half <== s.out;

    component sec = BytesBits(32); sec.in <== holderSecret;
    component nf = Nullifier();
    nf.secretBits <== sec.out;
    nf.nonceBits <== hdr.nonceBits;
    nullifier <== nf.out;

    if (CRED_V == 2) {
        component hc = HolderCommit();
        hc.secretBits <== sec.out;
        for (var i = 0; i < 256; i++) { hc.digest[i] === cb.out[i]; }
    }
}

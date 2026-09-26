pragma circom 2.2.3;

// Option C on the real app transcript: POPT v1 (docs/pop-contract.md §7.1, 269 bytes), two roles, one proof.
// Field = P-256 base field (circom --prime secq256r1). Gadgets reused from sb.circom (zkID ECDSA, circomlib SHA).
//
// POPT v1, big-endian, exactly what the app signs (SHA256withECDSA over the raw bytes):
//   0 "POPT" | 4 0x01 | 5 role 'A'/'B' | 6 attempt u8 | 7 session_nonce(32) | 39 pk_self(65 = 04||X||Y)
//   | 104 pk_partner(65) | 169 sample_rate u32 | 173 half i32 | 177 rec_sha256(32) | 209 play_frame_position u64
//   | 217 play_nano_time u64 | 225 rec_frame0_nano_time u64 | 233 self_os_delta i32 | 237 commit_hash(32)
//
// Constants from server/pop/constants.py (checked by verifier/check_fixtures_server.py):
//   SPEED_OF_SOUND_CM_S 34300, IMPOSSIBLE_CM -20, NEAR_CM 60, SELF_OS_TOL_MS 50, SR_MIN 36000, SR_MAX 96000.

include "sb.circom";

// SHA-256 of one POPT v1 transcript, rebuilt from its fields (all as MSB-first bit arrays).
template PoptV1Digest(ROLE) {
    signal input nonceBits[256];
    signal input attemptBits[8];
    signal input ownBits[512];       // X||Y of pk_self (the 0x04 prefix is a constant)
    signal input partnerBits[512];
    signal input srBits[32];
    signal input halfBits[32];
    signal input recBits[256];
    signal input pfpBits[64];
    signal input pntBits[64];
    signal input rf0Bits[64];
    signal input sodBits[32];
    signal input commitBits[256];
    signal output digest[256];

    component sha = Sha256(8 * 269);
    var hdr[6] = [0x50, 0x4F, 0x50, 0x54, 0x01, ROLE];   // "POPT", version 1, role byte
    var k = 0;
    for (var i = 0; i < 6; i++) { for (var j = 0; j < 8; j++) { sha.in[k] <== (hdr[i] >> (7 - j)) & 1; k++; } }
    for (var i = 0; i < 8; i++)   { sha.in[k] <== attemptBits[i]; k++; }
    for (var i = 0; i < 256; i++) { sha.in[k] <== nonceBits[i]; k++; }
    for (var j = 0; j < 8; j++)   { sha.in[k] <== (0x04 >> (7 - j)) & 1; k++; }
    for (var i = 0; i < 512; i++) { sha.in[k] <== ownBits[i]; k++; }
    for (var j = 0; j < 8; j++)   { sha.in[k] <== (0x04 >> (7 - j)) & 1; k++; }
    for (var i = 0; i < 512; i++) { sha.in[k] <== partnerBits[i]; k++; }
    for (var i = 0; i < 32; i++)  { sha.in[k] <== srBits[i]; k++; }
    for (var i = 0; i < 32; i++)  { sha.in[k] <== halfBits[i]; k++; }
    for (var i = 0; i < 256; i++) { sha.in[k] <== recBits[i]; k++; }
    for (var i = 0; i < 64; i++)  { sha.in[k] <== pfpBits[i]; k++; }
    for (var i = 0; i < 64; i++)  { sha.in[k] <== pntBits[i]; k++; }
    for (var i = 0; i < 64; i++)  { sha.in[k] <== rf0Bits[i]; k++; }
    for (var i = 0; i < 32; i++)  { sha.in[k] <== sodBits[i]; k++; }
    for (var i = 0; i < 256; i++) { sha.in[k] <== commitBits[i]; k++; }
    digest <== sha.out;
}

// SR_MIN <= sr <= SR_MAX (sr already < 2^32 from its bit decomposition).
template SrRange() {
    signal input sr;
    component lo = Num2Bits(17); lo.in <== sr - 36000;
    component hi = Num2Bits(17); hi.in <== 96000 - sr;
}

// |self_os_delta| <= SELF_OS_TOL_MS * sr / 1000, as server/pop/verdict.self_os_ok, in integers:
// 1000*d <= TOL*sr and -1000*d <= TOL*sr. |1000 d| < 2^41, TOL*sr < 2^23: 48-bit checks cannot wrap.
template SelfOsOk() {
    signal input sod;      // signed, as a field element (SignedI32)
    signal input sr;
    var TOL = 50;
    component a = Num2Bits(48); a.in <== TOL * sr - 1000 * sod;
    component b = Num2Bits(48); b.in <== TOL * sr + 1000 * sod;
}

// NEAR iff IMPOSSIBLE < flight < NEAR, flight = c/2 * (hA/srA - hB/srB) cm, exactly as server decide():
// flight <= -20 is impossible_flight, flight >= 60 is too_far. Multiply through by 2*srA*srB > 0:
//   c*N > 2*IMPOSSIBLE*S  and  c*N < 2*NEAR*S,   N = hA*srB - hB*srA,  S = srA*srB.
// Inputs: halves are signed i32 field elements, rates range-checked to [36000, 96000] (< 2^17) by the caller.
// |c*N| < 34300 * 2^31 * 2^17 * 2 < 2^65, 2*NEAR*S < 2^41: a 70-bit check of (value - 1) proves value >= 1.
template NearCross() {
    signal input hA;
    signal input hB;
    signal input srA;
    signal input srB;
    var C = 34300;
    var IMPOSSIBLE = -20;
    var NEAR = 60;
    signal t1 <== hA * srB;
    signal t2 <== hB * srA;
    signal S <== srA * srB;
    signal N <== t1 - t2;
    component gtLo = Num2Bits(70); gtLo.in <== C * N - 2 * IMPOSSIBLE * S - 1;
    component ltHi = Num2Bits(70); ltHi.in <== 2 * NEAR * S - C * N - 1;
}

// Two-role statement on POPT v1.
// Public: nonceHi, nonceLo, attempt, issuerX, issuerY, validAt, srA, srB (each phone's signed rate).
// Private: both device pubs (X||Y), halves, rec_sha256s, the three timestamps, self_os_deltas, commit_hashes,
//          device signatures (r, s^-1), credential expiries and issuer signatures.
// Accepts iff: both transcripts are rebuilt byte for byte from shared nonce/attempt with roles 'A'/'B' and
// crossed keys, each is ECDSA-signed by its device key, each device key has an unexpired issuer credential,
// pubA != pubB, both rates in [SR_MIN, SR_MAX], both |self_os_delta| within tolerance, and -20 < flight < 60 cm.
template PoptPair(CRED_V) {
    signal input nonceHi;
    signal input nonceLo;
    signal input attempt;
    signal input issuerX;
    signal input issuerY;
    signal input validAt;
    signal input srA;
    signal input srB;

    signal input pubA[64];
    signal input pubB[64];
    signal input halfA[4];
    signal input halfB[4];
    signal input recA[32];
    signal input recB[32];
    signal input pfpA[8];
    signal input pfpB[8];
    signal input pntA[8];
    signal input pntB[8];
    signal input rf0A[8];
    signal input rf0B[8];
    signal input sodA[4];
    signal input sodB[4];
    signal input chA[32];
    signal input chB[32];
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
    signal input holdA[32];     // CRED_V == 2: holder commitments inside the credentials (zeros for v1)
    signal input holdB[32];
    signal output holdBitsA[256];
    signal output holdBitsB[256];
    signal output nonceBitsOut[256];

    // public header -> bits (range checks)
    component nH = NumBitsBE(128); nH.in <== nonceHi;
    component nL = NumBitsBE(128); nL.in <== nonceLo;
    signal nonceBits[256];
    for (var i = 0; i < 128; i++) { nonceBits[i] <== nH.out[i]; nonceBits[128 + i] <== nL.out[i]; }
    nonceBitsOut <== nonceBits;
    component at = NumBitsBE(8); at.in <== attempt;
    component sAb = NumBitsBE(32); sAb.in <== srA;
    component sBb = NumBitsBE(32); sBb.in <== srB;
    component va = Num2Bits(64); va.in <== validAt;
    component rgA = SrRange(); rgA.sr <== srA;
    component rgB = SrRange(); rgB.sr <== srB;

    // private bytes -> bits
    component pA = BytesBits(64); pA.in <== pubA;
    component pB = BytesBits(64); pB.in <== pubB;
    component hAb = BytesBits(4); hAb.in <== halfA;
    component hBb = BytesBits(4); hBb.in <== halfB;
    component rA = BytesBits(32); rA.in <== recA;
    component rB = BytesBits(32); rB.in <== recB;
    component fA = BytesBits(8); fA.in <== pfpA;
    component fB = BytesBits(8); fB.in <== pfpB;
    component nA = BytesBits(8); nA.in <== pntA;
    component nB = BytesBits(8); nB.in <== pntB;
    component zA = BytesBits(8); zA.in <== rf0A;
    component zB = BytesBits(8); zB.in <== rf0B;
    component dA = BytesBits(4); dA.in <== sodA;
    component dB = BytesBits(4); dB.in <== sodB;
    component cA = BytesBits(32); cA.in <== chA;
    component cB = BytesBits(32); cB.in <== chB;
    component kA = BytesBits(32); kA.in <== holdA;
    component kB = BytesBits(32); kB.in <== holdB;
    holdBitsA <== kA.out;
    holdBitsB <== kB.out;

    component xA = PackBytes(32); component yA = PackBytes(32);
    component xB = PackBytes(32); component yB = PackBytes(32);
    for (var i = 0; i < 32; i++) {
        xA.in[i] <== pubA[i]; yA.in[i] <== pubA[32 + i];
        xB.in[i] <== pubB[i]; yB.in[i] <== pubB[32 + i];
    }
    // device A != device B (x alone: also rejects Q_B = -Q_A, which is fine)
    component same = IsEqual(); same.in[0] <== xA.out; same.in[1] <== xB.out; same.out === 0;

    // role A transcript: own = A, partner = B, sr = srA
    component tA = PoptV1Digest(0x41);
    tA.nonceBits <== nonceBits; tA.attemptBits <== at.out;
    tA.ownBits <== pA.out; tA.partnerBits <== pB.out; tA.srBits <== sAb.out; tA.halfBits <== hAb.out;
    tA.recBits <== rA.out; tA.pfpBits <== fA.out; tA.pntBits <== nA.out; tA.rf0Bits <== zA.out;
    tA.sodBits <== dA.out; tA.commitBits <== cA.out;
    // role B transcript: own = B, partner = A, sr = srB
    component tB = PoptV1Digest(0x42);
    tB.nonceBits <== nonceBits; tB.attemptBits <== at.out;
    tB.ownBits <== pB.out; tB.partnerBits <== pA.out; tB.srBits <== sBb.out; tB.halfBits <== hBb.out;
    tB.recBits <== rB.out; tB.pfpBits <== fB.out; tB.pntBits <== nB.out; tB.rf0Bits <== zB.out;
    tB.sodBits <== dB.out; tB.commitBits <== cB.out;

    component devA = DeviceChecks(CRED_V);
    devA.transcriptDigest <== tA.digest;
    devA.pubBits <== pA.out; devA.pubX <== xA.out; devA.pubY <== yA.out;
    devA.sigR <== sigA_r; devA.sigSInv <== sigA_sInv;
    devA.expBytes <== expA; devA.commitBits <== kA.out;
    devA.credR <== credA_r; devA.credSInv <== credA_sInv;
    devA.issuerX <== issuerX; devA.issuerY <== issuerY; devA.validAt <== validAt;

    component devB = DeviceChecks(CRED_V);
    devB.transcriptDigest <== tB.digest;
    devB.pubBits <== pB.out; devB.pubX <== xB.out; devB.pubY <== yB.out;
    devB.sigR <== sigB_r; devB.sigSInv <== sigB_sInv;
    devB.expBytes <== expB; devB.commitBits <== kB.out;
    devB.credR <== credB_r; devB.credSInv <== credB_sInv;
    devB.issuerX <== issuerX; devB.issuerY <== issuerY; devB.validAt <== validAt;

    // server checks: self_os_delta tolerance per role, then the verdict with both rates
    component sdA = SignedI32(); sdA.bits <== dA.out;
    component sdB = SignedI32(); sdB.bits <== dB.out;
    component okA = SelfOsOk(); okA.sod <== sdA.out; okA.sr <== srA;
    component okB = SelfOsOk(); okB.sod <== sdB.out; okB.sr <== srB;
    component shA = SignedI32(); shA.bits <== hAb.out;
    component shB = SignedI32(); shB.bits <== hBb.out;
    component near = NearCross();
    near.hA <== shA.out; near.hB <== shB.out; near.srA <== srA; near.srB <== srB;
}

// Default statement: no nullifier (the pair tag comes from the proof-of-human adapters, outside the circuit).
template PoptPairMain() {
    signal input nonceHi;
    signal input nonceLo;
    signal input attempt;
    signal input issuerX;
    signal input issuerY;
    signal input validAt;
    signal input srA;
    signal input srB;
    signal input pubA[64];
    signal input pubB[64];
    signal input halfA[4];
    signal input halfB[4];
    signal input recA[32];
    signal input recB[32];
    signal input pfpA[8];
    signal input pfpB[8];
    signal input pntA[8];
    signal input pntB[8];
    signal input rf0A[8];
    signal input rf0B[8];
    signal input sodA[4];
    signal input sodB[4];
    signal input chA[32];
    signal input chB[32];
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

    component c = PoptPair(1);
    c.nonceHi <== nonceHi; c.nonceLo <== nonceLo; c.attempt <== attempt;
    c.issuerX <== issuerX; c.issuerY <== issuerY; c.validAt <== validAt; c.srA <== srA; c.srB <== srB;
    c.pubA <== pubA; c.pubB <== pubB; c.halfA <== halfA; c.halfB <== halfB; c.recA <== recA; c.recB <== recB;
    c.pfpA <== pfpA; c.pfpB <== pfpB; c.pntA <== pntA; c.pntB <== pntB; c.rf0A <== rf0A; c.rf0B <== rf0B;
    c.sodA <== sodA; c.sodB <== sodB; c.chA <== chA; c.chB <== chB;
    c.sigA_r <== sigA_r; c.sigA_sInv <== sigA_sInv; c.sigB_r <== sigB_r; c.sigB_sInv <== sigB_sInv;
    c.expA <== expA; c.expB <== expB;
    c.credA_r <== credA_r; c.credA_sInv <== credA_sInv; c.credB_r <== credB_r; c.credB_sInv <== credB_sInv;
    for (var i = 0; i < 32; i++) { c.holdA[i] <== 0; c.holdB[i] <== 0; }
}

// Optional variant for the "none" human adapter (docs/pop-human-adapters.md §2): SBcred2 credentials carry a
// holder commitment SHA256("SBhold1"||secret); output nullifier = first 31 bytes of SHA256(secret || nonce),
// bound to the prover's own credential (me = 0: A, 1: B). With a World ID / ENS adapter this is not needed:
// the verifier's UNIQUE(kind, nullifier) store already stops double claims.
template PoptPairNf() {
    signal input nonceHi;
    signal input nonceLo;
    signal input attempt;
    signal input issuerX;
    signal input issuerY;
    signal input validAt;
    signal input srA;
    signal input srB;
    signal output nullifier;
    signal input pubA[64];
    signal input pubB[64];
    signal input halfA[4];
    signal input halfB[4];
    signal input recA[32];
    signal input recB[32];
    signal input pfpA[8];
    signal input pfpB[8];
    signal input pntA[8];
    signal input pntB[8];
    signal input rf0A[8];
    signal input rf0B[8];
    signal input sodA[4];
    signal input sodB[4];
    signal input chA[32];
    signal input chB[32];
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
    signal input holdA[32];
    signal input holdB[32];
    signal input holderSecret[32];
    signal input me;

    component c = PoptPair(2);
    c.nonceHi <== nonceHi; c.nonceLo <== nonceLo; c.attempt <== attempt;
    c.issuerX <== issuerX; c.issuerY <== issuerY; c.validAt <== validAt; c.srA <== srA; c.srB <== srB;
    c.pubA <== pubA; c.pubB <== pubB; c.halfA <== halfA; c.halfB <== halfB; c.recA <== recA; c.recB <== recB;
    c.pfpA <== pfpA; c.pfpB <== pfpB; c.pntA <== pntA; c.pntB <== pntB; c.rf0A <== rf0A; c.rf0B <== rf0B;
    c.sodA <== sodA; c.sodB <== sodB; c.chA <== chA; c.chB <== chB;
    c.sigA_r <== sigA_r; c.sigA_sInv <== sigA_sInv; c.sigB_r <== sigB_r; c.sigB_sInv <== sigB_sInv;
    c.expA <== expA; c.expB <== expB;
    c.credA_r <== credA_r; c.credA_sInv <== credA_sInv; c.credB_r <== credB_r; c.credB_sInv <== credB_sInv;
    c.holdA <== holdA; c.holdB <== holdB;

    component sec = BytesBits(32); sec.in <== holderSecret;
    component nf = Nullifier();
    nf.secretBits <== sec.out;
    nf.nonceBits <== c.nonceBitsOut;
    nullifier <== nf.out;
    me * (me - 1) === 0;
    component hc = HolderCommit();
    hc.secretBits <== sec.out;
    signal sel[256];
    for (var i = 0; i < 256; i++) {
        sel[i] <== c.holdBitsA[i] + me * (c.holdBitsB[i] - c.holdBitsA[i]);
        hc.digest[i] === sel[i];
    }
}

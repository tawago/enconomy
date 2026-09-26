"""Emit the optionA-v2 circom sources (circom 2.2.3, --prime secq256r1).

  python gen_circuit.py p7                         # circuits/p7.circom (Poseidon alpha=7, t=5 and t=16)
  python gen_circuit.py oa2 <delta_ms> <sig|audio> [--win w400|w150|w60]
  python gen_circuit.py pair                       # circuits/oa2_pair.circom

Statement of oa2 (one phone, role R = roleB ? B : A), see README.md for the prose version:
  (1) SIG only: the SBv2 transcript (265 B) is ECDSA-signed by the hidden device key; the key carries an
      SBcred3 credential from the public issuer, not expired at validAt; the holder secret matches the
      credential's Poseidon7 commitment; nullifier = H(TAG_NULL; secret, nonce); own pub != partner pub;
      pairTag = H(TAG_PAIR; nonce, pub_A.x, pub_B.x) (both phones' proofs must output the same tag).
  (2) every opened sample is int16 (16-bit range check), 1,024-sample leaves hash to leaf values whose
      4-ary Poseidon7 paths (depth 6) end at rec_root; self leaves start at the leaf holding
      p_self - delta - HM, partner leaves at the leaf holding a_partner - HM.
  (3) the claimed self curve (I_j, Q_j), j < K = 2 delta + 1, lags p_self - delta + j, is the exact
      correlation of the opened samples with the public template, by Schwartz-Zippel at r, rho =
      Poseidon7 sponge over (nonce, attempt, role, rec_root, p_self, p_partner, delta, a_self, a_partner,
      code_commit, I, Q). The partner I, Q are computed directly (one lag).
  (4) self: score(a_self) >= bar, score(k) < bar for all k in [p_self - delta, a_self),
      a_self in [p_self - delta, p_self + delta].  (bar: env2 * B >= E * cn2, no division)
  (5) partner: score(a_partner) >= bar, a_partner in [p_partner - WPRE, p_partner + WPOST].
  (6) half = a_partner - a_self (A) or a_self - a_partner (B) equals the signed half; output
      halfCommit = H(TAG_HALF; nonce, attempt, roleB, half, salt).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from common2 import HM, L, PARTNER_WINDOWS_MS, SR, delta_samples, geometry

HERE = Path(__file__).resolve().parent
CIRC = HERE / "circuits"
P7 = HERE / "poseidon7"
TAG_LEAF, TAG_NODE, TAG_FS, TAG_HALF, TAG_NULL, TAG_HOLD, TAG_PAIR = 1 + (1024 << 8), 2, 3, 4, 5, 6, 7


def fir_and_B():
    import twin as tw1
    from common2 import T0
    h, g = tw1.fir()
    return [int(v) for v in h], tw1.bconst(g, T0)


def width_W(h, B):
    """Bits for the per-lag comparison value, from worst-case int16 input and 8-bit templates."""
    imax = 32768 * 127 * L
    env2 = 2 * imax * imax
    ymax = 32768 * sum(abs(v) for v in h)
    Emax = L * ymax * ymax
    cmax = Emax * 127 * 127 * L
    dmax = max(cmax, env2 * B) + 1
    W = dmax.bit_length() + 1
    assert W < 250
    return W


# ---------------------------------------------------------------------------- Poseidon7
def emit_p7():
    lines = ["pragma circom 2.2.3;",
             "// Poseidon, x^7 S-box, over the P-256 base field (secq256r1 prime). RESEARCH INSTANTIATION.",
             "// Parameters: poseidon7/params_t{5,16}.json (gen_params.py: reference Grain LFSR, round numbers",
             "// for 128-bit security incl. the 2023/537 bound, +2 R_F / x1.075 R_P margin, Cauchy MDS with",
             "// irreducible charpoly of M^i, i <= 2t). 4 constraints per S-box.", ""]
    for t in (5, 16):
        d = json.loads((P7 / f"params_t{t}.json").read_text())
        C = [str(int(c, 16)) for c in d["C"]]
        M = [[str(int(v, 16)) for v in row] for row in d["M"]]
        lines.append(f"function P7_RF_{t}() {{ return {d['R_F']}; }}")
        lines.append(f"function P7_RP_{t}() {{ return {d['R_P']}; }}")
        lines.append(f"function P7_C_{t}() {{ return [{', '.join(C)}]; }}")
        lines.append(f"function P7_M_{t}() {{ return [{', '.join('[' + ', '.join(r) + ']' for r in M)}]; }}")
    lines.append("""
template Perm7(t) {
    signal input in[t];
    signal output out[t];
    var RF = t == 16 ? P7_RF_16() : P7_RF_5();
    var RP = t == 16 ? P7_RP_16() : P7_RP_5();
    var NC = (RF + RP) * t;
    var C[NC];
    var M[t][t];
    if (t == 16) { C = P7_C_16(); M = P7_M_16(); } else { C = P7_C_5(); M = P7_M_5(); }
    var NSB = RF * t + RP;
    signal x2[NSB];
    signal x4[NSB];
    signal x6[NSB];
    signal x7[NSB];
    var s[t];
    var ns[t];
    for (var i = 0; i < t; i++) { s[i] = in[i]; }
    var sb = 0;
    for (var r = 0; r < RF + RP; r++) {
        for (var i = 0; i < t; i++) { s[i] = s[i] + C[r * t + i]; }
        var full = (r < RF \\ 2) || (r >= RF \\ 2 + RP);
        for (var i = 0; i < t; i++) {
            if (full || i == 0) {
                x2[sb] <== s[i] * s[i];
                x4[sb] <== x2[sb] * x2[sb];
                x6[sb] <== x4[sb] * x2[sb];
                x7[sb] <== x6[sb] * s[i];
                s[i] = x7[sb];
                sb++;
            }
        }
        for (var i = 0; i < t; i++) {
            ns[i] = 0;
            for (var j = 0; j < t; j++) { ns[i] += M[i][j] * s[j]; }
        }
        for (var i = 0; i < t; i++) { s[i] = ns[i]; }
    }
    for (var i = 0; i < t; i++) { out[i] <== s[i]; }
}

// Sponge, t = 16, rate 15, capacity cell 0 = tag. Fixed input length N. Outputs cells 1, 2.
template Sponge16(N, TAG) {
    signal input in[N];
    signal output o1;
    signal output o2;
    var NB = N == 0 ? 1 : (N + 14) \\ 15;
    component p[NB];
    for (var b = 0; b < NB; b++) {
        p[b] = Perm7(16);
        if (b == 0) { p[b].in[0] <== TAG; } else { p[b].in[0] <== p[b - 1].out[0]; }
        for (var i = 0; i < 15; i++) {
            var prev = b == 0 ? 0 : p[b - 1].out[1 + i];
            var idx = 15 * b + i;
            if (idx < N) { p[b].in[1 + i] <== prev + in[idx]; } else { p[b].in[1 + i] <== prev; }
        }
    }
    o1 <== p[NB - 1].out[1];
    o2 <== p[NB - 1].out[2];
}

// 4-ary tree node: Perm7(5)([TAG_NODE, c0..c3])[1]
template Node5() {
    signal input c[4];
    signal output out;
    component p = Perm7(5);
    p.in[0] <== %d;
    for (var i = 0; i < 4; i++) { p.in[1 + i] <== c[i]; }
    out <== p.out[1];
}
""" % TAG_NODE)
    (CIRC / "p7.circom").write_text("\n".join(lines))
    print(CIRC / "p7.circom")


# ---------------------------------------------------------------------------- building blocks
LIB = """pragma circom 2.2.3;
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
    component sp = Sponge16(69, %(TAG_LEAF)d);
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
""" % {"TAG_LEAF": TAG_LEAF}


def emit_lib():
    (CIRC / "oa2lib.circom").write_text(LIB)


# ---------------------------------------------------------------------------- main statement
def emit_oa2(delta_ms, sig, win="w400"):
    delta = delta_samples(delta_ms)
    g = geometry(delta)
    K, NS, NLS, NP, NLP = g["K"], g["NS"], g["NLS"], g["NP"], g["NLP"]
    wpre, wpost = (v * SR // 1000 for v in PARTNER_WINDOWS_MS[win])
    h, B = fir_and_B()
    W = width_W(h, B)
    M = len(h)
    hl = ", ".join(str(v) for v in h)
    name = f"oa2_d{delta_ms}_{'sig' if sig else 'audio'}" + ("" if win == "w400" else f"_{win}")
    nfs = 12 + 2 * K
    src = f"""pragma circom 2.2.3;
// generated by gen_circuit.py: delta={delta} ({delta_ms} ms) K={K} NS={NS} NLS={NLS} NP={NP} NLP={NLP}
// window={win} [-{wpre}, +{wpost}] L={L} M={M} HM={HM} B={B} W={W} sig={sig}
include "oa2lib.circom";
{'include "sb.circom";' if sig else ''}

template OA2() {{
    var L = {L};
    var K = {K};
    var DELTA = {delta};
    var HM = {HM};
    var M = {M};
    var NS = {NS};
    var NP = {NP};
    var NLS = {NLS};
    var NLP = {NLP};
    var WPRE = {wpre};
    var WPOST = {wpost};
    var B = {B};
    var h[M] = [{hl}];

    // ---------------- public
    signal input nonceHi;
    signal input nonceLo;
    signal input attempt;
    signal input roleB;
    signal input codeHi;          // code_commit (SHA-256 of the int8 templates) as 2 x 128-bit limbs
    signal input codeLo;
    signal input cIs[L];          // own template (self arrival), 8-bit; verifier derives it
    signal input cQs[L];
    signal input cIp[L];          // partner template
    signal input cQp[L];
    signal output halfCommit;
"""
    if sig:
        src += """    signal input issuerX;
    signal input issuerY;
    signal input sr;
    signal input validAt;
    signal output nullifier;
    signal output pairTag;
    // ---------------- private: signed transcript fields, signatures, credential
    signal input ownPub[64];
    signal input partnerPub[64];
    signal input halfBytes[4];
    signal input recBytes[32];
    signal input pSelfB[4];
    signal input pPartnerB[4];
    signal input deltaB[2];
    signal input aSelfB[4];
    signal input aPartnerB[4];
    signal input ts[8];
    signal input sig_r;
    signal input sig_sInv;
    signal input exp[8];
    signal input cred_r;
    signal input cred_sInv;
    signal input holderSecret;
    signal input holdCommit[32];
"""
    else:
        src += """    // ---------------- public (audio-only variant: the signed fields are given in the clear)
    signal input recRoot;
    signal input pSelf;
    signal input pPartner;
"""
    src += """    signal input salt;
    // ---------------- private: recording openings, claimed curve, arrival selector
    signal input xs[NLS][1024];
    signal input chS[NLS][6][4];
    signal input leafS;
    signal input xp[NLP][1024];
    signal input chP[NLP][6][4];
    signal input leafP;
    signal input I[K];
    signal input Q[K];
    signal input u[K];            // u[j] = [j < a_self - (p_self - delta)]
"""
    if sig:
        src += """
    // ================= (1) transcript, signature, credential
    component hdr = PublicHeader();
    hdr.nonceHi <== nonceHi;
    hdr.nonceLo <== nonceLo;
    hdr.attempt <== attempt;
    hdr.sr <== sr;
    hdr.validAt <== validAt;
    roleB * (roleB - 1) === 0;
    component bO = BytesBits(64); bO.in <== ownPub;
    component bP = BytesBits(64); bP.in <== partnerPub;
    component bH = BytesBits(4); bH.in <== halfBytes;
    component bR = BytesBits(32); bR.in <== recBytes;
    component bPS = BytesBits(4); bPS.in <== pSelfB;
    component bPP = BytesBits(4); bPP.in <== pPartnerB;
    component bD = BytesBits(2); bD.in <== deltaB;
    component bAS = BytesBits(4); bAS.in <== aSelfB;
    component bAP = BytesBits(4); bAP.in <== aPartnerB;
    component bT = BytesBits(8); bT.in <== ts;
    component cH = NumBitsBE(128); cH.in <== codeHi;
    component cL = NumBitsBE(128); cL.in <== codeLo;
    component sha = Sha256(8 * 265);
    var k = 0;
    var magic[4] = [0x53, 0x42, 0x76, 0x32];   // "SBv2"
    for (var i = 0; i < 4; i++) { for (var j = 0; j < 8; j++) { sha.in[k] <== (magic[i] >> (7 - j)) & 1; k++; } }
    for (var i = 0; i < 256; i++) { sha.in[k] <== hdr.nonceBits[i]; k++; }
    for (var i = 0; i < 8; i++) { sha.in[k] <== hdr.attemptBits[i]; k++; }
    for (var j = 0; j < 6; j++) { sha.in[k] <== (0x41 >> (7 - j)) & 1; k++; }
    sha.in[k] <== roleB; k++;
    sha.in[k] <== 1 - roleB; k++;
    for (var i = 0; i < 512; i++) { sha.in[k] <== bO.out[i]; k++; }
    for (var i = 0; i < 512; i++) { sha.in[k] <== bP.out[i]; k++; }
    for (var i = 0; i < 32; i++) { sha.in[k] <== hdr.srBits[i]; k++; }
    for (var i = 0; i < 32; i++) { sha.in[k] <== bH.out[i]; k++; }
    for (var i = 0; i < 256; i++) { sha.in[k] <== bR.out[i]; k++; }
    for (var i = 0; i < 32; i++) { sha.in[k] <== bPS.out[i]; k++; }
    for (var i = 0; i < 32; i++) { sha.in[k] <== bPP.out[i]; k++; }
    for (var i = 0; i < 16; i++) { sha.in[k] <== bD.out[i]; k++; }
    for (var i = 0; i < 32; i++) { sha.in[k] <== bAS.out[i]; k++; }
    for (var i = 0; i < 32; i++) { sha.in[k] <== bAP.out[i]; k++; }
    for (var i = 0; i < 128; i++) { sha.in[k] <== cH.out[i]; k++; }
    for (var i = 0; i < 128; i++) { sha.in[k] <== cL.out[i]; k++; }
    for (var j = 0; j < 8; j++) { sha.in[k] <== (1 >> (7 - j)) & 1; k++; }
    for (var i = 0; i < 64; i++) { sha.in[k] <== bT.out[i]; k++; }

    component xO = PackBytes(32); component yO = PackBytes(32); component xP = PackBytes(32);
    for (var i = 0; i < 32; i++) { xO.in[i] <== ownPub[i]; yO.in[i] <== ownPub[32 + i]; xP.in[i] <== partnerPub[i]; }
    component dsig = VerifyDigestSig();
    dsig.digest <== sha.out;
    dsig.r <== sig_r;
    dsig.sInv <== sig_sInv;
    dsig.pubX <== xO.out;
    dsig.pubY <== yO.out;

    // credential SBcred3 = "SBcred3" | pub | expiry | holder_commit, signed by the issuer
    component bE = BytesBits(8); bE.in <== exp;
    component bC = BytesBits(32); bC.in <== holdCommit;
    component csha = Sha256(8 * 111);
    var kc = 0;
    var cmag[7] = [0x53, 0x42, 0x63, 0x72, 0x65, 0x64, 0x33];
    for (var i = 0; i < 7; i++) { for (var j = 0; j < 8; j++) { csha.in[kc] <== (cmag[i] >> (7 - j)) & 1; kc++; } }
    for (var i = 0; i < 512; i++) { csha.in[kc] <== bO.out[i]; kc++; }
    for (var i = 0; i < 64; i++) { csha.in[kc] <== bE.out[i]; kc++; }
    for (var i = 0; i < 256; i++) { csha.in[kc] <== bC.out[i]; kc++; }
    component isig = VerifyDigestSig();
    isig.digest <== csha.out;
    isig.r <== cred_r;
    isig.sInv <== cred_sInv;
    isig.pubX <== issuerX;
    isig.pubY <== issuerY;
    component expV = PackBytes(8); expV.in <== exp;
    component notExpired = LessEqThan(64);
    notExpired.in[0] <== validAt;
    notExpired.in[1] <== expV.out;
    notExpired.out === 1;

    // holder secret bound to the credential; nullifier; own != partner; pair tag
    component hc = Sponge16(1, %(TAG_HOLD)d); hc.in[0] <== holderSecret;
    component hcv = PackBytes(32); hcv.in <== holdCommit;
    hcv.out === hc.o1;
    component nf = Sponge16(3, %(TAG_NULL)d);
    nf.in[0] <== holderSecret; nf.in[1] <== nonceHi; nf.in[2] <== nonceLo;
    nullifier <== nf.o1;
    component same = IsEqual(); same.in[0] <== xO.out; same.in[1] <== xP.out; same.out === 0;
    signal xA <== xO.out + roleB * (xP.out - xO.out);
    signal xB <== xP.out + roleB * (xO.out - xP.out);
    component pt = Sponge16(4, %(TAG_PAIR)d);
    pt.in[0] <== nonceHi; pt.in[1] <== nonceLo; pt.in[2] <== xA; pt.in[3] <== xB;
    pairTag <== pt.o1;

    // transcript values
    component vR = PackBytes(32); vR.in <== recBytes;
    component vPS = PackBytes(4); vPS.in <== pSelfB;
    component vPP = PackBytes(4); vPP.in <== pPartnerB;
    component vD = PackBytes(2); vD.in <== deltaB;
    component vAS = PackBytes(4); vAS.in <== aSelfB;
    component vAP = PackBytes(4); vAP.in <== aPartnerB;
    component vH = SignedI32(); vH.bits <== bH.out;
    vD.out === DELTA;
    signal recRoot <== vR.out;
    signal pSelf <== vPS.out;
    signal pPartner <== vPP.out;
    signal aSelf <== vAS.out;
    signal aPartner <== vAP.out;
""" % {"TAG_HOLD": TAG_HOLD, "TAG_NULL": TAG_NULL, "TAG_PAIR": TAG_PAIR}
    else:
        src += """
    roleB * (roleB - 1) === 0;
    signal input aSelf;
    signal input aPartner;
"""
    src += f"""
    // ================= (2) open the recording: self and partner regions
    // self region starts at the leaf holding p_self - delta - HM; oS = offset inside that leaf
    signal oS <== pSelf - DELTA - HM - 1024 * leafS;
    component oSb = Num2Bits(10); oSb.in <== oS;
    component opS = OpenLeaves(NLS);
    opS.x <== xs; opS.first <== leafS; opS.ch <== chS; opS.root <== recRoot;
    signal oP <== aPartner - HM - 1024 * leafP;
    component oPb = Num2Bits(10); oPb.in <== oP;
    component opP = OpenLeaves(NLP);
    opP.x <== xp; opP.first <== leafP; opP.ch <== chP; opP.root <== recRoot;
    // shift to the window start (barrel shifter over the 10 offset bits)
    component shS = Barrel1024(NLS * 1024, NS);
    for (var i = 0; i < NLS; i++) {{ for (var j = 0; j < 1024; j++) {{ shS.in[1024 * i + j] <== xs[i][j]; }} }}
    shS.bits <== oSb.out;
    component shP = Barrel1024(NLP * 1024, NP);
    for (var i = 0; i < NLP; i++) {{ for (var j = 0; j < 1024; j++) {{ shP.in[1024 * i + j] <== xp[i][j]; }} }}
    shP.bits <== oPb.out;
    // shS.out[i] = x[p_self - delta - HM + i];  shP.out[i] = x[a_partner - HM + i]

    // ================= (3) Fiat-Shamir challenge over everything committed, Freivalds on the self curve
    component fs = Sponge16({nfs}, {TAG_FS + (nfs << 8)});
    fs.in[0] <== nonceHi; fs.in[1] <== nonceLo; fs.in[2] <== attempt; fs.in[3] <== roleB;
    fs.in[4] <== recRoot; fs.in[5] <== pSelf; fs.in[6] <== pPartner; fs.in[7] <== DELTA;
    fs.in[8] <== aSelf; fs.in[9] <== aPartner; fs.in[10] <== codeHi; fs.in[11] <== codeLo;
    for (var j = 0; j < K; j++) {{ fs.in[12 + j] <== I[j]; fs.in[12 + K + j] <== Q[j]; }}
    signal r <== fs.o1;
    signal rho <== fs.o2;
    var N = K + L - 1;
    signal pw[N];
    pw[0] <== 1;
    for (var i = 1; i < N; i++) {{ pw[i] <== pw[i - 1] * r; }}
    signal S[N + 1];
    S[0] <== 0;
    for (var m = 1; m <= N; m++) {{ S[m] <== S[m - 1] + pw[m - 1] * shS.out[HM + m - 1]; }}
    signal v[L];
    signal uu[L];
    signal acc[L + 1];
    acc[0] <== 0;
    for (var n = 0; n < L; n++) {{
        v[n] <== rho * cQs[n];
        uu[n] <== (cIs[n] + v[n]) * pw[L - 1 - n];
        acc[n + 1] <== acc[n] + uu[n] * (S[n + K] - S[n]);
    }}
    signal li[K + 1];
    signal lq[K + 1];
    li[0] <== 0;
    lq[0] <== 0;
    for (var j = 0; j < K; j++) {{
        li[j + 1] <== li[j] + pw[j] * I[j];
        lq[j + 1] <== lq[j] + pw[j] * Q[j];
    }}
    signal lhs <== li[K] + rho * lq[K];
    signal lhs2 <== pw[L - 1] * lhs;
    lhs2 === acc[L];

    // ================= normalization (self): E_j = sum_(m<L) y[j+m]^2, y = FIR(x); cn2 = |cI|^2
    signal EY[N + 1];
    EY[0] <== 0;
    for (var m = 0; m < N; m++) {{
        var yl = 0;
        for (var t = 0; t < M; t++) {{ if (h[t] != 0) {{ yl += h[t] * shS.out[m + t]; }} }}
        EY[m + 1] <== EY[m] + yl * yl;
    }}
    signal cna[L + 1];
    cna[0] <== 0;
    for (var n = 0; n < L; n++) {{ cna[n + 1] <== cna[n] + cIs[n] * cIs[n]; }}

    // ================= (4) self arrival: first lag >= bar in [p_self - delta, p_self + delta]
    u[K - 1] === 0;
    var usum = 0;
    for (var j = 0; j < K; j++) {{
        u[j] * (u[j] - 1) === 0;
        if (j > 0) {{ u[j] * (1 - u[j - 1]) === 0; }}
        usum += u[j];
    }}
    usum === aSelf - pSelf + DELTA;         // => a_self in [p_self - delta, p_self + delta]
    signal C[K];
    signal i2[K];
    signal env2[K];
    signal pu[K];
    signal pe[K];
    component rk[K];
    for (var j = 0; j < K; j++) {{
        C[j] <== (EY[j + L] - EY[j]) * cna[L];
        i2[j] <== I[j] * I[j];
        env2[j] <== i2[j] + Q[j] * Q[j];
        var D = C[j] - B * env2[j];         // D > 0  <=>  score < bar
        var e = (j == 0 ? 1 : u[j - 1]) - u[j];   // one-hot at the arrival
        pu[j] <== u[j] * (D - 1);            // before the arrival: D - 1 >= 0
        pe[j] <== e * D;                     // at the arrival: -D >= 0
        rk[j] = Range({W});
        rk[j].in <== pu[j] - pe[j];
    }}

    // ================= (5) partner arrival: one lag, score >= bar, inside the pinned window
    signal ipI[L + 1];
    signal ipQ[L + 1];
    ipI[0] <== 0;
    ipQ[0] <== 0;
    for (var n = 0; n < L; n++) {{
        ipI[n + 1] <== ipI[n] + cIp[n] * shP.out[HM + n];
        ipQ[n + 1] <== ipQ[n] + cQp[n] * shP.out[HM + n];
    }}
    signal EP[L + 1];
    EP[0] <== 0;
    for (var m = 0; m < L; m++) {{
        var yl = 0;
        for (var t = 0; t < M; t++) {{ if (h[t] != 0) {{ yl += h[t] * shP.out[m + t]; }} }}
        EP[m + 1] <== EP[m] + yl * yl;
    }}
    signal cnp[L + 1];
    cnp[0] <== 0;
    for (var n = 0; n < L; n++) {{ cnp[n + 1] <== cnp[n] + cIp[n] * cIp[n]; }}
    signal pi2 <== ipI[L] * ipI[L];
    signal penv2 <== pi2 + ipQ[L] * ipQ[L];
    signal pC <== EP[L] * cnp[L];
    component rp = Range({W});
    rp.in <== B * penv2 - pC;
    component w0 = Num2Bits(33); w0.in <== aPartner - pPartner + WPRE;
    component w1 = Num2Bits(33); w1.in <== pPartner + WPOST - aPartner;

    // ================= (6) half and its commitment
    signal half <== (1 - 2 * roleB) * (aPartner - aSelf);
"""
    if sig:
        src += "    vH.out === half;\n"
    src += f"""    component hcm = Sponge16(6, {TAG_HALF});
    hcm.in[0] <== nonceHi; hcm.in[1] <== nonceLo; hcm.in[2] <== attempt; hcm.in[3] <== roleB;
    hcm.in[4] <== half; hcm.in[5] <== salt;
    halfCommit <== hcm.o1;
}}
"""
    if sig:
        pubs = "nonceHi, nonceLo, attempt, roleB, codeHi, codeLo, cIs, cQs, cIp, cQp, issuerX, issuerY, sr, validAt"
    else:
        pubs = "nonceHi, nonceLo, attempt, roleB, codeHi, codeLo, cIs, cQs, cIp, cQp, recRoot, pSelf, pPartner"
    src += f"\ncomponent main {{public [{pubs}]}} = OA2();\n"
    (CIRC / "main").mkdir(exist_ok=True, parents=True)
    out = CIRC / "main" / f"{name}.circom"
    out.write_text(src)
    meta = {"name": name, "delta": delta, "delta_ms": delta_ms, "sig": sig, "win": win, "wpre": wpre,
            "wpost": wpost, "B": B, "W": W, "fir": h, **g, "public_order": pubs.replace(" ", "").split(",")}
    (CIRC / "main" / f"{name}.json").write_text(json.dumps(meta, indent=1))
    print(out)


def emit_pair():
    src = f"""pragma circom 2.2.3;
// Pair statement: the two per-phone half commitments (same nonce/attempt, roles A and B) open to halves
// with dLo < halfA - halfB < dHi  (-20 cm < flight < 60 cm; verifier computes dLo, dHi from sr).
include "oa2lib.circom";

template Pair() {{
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
    component ca = Sponge16(6, {TAG_HALF});
    ca.in[0] <== nonceHi; ca.in[1] <== nonceLo; ca.in[2] <== attempt; ca.in[3] <== 0;
    ca.in[4] <== halfA; ca.in[5] <== saltA;
    ca.o1 === commitA;
    component cb = Sponge16(6, {TAG_HALF});
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
}}

component main {{public [nonceHi, nonceLo, attempt, commitA, commitB, dLo, dHi]}} = Pair();
"""
    (CIRC / "main").mkdir(exist_ok=True, parents=True)
    (CIRC / "main" / "oa2_pair.circom").write_text(src)
    print(CIRC / "main" / "oa2_pair.circom")


if __name__ == "__main__":
    CIRC.mkdir(exist_ok=True)
    a = sys.argv[1:]
    if a[0] == "p7":
        emit_p7()
        emit_lib()
    elif a[0] == "oa2":
        win = a[a.index("--win") + 1] if "--win" in a else "w400"
        emit_lib()
        emit_oa2(int(a[1]), a[2] == "sig", win)
    elif a[0] == "pair":
        emit_lib()
        emit_pair()

// Sound-bound co-presence statement as a longfellow-zk circuit over Fp256Base
// (the P-256 base field). Single field, single circuit, like the vendor's
// "small" toy credential (lib/circuits/tests/anoncred/small.h).
//
// Public:  issuer pk (x,y), nonce[32], attempt, now (u64 BE), nullifier[32]
// Private: per role R in {A,B}: device pk bytes[64], half i32, rec_hash[32],
//          ts u64, cred expiry u64, issuer sig over sha256(cred_R),
//          device sig over sha256(transcript_R), SHA block witnesses;
//          shared: sr u32, holder_secret[32], two 64-bit range witnesses.
// Checks:
//   cred_R  = "SBcred1" | dpk_R | exp_R ;  ECDSA_issuer(sha256(cred_R)) ok ; now <= exp_R
//   tr_R    = "SBv1" | nonce | attempt | role_R | dpk_R | dpk_other | sr | half_R
//             | rec_R | 0x01 | ts_R ;       ECDSA_dpk_R(sha256(tr_R)) ok
//   d = half_A - half_B (signed);  -20 < 17150*d/sr < 60   <=>
//        1715*d + 2*sr - 1 in [0,2^64)  and  6*sr - 1715*d - 1 in [0,2^64)
//   nullifier == sha256(holder_secret | nonce)
#ifndef SBZK_CIRCUIT_H_
#define SBZK_CIRCUIT_H_

#include <cstddef>
#include <cstdint>
#include <vector>

#include "circuits/ecdsa/verify_circuit.h"
#include "circuits/logic/bit_plucker.h"
#include "circuits/logic/memcmp.h"
#include "circuits/sha/flatsha256_circuit.h"

namespace sbzk {
using namespace proofs;

constexpr size_t kTrLen = 215, kTrBlocks = 4;
constexpr size_t kCredLen = 79, kCredBlocks = 2;
constexpr size_t kNullLen = 64, kNullBlocks = 2;
constexpr size_t kRangeBits = 64;

template <class LogicCircuit, class Field, class EC>
class SoundBound {
 public:
  using EltW = typename LogicCircuit::EltW;
  using BitW = typename LogicCircuit::BitW;
  using Elt = typename LogicCircuit::Elt;
  using v8 = typename LogicCircuit::v8;
  using v32 = typename LogicCircuit::v32;
  using vR = typename LogicCircuit::template bitvec<kRangeBits>;
  using Nat = typename Field::N;
  using Ecdsa = VerifyCircuit<LogicCircuit, Field, EC>;
  using Flatsha = FlatSHA256Circuit<LogicCircuit, BitPlucker<LogicCircuit, 3>>;
  using ShaBW = typename Flatsha::BlockWitness;
  using packed_v32 = typename Flatsha::packed_v32;

  struct Public {
    EltW ipk_x, ipk_y;
    v8 nonce[32];
    v8 attempt;
    v8 now[8];
    v8 nullifier[32];
    void input(const LogicCircuit& lc) {
      ipk_x = lc.eltw_input();
      ipk_y = lc.eltw_input();
      for (auto& b : nonce) b = lc.template vinput<8>();
      attempt = lc.template vinput<8>();
      for (auto& b : now) b = lc.template vinput<8>();
      for (auto& b : nullifier) b = lc.template vinput<8>();
    }
  };

  struct Role {
    v8 dpk[64];
    v8 half[4];
    v8 rec[32];
    v8 ts[8];
    v8 exp[8];
    typename Ecdsa::Witness cred_sig, dev_sig;
    ShaBW cred_sha[kCredBlocks], tr_sha[kTrBlocks];
    void input(const LogicCircuit& lc) {
      for (auto& b : dpk) b = lc.template vinput<8>();
      for (auto& b : half) b = lc.template vinput<8>();
      for (auto& b : rec) b = lc.template vinput<8>();
      for (auto& b : ts) b = lc.template vinput<8>();
      for (auto& b : exp) b = lc.template vinput<8>();
      cred_sig.input(lc);
      dev_sig.input(lc);
      for (auto& w : cred_sha) w.input(lc);
      for (auto& w : tr_sha) w.input(lc);
    }
  };

  struct Witness {
    Role r[2];
    v8 sr[4];
    v8 holder[32];
    ShaBW null_sha[kNullBlocks];
    vR lo, hi;
    void input(const LogicCircuit& lc) {
      r[0].input(lc);
      r[1].input(lc);
      for (auto& b : sr) b = lc.template vinput<8>();
      for (auto& b : holder) b = lc.template vinput<8>();
      for (auto& w : null_sha) w.input(lc);
      lo = lc.template vinput<kRangeBits>();
      hi = lc.template vinput<kRangeBits>();
    }
  };

  SoundBound(const LogicCircuit& lc, const EC& ec, const Nat& order)
      : lc_(lc), ec_(ec), order_(order), sha_(lc) {}

  void assert_statement(const Public& pub, const Witness& w) const {
    Ecdsa ecc(lc_, ec_, order_);
    const Memcmp<LogicCircuit> CMP(lc_);

    for (size_t R = 0; R < 2; ++R) {
      const Role& me = w.r[R];
      const Role& other = w.r[1 - R];
      EltW dpkx = repack(&me.dpk[0]);
      EltW dpky = repack(&me.dpk[32]);

      // ---- credential: "SBcred1" | dpk | exp
      std::vector<v8> cred;
      put_const(cred, "SBcred1", 7);
      for (auto& b : me.dpk) cred.push_back(b);
      for (auto& b : me.exp) cred.push_back(b);
      pad(cred, kCredLen, kCredBlocks);
      const packed_v32* hc = sha_fixed(cred, me.cred_sha, kCredBlocks);
      ecc.verify_signature3(pub.ipk_x, pub.ipk_y, digest_elt(hc), me.cred_sig);
      lc_.assert1(CMP.leq(8, pub.now, me.exp));

      // ---- transcript
      std::vector<v8> tr;
      put_const(tr, "SBv1", 4);
      for (auto& b : pub.nonce) tr.push_back(b);
      tr.push_back(pub.attempt);
      tr.push_back(lc_.template vbit<8>(R == 0 ? 0x41 : 0x42));
      for (auto& b : me.dpk) tr.push_back(b);
      for (auto& b : other.dpk) tr.push_back(b);
      for (auto& b : w.sr) tr.push_back(b);
      for (auto& b : me.half) tr.push_back(b);
      for (auto& b : me.rec) tr.push_back(b);
      tr.push_back(lc_.template vbit<8>(1));  // n_ts = 1
      for (auto& b : me.ts) tr.push_back(b);
      check(tr.size() == kTrLen, "transcript length");
      pad(tr, kTrLen, kTrBlocks);
      const packed_v32* ht = sha_fixed(tr, me.tr_sha, kTrBlocks);
      ecc.verify_signature3(dpkx, dpky, digest_elt(ht), me.dev_sig);
    }

    // ---- threshold: -20 cm < 17150*(hA-hB)/sr < 60 cm
    EltW hA = signed32(w.r[0].half), hB = signed32(w.r[1].half);
    EltW sr = lc_.as_scalar(be32(w.sr));
    EltW d = lc_.sub(hA, hB);
    EltW t = lc_.mul(lc_.elt(1715), d);
    // lo = 1715 d + 2 sr - 1
    EltW lo = lc_.sub(lc_.add(t, lc_.mul(lc_.elt(2), sr)), lc_.konst(1));
    // hi = 6 sr - 1715 d - 1
    EltW hi = lc_.sub(lc_.sub(lc_.mul(lc_.elt(6), sr), t), lc_.konst(1));
    lc_.assert_eq(lc_.as_scalar(w.lo), lo);
    lc_.assert_eq(lc_.as_scalar(w.hi), hi);

    // ---- nullifier = sha256(holder | nonce)
    std::vector<v8> nm;
    for (auto& b : w.holder) nm.push_back(b);
    for (auto& b : pub.nonce) nm.push_back(b);
    pad(nm, kNullLen, kNullBlocks);
    const packed_v32* hn = sha_fixed(nm, w.null_sha, kNullBlocks);
    for (size_t j = 0; j < 8; ++j) {
      v32 word = sha_.bp_.unpack_v32(hn[j]);
      for (size_t m = 0; m < 4; ++m) {
        for (size_t b = 0; b < 8; ++b) {
          lc_.assert_eq(pub.nullifier[4 * j + m][b], word[8 * (3 - m) + b]);
        }
      }
    }
  }

 private:
  void put_const(std::vector<v8>& v, const char* s, size_t n) const {
    for (size_t i = 0; i < n; ++i) v.push_back(lc_.template vbit<8>((uint8_t)s[i]));
  }
  // SHA-256 padding with constant bytes for a fixed-length message.
  void pad(std::vector<v8>& v, size_t len, size_t nblocks) const {
    check(v.size() == len, "pad: len");
    v.push_back(lc_.template vbit<8>(0x80));
    while (v.size() < 64 * nblocks - 8) v.push_back(lc_.template vbit<8>(0));
    uint64_t bits = 8 * (uint64_t)len;
    for (size_t i = 0; i < 8; ++i) v.push_back(lc_.template vbit<8>((bits >> (56 - 8 * i)) & 0xff));
    check(v.size() == 64 * nblocks, "pad: blocks");
  }
  // Chain of block transforms over a fully padded message; returns final H.
  const packed_v32* sha_fixed(const std::vector<v8>& m, const ShaBW bw[], size_t nb) const {
    static const uint64_t iv[8] = {0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
                                   0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u};
    v32 H0[8];
    for (size_t i = 0; i < 8; ++i) H0[i] = lc_.template vbit<32>(iv[i]);
    for (size_t b = 0; b < nb; ++b) {
      v32 in[16];
      for (size_t i = 0; i < 16; ++i) {
        const v8* p = &m[64 * b + 4 * i];
        in[i] = lc_.vappend(lc_.vappend(p[3], p[2]), lc_.vappend(p[1], p[0]));
      }
      if (b == 0) {
        sha_.assert_transform_block(in, H0, bw[b].outw, bw[b].oute, bw[b].outa, bw[b].h1);
      } else {
        sha_.assert_transform_block(in, bw[b - 1].h1, bw[b].outw, bw[b].oute, bw[b].outa,
                                    bw[b].h1);
      }
    }
    return bw[nb - 1].h1;
  }
  // Big-endian 256-bit digest as a field element (same as small.h repack32).
  EltW digest_elt(const packed_v32 H[8]) const {
    EltW h = lc_.konst(0);
    Elt twok = lc_.one();
    for (size_t j = 8; j-- > 0;) {
      auto hj = sha_.bp_.unpack_v32(H[j]);
      for (size_t k = 0; k < 32; ++k) {
        h = lc_.axpy(h, twok, lc_.eval(hj[k]));
        lc_.f_.add(twok, twok);
      }
    }
    return h;
  }
  // 32 big-endian bytes -> field element (same as small.h repack).
  EltW repack(const v8 in[]) const {
    EltW h = lc_.konst(0);
    EltW base = lc_.konst(0x2);
    for (size_t i = 0; i < 32; ++i) {
      for (size_t j = 0; j < 8; ++j) {
        h = lc_.add(lc_.eval(in[i][7 - j]), lc_.mul(h, base));
      }
    }
    return h;
  }
  v32 be32(const v8 b[4]) const {
    return lc_.vappend(lc_.vappend(b[3], b[2]), lc_.vappend(b[1], b[0]));
  }
  // two's complement i32 -> field element (value in (-2^31, 2^31))
  EltW signed32(const v8 b[4]) const {
    v32 v = be32(b);
    EltW u = lc_.as_scalar(v);
    return lc_.sub(u, lc_.mul(lc_.elt(1ull << 32), lc_.eval(v[31])));
  }

  const LogicCircuit& lc_;
  const EC& ec_;
  const Nat& order_;
  Flatsha sha_;
};

}  // namespace sbzk
#endif
